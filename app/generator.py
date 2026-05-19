from __future__ import annotations

import json
import logging
import os
import re
import asyncio
import ast
import builtins
import difflib
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from app.schemas import (
    BugCard,
    GeneratePackRequest,
    Language,
    LessonFlow,
    LessonPack,
    Metadata,
    RunSuggestions,
)


load_dotenv()

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_THINKING_TYPE = "enabled"
DEFAULT_REASONING_EFFORT = "high"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_GENERATE_READ_TIMEOUT_SECONDS = 120.0
DEFAULT_STREAM_READ_TIMEOUT_SECONDS = 180.0
DEFAULT_WRITE_TIMEOUT_SECONDS = 30.0
DEFAULT_POOL_TIMEOUT_SECONDS = 10.0
LOGGER = logging.getLogger(__name__)


STREAM_MESSAGES: dict[Language, dict[str, str]] = {
    "zh-Hant": {
        "preparing": "正在準備生成請求...",
        "ai_failed": "AI 串流失敗，正在準備 fallback 教材包...",
        "using_fallback": "使用 fallback 教材包...",
        "lesson_flow": "Lesson flow 已就緒。",
        "master_code": "Master code 已就緒。",
        "buggy_code": "Buggy code 已就緒。",
        "debug_cards": "Debug cards 已就緒。",
        "streaming": "正在從 {model} 串流輸出...",
        "no_cards": "串流 JSON 沒有有效 debug cards，正在準備 fallback 教材包...",
        "invalid_json": "串流 JSON 驗證失敗，正在準備 fallback 教材包...",
    },
    "en": {
        "preparing": "Preparing generation request...",
        "ai_failed": "AI stream failed; preparing fallback pack...",
        "using_fallback": "Using fallback pack...",
        "lesson_flow": "Lesson flow ready.",
        "master_code": "Master code ready.",
        "buggy_code": "Buggy code ready.",
        "debug_cards": "Debug cards ready.",
        "streaming": "Streaming from {model}...",
        "no_cards": "Streamed JSON had no valid debug cards; preparing fallback pack...",
        "invalid_json": "Streamed JSON failed validation; preparing fallback pack...",
    },
}


LESSON_FLOW_PARTIAL_FIELDS = (
    ("warm_up", "warmUp"),
    ("build_activity", "buildActivity"),
    ("debug_activity", "debugActivity"),
    ("wrap_up", "wrapUp"),
    ("teacher_notes", "teacherNotes"),
)
RUN_SUGGESTIONS_SECTION_ID = "runSuggestions"
STREAMING_LESSON_FLOW_SECTION_IDS = tuple(section_id for _, section_id in LESSON_FLOW_PARTIAL_FIELDS) + (
    RUN_SUGGESTIONS_SECTION_ID,
)
JSON_FIELD_NAMES = (
    "topic",
    "level",
    "duration",
    "lesson_title",
    "key_concepts",
    "lesson_flow",
    "run_suggestions",
    "master_code",
    "starter_code",
    "buggy_code",
    "bug_cards",
    "metadata",
    "warm_up",
    "build_activity",
    "debug_activity",
    "wrap_up",
    "teacher_notes",
    "master_input",
    "buggy_input",
    "note",
    "id",
    "title",
    "error_type",
    "teaching_concept",
    "code_location",
    "classroom_symptom",
    "guiding_questions",
    "progressive_hints",
    "teacher_explanation",
    "fix_summary",
    "extension_activity",
    "related_code_snippet",
    "severity",
    "generated_at",
    "difficulty",
    "schema_version",
    "source",
    "language",
)
MISSING_FIELD_COMMA_RE = re.compile(
    r'([}\]"])\s*\n(\s*"(' + "|".join(re.escape(name) for name in JSON_FIELD_NAMES) + r')"\s*:)'
)

_JSON_MISSING = object()
_JSON_DECODER = json.JSONDecoder()


LEVEL_LABELS_EN = {
    "小學": "Primary",
    "初中": "Junior secondary",
    "高中": "Senior secondary",
}

DURATION_LABELS_EN = {
    "30 分鐘": "30 minutes",
    "1 小時": "1 hour",
    "90 分鐘": "90 minutes",
}


def _stream_message(language: Language, key: str, **values: Any) -> str:
    template = STREAM_MESSAGES.get(language, STREAM_MESSAGES["zh-Hant"])[key]
    return template.format(**values)


def _level_label(level: str, language: Language) -> str:
    if language == "en":
        return LEVEL_LABELS_EN.get(level, level)
    return level


def _duration_label(duration: str, language: Language) -> str:
    if language == "en":
        return DURATION_LABELS_EN.get(duration, duration)
    return duration


def api_status() -> dict[str, Any]:
    return {
        "configured": bool(os.getenv("DEEPSEEK_API_KEY")),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
        "model": os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
        "thinking": DEFAULT_THINKING_TYPE,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
    }


def _deepseek_timeout(*, stream: bool) -> httpx.Timeout:
    read_name = "DEEPSEEK_STREAM_READ_TIMEOUT_SECONDS" if stream else "DEEPSEEK_READ_TIMEOUT_SECONDS"
    read_default = DEFAULT_STREAM_READ_TIMEOUT_SECONDS if stream else DEFAULT_GENERATE_READ_TIMEOUT_SECONDS
    return httpx.Timeout(
        connect=_env_timeout_seconds("DEEPSEEK_CONNECT_TIMEOUT_SECONDS", DEFAULT_CONNECT_TIMEOUT_SECONDS),
        read=_env_timeout_seconds(read_name, read_default),
        write=_env_timeout_seconds("DEEPSEEK_WRITE_TIMEOUT_SECONDS", DEFAULT_WRITE_TIMEOUT_SECONDS),
        pool=_env_timeout_seconds("DEEPSEEK_POOL_TIMEOUT_SECONDS", DEFAULT_POOL_TIMEOUT_SECONDS),
    )


def _env_timeout_seconds(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError:
        LOGGER.warning("Ignoring invalid %s=%r; using %.1fs", name, raw_value, default)
        return default

    if value <= 0:
        LOGGER.warning("Ignoring non-positive %s=%r; using %.1fs", name, raw_value, default)
        return default
    return value


def _describe_deepseek_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        body = exc.response.text.strip().replace("\n", " ")
        if len(body) > 300:
            body = f"{body[:300]}..."
        if body:
            return f"{type(exc).__name__}: HTTP {status_code} from DeepSeek: {body}"
        return f"{type(exc).__name__}: HTTP {status_code} from DeepSeek"

    if isinstance(exc, httpx.TimeoutException):
        return f"{type(exc).__name__}: DeepSeek request timed out"

    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return repr(exc)


async def generate_lesson_pack(request: GeneratePackRequest) -> LessonPack:
    if os.getenv("DEEPSEEK_API_KEY"):
        try:
            return await _generate_with_deepseek(request)
        except Exception as exc:
            LOGGER.warning(
                "AI lesson pack generation failed; using fallback: %s",
                _describe_deepseek_error(exc),
                exc_info=True,
            )
            return fallback_pack(request)

    return fallback_pack(request)


async def stream_lesson_pack(request: GeneratePackRequest) -> AsyncIterator[str]:
    yield _stream_event("status", message=_stream_message(request.language, "preparing"))

    if os.getenv("DEEPSEEK_API_KEY"):
        try:
            async for line in _stream_with_deepseek(request):
                yield line
            return
        except Exception as exc:
            LOGGER.warning(
                "AI lesson pack stream failed; using fallback: %s",
                _describe_deepseek_error(exc),
                exc_info=True,
            )
            yield _stream_event("status", message=_stream_message(request.language, "ai_failed"))

    fallback = fallback_pack(request)
    yield _stream_event("status", message=_stream_message(request.language, "using_fallback"))
    for line in _fallback_lesson_flow_partial_events(fallback):
        yield line
        await asyncio.sleep(0.08)
    for key in ("master_code", "buggy_code", "debug_cards"):
        yield _stream_event("delta", text=f"{_stream_message(request.language, key)}\n")
        await asyncio.sleep(0.08)
    yield _stream_event("complete", pack=fallback.model_dump())


async def _generate_with_deepseek(request: GeneratePackRequest) -> LessonPack:
    api_key = os.environ["DEEPSEEK_API_KEY"]
    base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
    payload = _deepseek_payload(request, model=model, stream=False)

    async with httpx.AsyncClient(timeout=_deepseek_timeout(stream=False)) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    data = _extract_json(content)
    data.setdefault("topic", request.topic)
    data.setdefault("level", request.level)
    data.setdefault("duration", request.duration)
    data["metadata"] = {
        **data.get("metadata", {}),
        "generated_at": _now_iso(),
        "difficulty": request.level,
        "schema_version": "1.0",
        "source": "ai",
        "language": request.language,
    }

    normalized = _normalize_lesson_pack_data(data, request.language)

    try:
        pack = LessonPack.model_validate(normalized)
        if not pack.bug_cards:
            raise ValueError("AI lesson pack has no valid bug cards")
        return pack
    except ValueError as exc:
        LOGGER.warning("AI lesson pack failed quality checks; using fallback: %s", exc)
        return fallback_pack(request)
    except ValidationError as exc:
        LOGGER.warning("AI lesson pack failed validation; using fallback: %s", exc.errors())
        return fallback_pack(request)


async def _stream_with_deepseek(request: GeneratePackRequest) -> AsyncIterator[str]:
    api_key = os.environ["DEEPSEEK_API_KEY"]
    base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
    payload = _deepseek_payload(request, model=model, stream=True)

    chunks: list[str] = []
    emitted_flow_sections: set[str] = set()
    yield _stream_event("status", message=_stream_message(request.language, "streaming", model=model))

    async with httpx.AsyncClient(timeout=_deepseek_timeout(stream=True)) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue

                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue

                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                if delta:
                    chunks.append(delta)
                    yield _stream_event("delta", text=delta)
                    content = "".join(chunks)
                    for event in _lesson_flow_partial_events(content, emitted_flow_sections):
                        yield event

    content = "".join(chunks)
    data = _extract_json(content)
    data.setdefault("topic", request.topic)
    data.setdefault("level", request.level)
    data.setdefault("duration", request.duration)
    data["metadata"] = {
        **data.get("metadata", {}),
        "generated_at": _now_iso(),
        "difficulty": request.level,
        "schema_version": "1.0",
        "source": "ai",
        "language": request.language,
    }
    normalized = _normalize_lesson_pack_data(data, request.language)

    try:
        pack = LessonPack.model_validate(normalized)
        if not pack.bug_cards:
            raise ValueError("AI lesson pack has no valid bug cards")
    except ValueError as exc:
        LOGGER.warning("AI lesson pack stream failed quality checks; using fallback: %s", exc)
        yield _stream_event("status", message=_stream_message(request.language, "no_cards"))
        pack = fallback_pack(request)
    except ValidationError as exc:
        LOGGER.warning("AI lesson pack stream failed validation; using fallback: %s", exc.errors())
        yield _stream_event("status", message=_stream_message(request.language, "invalid_json"))
        pack = fallback_pack(request)

    yield _stream_event("complete", pack=pack.model_dump())


def _deepseek_payload(request: GeneratePackRequest, *, model: str, stream: bool) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": _build_system_prompt(request.language),
            },
            {"role": "user", "content": _build_prompt(request)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": DEFAULT_THINKING_TYPE},
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
    }
    if stream:
        payload["stream"] = True
    return payload


def _fallback_lesson_flow_partial_events(pack: LessonPack) -> list[str]:
    flow = pack.lesson_flow
    values = {
        "warmUp": flow.warm_up,
        "buildActivity": flow.build_activity,
        "debugActivity": flow.debug_activity,
        "wrapUp": flow.wrap_up,
        "teacherNotes": flow.teacher_notes,
        RUN_SUGGESTIONS_SECTION_ID: pack.run_suggestions.note,
    }
    return [
        _stream_event("partial", target="lesson_flow", section={"id": section_id, "value": values[section_id]})
        for section_id in STREAMING_LESSON_FLOW_SECTION_IDS
    ]


def _lesson_flow_partial_events(content: str, emitted_sections: set[str]) -> list[str]:
    lesson_flow_start = _json_object_value_start_for_key(content, "lesson_flow")
    events: list[str] = []
    if lesson_flow_start is not None:
        for field_name, section_id in LESSON_FLOW_PARTIAL_FIELDS:
            if section_id in emitted_sections:
                continue
            value = _completed_json_value_for_key(content, field_name, lesson_flow_start)
            if value is _JSON_MISSING:
                continue
            emitted_sections.add(section_id)
            events.append(
                _stream_event(
                    "partial",
                    target="lesson_flow",
                    section={"id": section_id, "value": value},
                )
            )

    run_suggestions_start = _json_object_value_start_for_key(content, "run_suggestions")
    if run_suggestions_start is None or RUN_SUGGESTIONS_SECTION_ID in emitted_sections:
        return events

    note = _completed_json_value_for_key(content, "note", run_suggestions_start)
    if note is _JSON_MISSING:
        return events

    emitted_sections.add(RUN_SUGGESTIONS_SECTION_ID)
    events.append(
        _stream_event(
            "partial",
            target="lesson_flow",
            section={"id": RUN_SUGGESTIONS_SECTION_ID, "value": note},
        )
    )
    return events


def _json_object_value_start_for_key(text: str, key: str) -> int | None:
    root_start = text.find("{")
    if root_start < 0:
        return None

    value_start = _json_value_start_for_key(text, key, root_start)
    if value_start is None or value_start >= len(text):
        return None
    if text[value_start] != "{":
        return None
    return value_start


def _completed_json_value_for_key(text: str, key: str, object_start: int) -> Any:
    value_start = _json_value_start_for_key(text, key, object_start)
    if value_start is None:
        return _JSON_MISSING

    try:
        value, _ = _JSON_DECODER.raw_decode(text, value_start)
    except json.JSONDecodeError:
        return _JSON_MISSING
    return value


def _json_value_start_for_key(text: str, key: str, object_start: int) -> int | None:
    if object_start >= len(text) or text[object_start] != "{":
        return None

    index = object_start + 1
    while index < len(text):
        index = _skip_json_ws(text, index)
        if index >= len(text) or text[index] == "}":
            return None
        if text[index] == ",":
            index += 1
            continue
        if text[index] != '"':
            return None

        try:
            current_key, key_end = _JSON_DECODER.raw_decode(text, index)
        except json.JSONDecodeError:
            return None
        if not isinstance(current_key, str):
            return None

        index = _skip_json_ws(text, key_end)
        if index >= len(text) or text[index] != ":":
            return None
        value_start = _skip_json_ws(text, index + 1)
        if current_key == key:
            return value_start

        try:
            _, value_end = _JSON_DECODER.raw_decode(text, value_start)
        except json.JSONDecodeError:
            return None
        index = value_end

    return None


def _skip_json_ws(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _stream_event(event_type: str, **payload: Any) -> str:
    return json.dumps({"type": event_type, **payload}, ensure_ascii=False) + "\n"


def _build_system_prompt(language: Language) -> str:
    language_rule = (
        "Use Traditional Chinese with Cantonese-friendly wording for every teacher-facing field."
        if language == "zh-Hant"
        else "Use clear, natural English for every teacher-facing field."
    )
    return (
        "You generate concise Python teaching material for Hong Kong teachers. "
        f"{language_rule} "
        "Return JSON only. Do not use markdown fences. Keep code beginner-safe "
        "and make master_code, starter_code, and buggy_code share the same structure."
    )


def _build_prompt(request: GeneratePackRequest) -> str:
    difficulty_rules = {
        "小學": "avoid class, lambda, recursion, list comprehension, and nested data structures",
        "初中": "allow variables, input, if/elif/else, loops, functions only when useful",
        "高中": "allow functions, lists, dictionaries, and simple decomposition",
    }[request.level]
    teaching_language = (
        "Traditional Chinese / Cantonese-friendly wording"
        if request.language == "zh-Hant"
        else "English"
    )
    level_label = _level_label(request.level, request.language)
    duration_label = _duration_label(request.duration, request.language)

    return f"""
Create one Python lesson debug pack as strict JSON with these top-level fields:
topic, level, duration, lesson_title, key_concepts, lesson_flow, run_suggestions,
master_code, starter_code, buggy_code, bug_cards, metadata.

Teacher input:
- topic: {request.topic}
- level: {level_label} (JSON value must remain exactly "{request.level}")
- duration: {duration_label} (JSON value must remain exactly "{request.duration}")
- language: {teaching_language}

Rules:
- Language for all teacher-facing text, including lesson_title, key_concepts,
  lesson_flow, bug_cards, run_suggestions.note, and any generated classroom
  wording: {teaching_language}.
- Keep the JSON level field exactly "{request.level}" and duration exactly
  "{request.duration}" so the response matches the API schema.
- Return the JSON fields in the order listed above. Keep run_suggestions
  immediately after lesson_flow so the Lesson Flow tab can stream every card,
  including Run Suggestions, before the longer code fields finish.
- Difficulty rule: {difficulty_rules}.
- Derive key_concepts from the topic and the generated code only; do not rely on user-selected concepts.
- master_code must be complete, clear, and runnable.
- starter_code must share the same structure and use # TODO comments.
- buggy_code must be based on master_code and contain 2 to 3 teachable Python mistakes.
- bug_cards must include 2 to 3 items. Each item needs id, title, error_type,
  teaching_concept, code_location, classroom_symptom, guiding_questions,
  progressive_hints, teacher_explanation, fix_summary, extension_activity,
  related_code_snippet, severity.
- Evidence-first bug-card principle: never claim that a correct or already
  present piece of code is wrong, missing, or undefined. A bug_card may only
  accuse a line, token, variable, function call, import, bracket, quote, colon,
  operator, or indentation if that exact wrong evidence appears in buggy_code.
- For every bug_card, self-check before returning JSON:
  1. related_code_snippet is copied exactly from buggy_code.
  2. code_location points to the same buggy line.
  3. classroom_symptom and fix_summary are not contradicted by buggy_code.
  4. If the card says something is missing, first verify it is not already
     present in buggy_code.
  5. If Python would report an error on a specific line/name, the card must
     describe that actual line/name, not a nearby correct line.
- Examples of forbidden false accusations:
  - If buggy_code has input(...), do not say input is missing parentheses.
  - If buggy_code has import random, do not say random was not imported.
  - If buggy_code has a variable already assigned before use, do not say that
    same variable is undefined; look for the actual misspelled or different
    name.
  - If buggy_code uses an if/elif/else chain, do not say two branches will run
    or that it should use elif; Python will run only the first matching branch
    in one if/elif/else chain.
  - If buggy_code has SyntaxError, do not label that same line as Logic Error
    or say the program runs without an error. SyntaxError stops execution before
    runtime or logic behaviour can be observed.
  - If buggy_code compiles successfully, do not include SyntaxError or
    IndentationError cards. Do not invent missing quotes, brackets, colons, or
    indentation errors on code that Python can parse.
  - If buggy_code contains both a SyntaxError and later runtime/logic bugs
    such as NameError, TypeError, AttributeError, ValueError, or Logic Error,
    runtime bug cards must say they are observed after fixing the SyntaxError
    first. Do not imply the runtime error appears before the SyntaxError is fixed.
  - If buggy_code has a colon, quote, bracket, or indentation already correct
    on that line, do not name that as the bug.
- Python 3 type rule: input() returns str. Comparing that str with an int or
  float using >, <, >=, or <= raises TypeError. Do not describe it as a Logic
  Error that simply becomes False. Equality == may be False, but ordering
  comparisons between str and number are TypeError.
- If buggy_code already converts an input variable with int(...) or float(...)
  before comparison, do not write a card saying the input was not converted.
  Look for another real bug.
- Never include a card that says "this bug does not exist", "ignore this card",
  or similar. Replace it with a real bug from buggy_code or omit it.
- Import-specific examples: If buggy_code has "import random as r" but uses
  "random", explain the alias mismatch. If it has "from random import randint"
  but uses "random.randint", explain that from-import does not create the module
  name "random".
- lesson_flow needs warm_up, build_activity, debug_activity, wrap_up, teacher_notes.
- Every lesson_flow field must be tightly grounded in this exact topic and code. Mention concrete program details such as variable names, TODO steps, sample input/output, or the exact bug/error type.
- Lesson flow cards must be easy to scan. Write each lesson_flow card as
  exactly three short numbered steps in this exact visual style:
  1. XXXXXX
  2. YYYYYY
  3. ZZZZZZ
- For list fields such as build_activity, debug_activity, and teacher_notes,
  each array item is one numbered step's text only. Do not put "1.", "2.",
  "first", "second", semicolon chains, or nested lists inside an array item.
- For string fields such as warm_up, wrap_up, and run_suggestions.note, use
  three separate numbered lines. Do not return a paragraph.
- Do not write generic extension ideas or vague classroom filler. Avoid lines like "加入更多功能", "提供額外延伸", or any activity that could fit any Python lesson.
- teacher_notes must be actionable for teaching this generated program, including which line/variable/error to focus on.
- run_suggestions needs master_input, buggy_input, note.
- metadata can be an empty object; the server will fill it.
""".strip()


def _extract_json(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        repaired = _repair_missing_field_commas(cleaned)
        if repaired != cleaned:
            try:
                LOGGER.info("Repaired missing JSON field comma after model output parse error: %s", exc)
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
        raise


def _repair_missing_field_commas(content: str) -> str:
    return MISSING_FIELD_COMMA_RE.sub(r"\1,\n\2", content)


def _normalize_lesson_pack_data(data: dict[str, Any], language: Language = "zh-Hant") -> dict[str, Any]:
    normalized = dict(data)

    normalized["key_concepts"] = _as_list(normalized.get("key_concepts"))
    normalized["master_code"] = _as_string(normalized.get("master_code"))
    normalized["starter_code"] = _as_string(normalized.get("starter_code"))
    normalized["buggy_code"] = _as_string(normalized.get("buggy_code"))

    flow = dict(normalized.get("lesson_flow") or {})
    flow["warm_up"] = _as_string(flow.get("warm_up"))
    flow["build_activity"] = _as_list(flow.get("build_activity"))
    flow["debug_activity"] = _as_list(flow.get("debug_activity"))
    flow["wrap_up"] = _as_string(flow.get("wrap_up"))
    flow["teacher_notes"] = _as_list(flow.get("teacher_notes"))
    normalized["lesson_flow"] = flow

    run_suggestions = dict(normalized.get("run_suggestions") or {})
    run_suggestions["master_input"] = _as_string(run_suggestions.get("master_input"))
    run_suggestions["buggy_input"] = _as_string(run_suggestions.get("buggy_input"))
    run_suggestions["note"] = _as_string(run_suggestions.get("note"))
    normalized["run_suggestions"] = run_suggestions

    cards: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(normalized.get("bug_cards")), start=1):
        if not isinstance(item, dict):
            continue

        card = dict(item)
        card["id"] = _as_string(card.get("id") or f"bug-{index}")
        for field in (
            "title",
            "error_type",
            "teaching_concept",
            "code_location",
            "classroom_symptom",
            "teacher_explanation",
            "fix_summary",
            "extension_activity",
            "related_code_snippet",
        ):
            card[field] = _as_string(card.get(field))
        card["guiding_questions"] = _as_list(card.get("guiding_questions"))
        card["progressive_hints"] = _as_list(card.get("progressive_hints"))
        if card.get("severity") not in {"beginner", "intermediate", "advanced"}:
            card["severity"] = "beginner"
        cards.append(card)

    normalized["bug_cards"] = cards
    return _repair_bug_cards_for_code(normalized, language)


def _repair_bug_cards_for_code(normalized: dict[str, Any], language: Language = "zh-Hant") -> dict[str, Any]:
    buggy_code = normalized.get("buggy_code", "")
    diagnostic = _compile_diagnostic(buggy_code)
    if not diagnostic or diagnostic["error_type"] != "SyntaxError":
        return _repair_semantic_false_accusations(
            _repair_name_error_cards_for_code(
                _drop_false_syntax_cards_when_code_compiles(normalized), buggy_code, language
            ),
            buggy_code,
            language,
        )

    replacement = _syntax_card_from_diagnostic(diagnostic, language)
    if not replacement:
        return _repair_semantic_false_accusations(
            _repair_name_error_cards_for_code(normalized, buggy_code, language), buggy_code, language
        )

    cards = list(normalized.get("bug_cards") or [])
    cards, dropped_false_name_card = _drop_false_name_error_cards_from_text(cards, buggy_code)
    if dropped_false_name_card:
        normalized["bug_cards"] = cards[:3]

    cards, replaced_false_syntax_card = _replace_false_syntax_cards(cards, diagnostic, replacement)
    cards, qualified_runtime_cards = _qualify_runtime_cards_after_syntax_error(cards, language)
    if replaced_false_syntax_card:
        normalized["bug_cards"] = cards[:3]
    if qualified_runtime_cards:
        normalized["bug_cards"] = cards[:3]

    if _cards_cover_diagnostic(cards, diagnostic):
        return _repair_semantic_false_accusations(
            _repair_name_error_cards_for_code(normalized, buggy_code, language), buggy_code, language
        )

    for index, card in enumerate(cards):
        if _is_syntax_card(card):
            replacement["id"] = _as_string(card.get("id")) or replacement["id"]
            cards[index] = replacement
            normalized["bug_cards"] = cards[:3]
            return _repair_semantic_false_accusations(
                _repair_name_error_cards_for_code(normalized, buggy_code, language), buggy_code, language
            )

    normalized["bug_cards"] = [replacement, *cards][:3]
    return _repair_semantic_false_accusations(
        _repair_name_error_cards_for_code(normalized, buggy_code, language), buggy_code, language
    )


def _drop_false_name_error_cards_from_text(
    cards: list[dict[str, Any]], code: str
) -> tuple[list[dict[str, Any]], bool]:
    changed = False
    kept: list[dict[str, Any]] = []
    for card in cards:
        if _card_falsely_accuses_defined_name_from_text(card, code):
            changed = True
            continue
        kept.append(card)
    return kept, changed


def _drop_false_syntax_cards_when_code_compiles(normalized: dict[str, Any]) -> dict[str, Any]:
    cards = list(normalized.get("bug_cards") or [])
    filtered = [card for card in cards if not _is_syntax_card(card)]
    if len(filtered) != len(cards):
        normalized = dict(normalized)
        normalized["bug_cards"] = filtered[:3]
    return normalized


def _card_falsely_accuses_defined_name_from_text(card: dict[str, Any], code: str) -> bool:
    if not _is_name_error_card(card):
        return False

    name = _name_error_card_name(card)
    if not name:
        return False

    snippet = _as_string(card.get("related_code_snippet")).strip()
    if snippet and _line_binds_name_without_self_reference(snippet, name):
        return True

    binding_lines = _binding_line_numbers_for_name(code, name)
    if not binding_lines:
        return False

    accused_line = _card_accused_line_number(card, code)
    if accused_line <= 0:
        return False

    return any(line_no < accused_line for line_no in binding_lines)


def _line_binds_name_without_self_reference(line: str, name: str) -> bool:
    match = re.match(rf"^\s*{re.escape(name)}\s*=", line)
    if not match:
        return False
    rhs = line[match.end() :]
    return not re.search(rf"\b{re.escape(name)}\b", rhs)


def _binding_line_numbers_for_name(code: str, name: str) -> list[int]:
    binding_lines: list[int] = []
    for index, line in enumerate(code.splitlines(), start=1):
        stripped = line.strip()
        if re.match(rf"import\s+{re.escape(name)}\b", stripped):
            binding_lines.append(index)
        elif re.match(rf"from\s+\S+\s+import\s+.*\b{re.escape(name)}\b", stripped):
            binding_lines.append(index)
        elif re.match(rf"(def|class)\s+{re.escape(name)}\b", stripped):
            binding_lines.append(index)
        elif _line_binds_name_without_self_reference(stripped, name):
            binding_lines.append(index)
    return binding_lines


def _card_accused_line_number(card: dict[str, Any], code: str) -> int:
    for field in ("code_location", "classroom_symptom", "title"):
        match = re.search(r"(?:第|line\s*)(\d+)", _as_string(card.get(field)), re.IGNORECASE)
        if match:
            return int(match.group(1))

    snippet = _as_string(card.get("related_code_snippet")).strip()
    if not snippet:
        return 0
    for index, line in enumerate(code.splitlines(), start=1):
        if line.strip() == snippet:
            return index
    return 0


def _replace_false_syntax_cards(
    cards: list[dict[str, Any]], diagnostic: dict[str, Any], replacement: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    changed = False
    repaired: list[dict[str, Any]] = []
    for card in cards:
        if _card_contradicts_syntax_diagnostic(card, diagnostic):
            fixed = dict(replacement)
            fixed["id"] = _as_string(card.get("id")) or fixed["id"]
            repaired.append(fixed)
            changed = True
        else:
            repaired.append(card)
    return repaired, changed


def _card_contradicts_syntax_diagnostic(card: dict[str, Any], diagnostic: dict[str, Any]) -> bool:
    text = _card_text(card).lower()
    if _is_syntax_card(card):
        return False

    if diagnostic.get("error_type") != "SyntaxError":
        return False

    if _syntax_issue_kind(diagnostic) == "single_equals_condition" and _card_matches_single_equals_condition(card):
        return True

    return any(
        term in text
        for term in (
            "logic error",
            "邏輯錯誤",
            "冇報錯",
            "沒有報錯",
            "no error",
            "can run",
            "可以執行",
            "程式可以執行",
        )
    )


def _qualify_runtime_cards_after_syntax_error(
    cards: list[dict[str, Any]], language: Language = "zh-Hant"
) -> tuple[list[dict[str, Any]], bool]:
    changed = False
    qualified: list[dict[str, Any]] = []
    seen_primary_syntax = False
    for card in cards:
        if _is_syntax_card(card):
            if not seen_primary_syntax:
                seen_primary_syntax = True
                qualified.append(card)
                continue

            text = _card_text(card)
            if "修正 SyntaxError 後" in text or "修正語法錯誤後" in text:
                qualified.append(card)
                continue

            fixed = dict(card)
            symptom = _as_string(fixed.get("classroom_symptom"))
            explanation = _as_string(fixed.get("teacher_explanation"))
            if symptom:
                prefix = "After fixing the SyntaxError, " if language == "en" else "修正 SyntaxError 後，"
                fixed["classroom_symptom"] = f"{prefix}{symptom}"
                changed = True
            if explanation and "SyntaxError" not in explanation:
                fixed["teacher_explanation"] = (
                    "The same buggy code still has an earlier SyntaxError, so demonstrate this card only after fixing the first syntax error. "
                    if language == "en"
                    else "同一份 buggy code 仍有更早的 SyntaxError，這張卡要在前一個語法錯誤修正後才示範。"
                ) + f"{explanation}"
                changed = True
            qualified.append(fixed)
            continue

            qualified.append(card)
            continue

        error_type = _as_string(card.get("error_type")).lower()
        is_runtime_or_logic = (
            error_type.endswith("error")
            and not any(term in error_type for term in ("syntaxerror", "indentationerror"))
        ) or "logic" in error_type
        if not is_runtime_or_logic:
            qualified.append(card)
            continue

        text = _card_text(card)
        if "SyntaxError" in text or "語法" in text and "修正" in text:
            qualified.append(card)
            continue

        fixed = dict(card)
        symptom = _as_string(fixed.get("classroom_symptom"))
        explanation = _as_string(fixed.get("teacher_explanation"))
        if symptom and not symptom.startswith(("修正語法錯誤後", "After fixing the syntax error")):
            prefix = "After fixing the syntax error, " if language == "en" else "修正語法錯誤後，"
            fixed["classroom_symptom"] = f"{prefix}{symptom}"
            changed = True
        if explanation and "SyntaxError" not in explanation:
            fixed["teacher_explanation"] = (
                "Because the same buggy code still has a SyntaxError, demonstrate this card only after fixing the syntax error. "
                if language == "en"
                else "由於同一份 buggy code 仍有 SyntaxError，這張卡要在語法錯誤修正後才示範。"
            ) + f"{explanation}"
            changed = True
        qualified.append(fixed)
    return qualified, changed


def _compile_diagnostic(code: str) -> dict[str, Any] | None:
    try:
        compile(code, "<buggy_code>", "exec")
    except SyntaxError as exc:
        line_no = exc.lineno or 0
        lines = code.splitlines()
        line = lines[line_no - 1] if 0 < line_no <= len(lines) else (exc.text or "")
        return {
            "error_type": exc.__class__.__name__,
            "message": exc.msg,
            "line_no": line_no,
            "line": line.rstrip(),
        }
    return None


def _cards_cover_diagnostic(cards: list[dict[str, Any]], diagnostic: dict[str, Any]) -> bool:
    actual_line = _as_string(diagnostic.get("line")).strip()
    if not actual_line:
        return False

    issue_kind = _syntax_issue_kind(diagnostic)
    for card in cards:
        if not _is_syntax_card(card):
            continue
        snippet = _as_string(card.get("related_code_snippet")).strip()
        if snippet and (snippet in actual_line or actual_line in snippet):
            if issue_kind == "single_equals_condition":
                return _card_matches_single_equals_condition(card)
            return True
    return False


def _is_syntax_card(card: dict[str, Any]) -> bool:
    text = " ".join(
        _as_string(card.get(field))
        for field in ("error_type", "title", "teaching_concept", "classroom_symptom", "fix_summary")
    ).lower()
    return "syntaxerror" in text or "syntax error" in text or "語法" in text or "文法" in text


def _syntax_card_from_diagnostic(
    diagnostic: dict[str, Any], language: Language = "zh-Hant"
) -> dict[str, Any] | None:
    line = _as_string(diagnostic.get("line")).strip()
    line_no = int(diagnostic.get("line_no") or 0)
    if not line:
        return None

    if _syntax_issue_kind(diagnostic) == "single_equals_condition":
        if language == "en":
            return {
                "id": f"bug-syntax-line-{line_no}",
                "title": "A condition uses a single equals sign",
                "error_type": "SyntaxError",
                "teaching_concept": "Conditions use == for comparison; a single = assigns a value.",
                "code_location": f"line {line_no}: {line}",
                "classroom_symptom": "The program shows SyntaxError: invalid syntax before it starts running.",
                "guiding_questions": [
                    f"On line {line_no}, are we trying to compare values or change a variable?",
                    "What is the difference between = and == in Python?",
                ],
                "progressive_hints": [
                    "First count how many equals signs are inside the condition.",
                    "Comparisons after if / elif / while usually need ==.",
                ],
                "teacher_explanation": (
                    "When Python sees a single = after if or elif, it treats it as assignment, but that position needs an expression that can be True or False."
                ),
                "fix_summary": f"Change the = in the line {line_no} condition to ==.",
                "extension_activity": "Ask students to inspect other if / elif conditions and mark which equals signs assign values and which compare values.",
                "related_code_snippet": line,
                "severity": "beginner",
            }
        return {
            "id": f"bug-syntax-line-{line_no}",
            "title": "比較條件用了單一等號",
            "error_type": "SyntaxError",
            "teaching_concept": "條件判斷要用 == 比較，單一 = 只用來指派變數",
            "code_location": f"第{line_no}行：{line}",
            "classroom_symptom": "程式未開始執行就顯示 SyntaxError: invalid syntax。",
            "guiding_questions": [
                f"第{line_no}行想做比較，定係想改變變數值？",
                "Python 入面 = 同 == 分別係咩？",
            ],
            "progressive_hints": [
                "先望一望條件入面用了幾多個等號。",
                "if / elif / while 後面的比較通常要用 ==。",
            ],
            "teacher_explanation": (
                "Python 見到 if 或 elif 後面用單一 = 會當成指派，但條件位置需要一個可以判斷 True / False 的比較式。"
            ),
            "fix_summary": f"將第{line_no}行條件中的 = 改成 ==。",
            "extension_activity": "請學生檢查其他 if / elif 條件，圈出哪些位置是指派，哪些位置是比較。",
            "related_code_snippet": line,
            "severity": "beginner",
        }

    if language == "en":
        return {
            "id": f"bug-syntax-line-{line_no}",
            "title": "Start by matching the actual syntax error line",
            "error_type": "SyntaxError",
            "teaching_concept": "Use Python's reported line number to inspect the syntax structure first.",
            "code_location": f"line {line_no}: {line}",
            "classroom_symptom": f"The program shows SyntaxError: {diagnostic.get('message', 'invalid syntax')} before it starts running.",
            "guiding_questions": [
                f"Does Python's line {line_no} match the line described by the card?",
                "Are the brackets, quotes, colons, or comparison symbols complete on this line?",
            ],
            "progressive_hints": [
                "Do not guess the cause first; align with the line mentioned in the traceback.",
                "Check brackets, quotes, colons, and operators one at a time.",
            ],
            "teacher_explanation": "SyntaxError means Python cannot read the program structure. In teaching, first follow the traceback to the actual failing line, then discuss the fix.",
            "fix_summary": f"Use the SyntaxError message to repair the syntax on line {line_no}.",
            "extension_activity": "Ask students to compare the incorrect line with the fixed line and name the exact symbol that changed.",
            "related_code_snippet": line,
            "severity": "beginner",
        }

    return {
        "id": f"bug-syntax-line-{line_no}",
        "title": "語法錯誤位置要先對準",
        "error_type": "SyntaxError",
        "teaching_concept": "先根據 Python 指出的行數檢查語法結構",
        "code_location": f"第{line_no}行：{line}",
        "classroom_symptom": f"程式未開始執行就顯示 SyntaxError: {diagnostic.get('message', 'invalid syntax')}。",
        "guiding_questions": [
            f"Python 指出的第{line_no}行同卡片描述是否同一行？",
            "這一行的括號、引號、冒號或比較符號是否完整？",
        ],
        "progressive_hints": [
            "先不要猜錯誤原因，先對準 traceback 提到的行。",
            "逐個檢查括號、引號、冒號和運算符號。",
        ],
        "teacher_explanation": "SyntaxError 代表 Python 連程式結構都讀不到，教學時應先跟 traceback 定位實際出錯行，再討論修法。",
        "fix_summary": f"根據 SyntaxError 訊息修正第{line_no}行的語法。",
        "extension_activity": "請學生把錯誤行和修正後一行並排比較，說出改動了哪一個符號。",
        "related_code_snippet": line,
        "severity": "beginner",
    }


def _has_single_equals_in_condition(line: str) -> bool:
    stripped = line.strip()
    if not re.match(r"^(if|elif|while)\b", stripped):
        return False
    if ":=" in stripped:
        return False
    return bool(re.search(r"(?<![<>=!])=(?!=)", stripped))


def _syntax_issue_kind(diagnostic: dict[str, Any]) -> str:
    if _has_single_equals_in_condition(_as_string(diagnostic.get("line"))):
        return "single_equals_condition"
    return "generic"


def _card_matches_single_equals_condition(card: dict[str, Any]) -> bool:
    text = " ".join(
        _as_string(card.get(field))
        for field in (
            "title",
            "teaching_concept",
            "classroom_symptom",
            "teacher_explanation",
            "fix_summary",
        )
    ).lower()
    if any(term in text for term in ("括號", "bracket", "parentheses")):
        return False
    return any(term in text for term in ("==", "等號", "比較", "指派", "comparison", "assignment", "equal"))


def _repair_name_error_cards_for_code(
    normalized: dict[str, Any], code: str, language: Language = "zh-Hant"
) -> dict[str, Any]:
    analysis = _python_name_analysis(code)
    if not analysis:
        return normalized

    cards = list(normalized.get("bug_cards") or [])
    changed = False
    for index, card in enumerate(cards):
        if not _is_name_error_card(card):
            continue

        mentioned_name = _name_error_card_name(card)
        if not _name_error_card_needs_repair(card, analysis, mentioned_name):
            continue

        replacement = _name_error_card_from_analysis(analysis, mentioned_name, language)
        if not replacement:
            continue

        replacement["id"] = _as_string(card.get("id")) or replacement["id"]
        cards[index] = replacement
        changed = True

    if changed:
        normalized["bug_cards"] = cards[:3]
    return normalized


def _is_name_error_card(card: dict[str, Any]) -> bool:
    return "nameerror" in _card_text(card).lower()


def _is_name_error_import_card(card: dict[str, Any]) -> bool:
    text = _card_text(card).lower()
    if "nameerror" not in text:
        return False
    return "import" in text or "模組" in text or "模块" in text or "引入" in text


def _card_text(card: dict[str, Any]) -> str:
    return " ".join(
        _as_string(card.get(field))
        for field in (
            "error_type",
            "title",
            "teaching_concept",
            "classroom_symptom",
            "guiding_questions",
            "progressive_hints",
            "teacher_explanation",
            "fix_summary",
            "related_code_snippet",
        )
    )


def _name_error_card_name(card: dict[str, Any]) -> str:
    text = " ".join(_as_string(value) for value in card.values())
    match = re.search(r"name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] is not defined", text)
    if match:
        return match.group(1)

    match = re.search(r"\bimport\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    if match:
        return match.group(1)

    return ""


def _name_error_card_needs_repair(card: dict[str, Any], analysis: dict[str, Any], mentioned_name: str) -> bool:
    problems: list[dict[str, Any]] = analysis["problems"]
    if not problems:
        return False

    if not mentioned_name:
        return False

    if _is_name_error_import_card(card):
        exact_missing_import = (
            any(problem["name"] == mentioned_name and problem["kind"] == "undefined" for problem in problems)
            and mentioned_name not in analysis["binds"]
            and not analysis["imports"]
        )
        return not exact_missing_import

    if any(problem["name"] == mentioned_name for problem in problems):
        return False

    if mentioned_name in analysis["binds"]:
        return True

    return bool(_closest_bound_name(mentioned_name, analysis["binds"]))


def _name_error_card_from_analysis(
    analysis: dict[str, Any], mentioned_name: str, language: Language = "zh-Hant"
) -> dict[str, Any] | None:
    problem = _select_name_problem(analysis, mentioned_name)
    if not problem:
        return None

    name = problem["name"]
    line_no = int(problem.get("line_no") or 0)
    line = _as_string(problem.get("line")).strip()
    import_record = _import_record_for_problem(analysis, name)

    if problem["kind"] == "used_before_bind" and import_record:
        if language == "en":
            return {
                "id": f"bug-name-{name}",
                "title": f"{name} is used before its import runs",
                "error_type": "NameError",
                "teaching_concept": "Place imports before the first use of the module.",
                "code_location": f"line {line_no}: {line}",
                "classroom_symptom": f"Line {line_no} raises NameError because Python has not executed the import yet.",
                "guiding_questions": [
                    f"Which line first uses {name}?",
                    f"Does import {name} happen before or after that use?",
                ],
                "progressive_hints": [
                    "Python executes from top to bottom; an import on a later line has not happened yet.",
                    "Move the import to the top of the file or before the first use.",
                ],
                "teacher_explanation": "Having an import somewhere in the program does not mean it has already run. If the name is used before the import line, Python still sees it as undefined.",
                "fix_summary": f"Move import {name} before line {line_no}, usually near the top of the program.",
                "extension_activity": "Ask students to mark the execution order and circle the first module use and the import line.",
                "related_code_snippet": line,
                "severity": "beginner",
            }
        return {
            "id": f"bug-name-{name}",
            "title": f"{name} 在 import 前已被使用",
            "error_type": "NameError",
            "teaching_concept": "import 要放在第一次使用模組之前",
            "code_location": f"第{line_no}行：{line}",
            "classroom_symptom": f"執行到第{line_no}行時出現 NameError，因為 Python 當時仍未執行 import。",
            "guiding_questions": [
                f"程式第一次使用 {name} 是第幾行？",
                f"import {name} 又是在使用之前，還是之後？",
            ],
            "progressive_hints": [
                "Python 由上至下執行，未行到的 import 不會先自動生效。",
                "把 import 行移到檔案最上方或第一次使用之前。",
            ],
            "teacher_explanation": "程式有 import 不代表當刻已經執行了 import；如果先使用模組名稱，Python 仍會視它為未定義。",
            "fix_summary": f"將 import {name} 移到第{line_no}行之前，通常放在程式最上方。",
            "extension_activity": "請學生標出程式執行順序，圈出第一次使用模組和 import 行的位置。",
            "related_code_snippet": line,
            "severity": "beginner",
        }

    if import_record and import_record.get("source") == name and import_record.get("bound") != name:
        bound_name = _as_string(import_record.get("bound"))
        import_line = _as_string(import_record.get("line"))
        if import_record.get("kind") == "import":
            if language == "en":
                fix = f"Use the alias {bound_name}, for example change {name}.xxx to {bound_name}.xxx; or change the import back to import {name}."
                concept = "After importing with an alias, call the module using the alias name."
            else:
                fix = f"使用別名 {bound_name}，例如把 {name}.xxx 改成 {bound_name}.xxx；或者改回 import {name}。"
                concept = "import alias 後，要用 alias 名稱呼叫模組"
        else:
            if language == "en":
                fix = f"If the code uses {import_line}, call the imported name directly; if you want {name}.xxx, use import {name} instead."
                concept = "from-import imports only the named object; it does not create the module name itself."
            else:
                fix = f"如果用了 {import_line}，就直接呼叫已引入的名稱；如果想寫 {name}.xxx，就改用 import {name}。"
                concept = "from-import 只引入指定名稱，不會建立模組名稱本身"

        if language == "en":
            return {
                "id": f"bug-name-{name}",
                "title": f"{name} import style does not match how it is used",
                "error_type": "NameError",
                "teaching_concept": concept,
                "code_location": f"line {line_no}: {line}",
                "classroom_symptom": f"The program has an import, but line {line_no} still says name '{name}' is not defined.",
                "guiding_questions": [
                    f"Which name did the import actually create: {name} or {bound_name}?",
                    f"Does the name on line {line_no} match the name created by the import?",
                ],
                "progressive_hints": [
                    "Check whether the import line uses an alias or from ... import ....",
                    "Python only recognizes the exact name that the import placed in the namespace.",
                ],
                "teacher_explanation": "The issue is not a total lack of import; the import syntax created a different usable name from the one used later.",
                "fix_summary": fix,
                "extension_activity": "Ask students to try import random, import random as r, and from random import randint, then list which names are available.",
                "related_code_snippet": line,
                "severity": "beginner",
            }

        return {
            "id": f"bug-name-{name}",
            "title": f"{name} 的 import 寫法和使用方式不一致",
            "error_type": "NameError",
            "teaching_concept": concept,
            "code_location": f"第{line_no}行：{line}",
            "classroom_symptom": f"程式已有 import，但執行到第{line_no}行仍顯示 name '{name}' is not defined。",
            "guiding_questions": [
                f"import 行實際建立了哪個名稱：{name} 還是 {bound_name}？",
                f"第{line_no}行使用的名稱和 import 建立的名稱是否一樣？",
            ],
            "progressive_hints": [
                "先看 import 行有沒有 as alias，或者是否用了 from ... import ...。",
                "Python 只認得 import 實際放到程式命名空間的名稱。",
            ],
            "teacher_explanation": "問題不是完全沒有 import，而是 import 寫法建立的名稱和後面使用的名稱不同。",
            "fix_summary": fix,
            "extension_activity": "請學生分別試寫 import random、import random as r、from random import randint，觀察可用名稱有何不同。",
            "related_code_snippet": line,
            "severity": "beginner",
        }

    if problem["kind"] == "undefined" and analysis["imports"]:
        imported_names = ", ".join(sorted(record["bound"] for record in analysis["imports"] if record.get("bound")))
        if language == "en":
            return {
                "id": f"bug-name-{name}",
                "title": f"{name} is undefined; first check the names made available by imports",
                "error_type": "NameError",
                "teaching_concept": "Imported names and called names must match.",
                "code_location": f"line {line_no}: {line}",
                "classroom_symptom": f"The program has imports, but line {line_no} uses a name Python does not know: {name}.",
                "guiding_questions": [
                    f"Which names did the import lines create? Current imported names: {imported_names}",
                    f"Does {name} on line {line_no} appear in an import or assignment?",
                ],
                "progressive_hints": [
                    "Do not only check whether an import exists; check the exact name it makes available.",
                    "Look for a missing module prefix, a misspelling, or a function name that was never imported.",
                ],
                "teacher_explanation": "NameError means the current namespace does not contain this name. Even with imports, the imported name may not be this exact one.",
                "fix_summary": f"Change {name} on line {line_no} to the correct imported name, or add the import that actually creates it.",
                "extension_activity": "Ask students to list the usable names created by each import line, then compare them with the failing line.",
                "related_code_snippet": line,
                "severity": "beginner",
            }
        return {
            "id": f"bug-name-{name}",
            "title": f"{name} 未定義，先核對 import 後可用的名稱",
            "error_type": "NameError",
            "teaching_concept": "已 import 的名稱和實際呼叫的名稱要一致",
            "code_location": f"第{line_no}行：{line}",
            "classroom_symptom": f"程式已有 import，但第{line_no}行使用了 Python 不認得的名稱 {name}。",
            "guiding_questions": [
                f"import 行建立了哪些名稱？目前見到：{imported_names}",
                f"第{line_no}行用的 {name} 是否在 import 或變數指派中出現過？",
            ],
            "progressive_hints": [
                "不要只看有沒有 import，要看 import 後可直接使用的名稱。",
                "檢查是否少了模組前綴、寫錯拼字，或用了未引入的函數名稱。",
            ],
            "teacher_explanation": "NameError 的核心是目前命名空間沒有這個名稱；即使程式有 import，也可能不是引入了這個名稱。",
            "fix_summary": f"把第{line_no}行的 {name} 改成已 import 的正確名稱，或補回真正需要的 import。",
            "extension_activity": "請學生列出每一行 import 後新增了哪些可用名稱，再對照出錯行。",
            "related_code_snippet": line,
            "severity": "beginner",
        }

    if problem["kind"] == "undefined":
        candidate = _closest_bound_name(name, analysis["binds"])
        if candidate:
            if language == "en":
                fix_summary = f"Change {name} on line {line_no} to the already-created name {candidate}, or correctly create {name} before using it."
                first_hint = f"Is there a very similar name nearby, such as {candidate}?"
            else:
                fix_summary = f"將第{line_no}行的 {name} 改成已建立的名稱 {candidate}，或在使用前正確建立 {name}。"
                first_hint = f"附近有沒有一個很相似的名稱，例如 {candidate}？"
        else:
            if language == "en":
                fix_summary = f"Before using {name} on line {line_no}, create that variable/function or change it to an existing correct name."
                first_hint = "Look upward: was this name assigned, defined, or imported earlier?"
            else:
                fix_summary = f"在第{line_no}行使用 {name} 前，先建立這個變數/函數，或改成已存在的正確名稱。"
                first_hint = "向上找一找，這個名稱之前有沒有被指派、定義或 import。"

        if language == "en":
            return {
                "id": f"bug-name-{name}",
                "title": f"{name} is undefined; check the exact name first",
                "error_type": "NameError",
                "teaching_concept": "A name must exactly match a variable, function, or import created earlier.",
                "code_location": f"line {line_no}: {line}",
                "classroom_symptom": f"Line {line_no} raises NameError: name '{name}' is not defined.",
                "guiding_questions": [
                    f"Python says {name} is undefined. Is there an exactly matching name earlier?",
                    "Does the card's name match the actual name in the error message?",
                ],
                "progressive_hints": [
                    first_hint,
                    "For NameError, read the exact name inside the error message before guessing the cause.",
                ],
                "teacher_explanation": "The evidence for NameError is the name shown in the error message. If a different name already exists correctly, do not accuse that correct name.",
                "fix_summary": fix_summary,
                "extension_activity": "Ask students to circle the name in the error message, then mark whether the exact same name appears earlier in the program.",
                "related_code_snippet": line,
                "severity": "beginner",
            }

        return {
            "id": f"bug-name-{name}",
            "title": f"{name} 未定義，先核對真正的名稱",
            "error_type": "NameError",
            "teaching_concept": "名稱必須和前面建立的變數、函數或 import 完全一致",
            "code_location": f"第{line_no}行：{line}",
            "classroom_symptom": f"執行到第{line_no}行時出現 NameError: name '{name}' is not defined。",
            "guiding_questions": [
                f"Python 說未定義的是 {name}，程式前面有沒有完全一樣的名稱？",
                "卡片提到的名稱是否真的和錯誤訊息一致？",
            ],
            "progressive_hints": [
                first_hint,
                "NameError 要先讀錯誤訊息入面的實際名稱，不要先猜原因。",
            ],
            "teacher_explanation": "NameError 的證據是錯誤訊息指出的名稱；如果另一個名稱已經正確存在，就不應把那個正確名稱當成錯。",
            "fix_summary": fix_summary,
            "extension_activity": "請學生圈出錯誤訊息中的名稱，再用同一顏色標出程式前面是否有完全相同的名稱。",
            "related_code_snippet": line,
            "severity": "beginner",
        }

    return None


def _select_name_problem(analysis: dict[str, Any], mentioned_name: str) -> dict[str, Any] | None:
    problems: list[dict[str, Any]] = analysis["problems"]
    if mentioned_name:
        for problem in problems:
            if problem["name"] == mentioned_name:
                return problem

        import_record = _import_record_for_problem(analysis, mentioned_name)
        if import_record and import_record.get("bound") != mentioned_name:
            load = analysis["loads"].get(mentioned_name)
            if load:
                return {
                    "name": mentioned_name,
                    "kind": "undefined",
                    "line_no": load["line_no"],
                    "line": load["line"],
                }

    return problems[0] if problems else None


def _import_record_for_problem(analysis: dict[str, Any], name: str) -> dict[str, Any] | None:
    for record in analysis["imports"]:
        if record.get("source") == name or record.get("bound") == name:
            return record
    return None


def _closest_bound_name(name: str, binds: dict[str, dict[str, Any]]) -> str:
    matches = difflib.get_close_matches(name, binds.keys(), n=1, cutoff=0.72)
    return matches[0] if matches else ""


def _repair_semantic_false_accusations(
    normalized: dict[str, Any], code: str, language: Language = "zh-Hant"
) -> dict[str, Any]:
    normalized = _repair_input_order_comparison_cards(normalized, code, language)
    normalized = _drop_nonexistent_bug_cards(normalized)
    normalized = _drop_false_input_conversion_cards(normalized, code)
    normalized = _drop_false_name_error_cards(normalized, code)
    normalized = _drop_meta_reasoning_cards(normalized)
    cards = list(normalized.get("bug_cards") or [])
    changed = False
    for index, card in enumerate(cards):
        if not _card_falsely_accuses_if_elif(card, code):
            continue
        replacement = _else_branch_card_from_code(code, language)
        if not replacement:
            continue
        replacement["id"] = _as_string(card.get("id")) or replacement["id"]
        cards[index] = replacement
        changed = True

    if changed:
        normalized["bug_cards"] = cards[:3]
    return normalized


def _drop_nonexistent_bug_cards(normalized: dict[str, Any]) -> dict[str, Any]:
    cards = list(normalized.get("bug_cards") or [])
    filtered = [
        card
        for card in cards
        if not any(term in _card_text(card).lower() for term in ("bug 唔存在", "請忽略", "does not exist", "ignore this"))
    ]
    if len(filtered) != len(cards):
        normalized["bug_cards"] = filtered[:3]
    return normalized


def _drop_meta_reasoning_cards(normalized: dict[str, Any]) -> dict[str, Any]:
    cards = list(normalized.get("bug_cards") or [])
    meta_terms = (
        "original buggy_code",
        "given buggy_code",
        "i will",
        "i must",
        "原 buggy_code",
        "給定的 buggy_code",
        "我將",
        "我必須",
        "為符合",
        "不能改",
        "此卡不適用",
        "不適用",
        "需要再引入",
    )
    filtered = [card for card in cards if not any(term in _card_text(card).lower() for term in meta_terms)]
    if len(filtered) != len(cards):
        normalized["bug_cards"] = filtered[:3]
    return normalized


def _drop_false_name_error_cards(normalized: dict[str, Any], code: str) -> dict[str, Any]:
    analysis = _python_name_analysis(code)
    if not analysis:
        return normalized

    problem_names = {problem["name"] for problem in analysis["problems"]}
    cards = list(normalized.get("bug_cards") or [])
    filtered: list[dict[str, Any]] = []
    changed = False
    for card in cards:
        if not _is_name_error_card(card):
            filtered.append(card)
            continue

        mentioned_name = _name_error_card_name(card)
        if mentioned_name and mentioned_name in analysis["binds"] and mentioned_name not in problem_names:
            changed = True
            continue

        filtered.append(card)

    if changed:
        normalized["bug_cards"] = filtered[:3]
    return normalized


def _drop_false_input_conversion_cards(normalized: dict[str, Any], code: str) -> dict[str, Any]:
    converted_names = _input_names_converted_later(code)
    if not converted_names:
        return normalized

    cards = list(normalized.get("bug_cards") or [])
    filtered: list[dict[str, Any]] = []
    changed = False
    for card in cards:
        text = _card_text(card).lower()
        accuses_conversion = (
            "input" in text
            and any(term in text for term in ("int", "float", "typeerror", "型別", "轉換", "轉型", "字串"))
            and any(
                term in text
                for term in (
                    "未",
                    "忘記",
                    "沒有",
                    "缺少",
                    "forgot",
                    "needs",
                    "need",
                    "missing",
                    "not converted",
                    "without converting",
                )
            )
        )
        mentions_converted_name = any(re.search(rf"\b{re.escape(name)}\b", _card_text(card)) for name in converted_names)
        if accuses_conversion and mentions_converted_name:
            changed = True
            continue
        filtered.append(card)

    if changed:
        normalized["bug_cards"] = filtered[:3]
    return normalized


def _input_names_converted_later(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return _input_names_converted_later_text(code)

    input_names: set[str] = set()
    converted_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_input_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    input_names.add(target.id)
        if isinstance(node, ast.Assign) and _is_conversion_of_input_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    converted_names.add(target.id)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if not isinstance(node.value.func, ast.Name) or node.value.func.id not in {"int", "float"}:
                continue
            if not node.value.args or not isinstance(node.value.args[0], ast.Name):
                continue
            source_name = node.value.args[0].id
            if source_name not in input_names:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    converted_names.add(source_name)
                    converted_names.add(target.id)
    return converted_names


def _input_names_converted_later_text(code: str) -> set[str]:
    input_names: set[str] = set()
    converted_names: set[str] = set()
    for line in code.splitlines():
        input_match = re.match(r"\s*([A-Za-z_]\w*)\s*=\s*input\s*\(", line)
        if input_match:
            input_names.add(input_match.group(1))
            continue
        inline_convert_match = re.match(r"\s*([A-Za-z_]\w*)\s*=\s*(int|float)\s*\(\s*input\s*\(", line)
        if inline_convert_match:
            converted_names.add(inline_convert_match.group(1))
            continue
        convert_match = re.match(r"\s*([A-Za-z_]\w*)\s*=\s*(int|float)\s*\(\s*([A-Za-z_]\w*)\s*\)", line)
        if convert_match and convert_match.group(3) in input_names:
            converted_names.add(convert_match.group(1))
            converted_names.add(convert_match.group(3))
    return converted_names


def _repair_input_order_comparison_cards(
    normalized: dict[str, Any], code: str, language: Language = "zh-Hant"
) -> dict[str, Any]:
    diagnostic = _input_order_comparison_diagnostic(code)
    if not diagnostic:
        return normalized

    cards = list(normalized.get("bug_cards") or [])
    changed = False
    for index, card in enumerate(cards):
        text = _card_text(card).lower()
        if "input" not in text:
            continue
        if "typeerror" in text and "logic error" not in text:
            continue
        if any(term in text for term in ("logic error", "邏輯錯誤", "永遠", "false", "唔會出錯", "不會出錯", "冇報錯")):
            replacement = _input_order_comparison_card(diagnostic, language)
            replacement["id"] = _as_string(card.get("id")) or replacement["id"]
            cards[index] = replacement
            changed = True

    if changed:
        normalized["bug_cards"] = cards[:3]
    return normalized


def _input_order_comparison_diagnostic(code: str) -> dict[str, Any] | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    lines = code.splitlines()
    input_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not _is_input_call(node.value):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                input_names.add(target.id)

    if not input_names:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for op in node.ops):
            continue
        names = [part.id for part in [node.left, *node.comparators] if isinstance(part, ast.Name)]
        input_name = next((name for name in names if name in input_names), "")
        if not input_name:
            continue
        line_no = getattr(node, "lineno", 0)
        return {
            "name": input_name,
            "line_no": line_no,
            "line": lines[line_no - 1].strip() if 0 < line_no <= len(lines) else "",
        }

    return None


def _is_input_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "input"
    )


def _is_conversion_of_input_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"int", "float"}
        and bool(node.args)
        and _is_input_call(node.args[0])
    )


def _input_order_comparison_card(
    diagnostic: dict[str, Any], language: Language = "zh-Hant"
) -> dict[str, Any]:
    name = _as_string(diagnostic.get("name"))
    line_no = int(diagnostic.get("line_no") or 0)
    line = _as_string(diagnostic.get("line"))
    if language == "en":
        return {
            "id": f"bug-type-{name}",
            "title": f"{name} is compared before being converted to a number",
            "error_type": "TypeError",
            "teaching_concept": "input() returns text; text and numbers cannot be compared directly with > or <.",
            "code_location": f"line {line_no}: {line}",
            "classroom_symptom": f"Line {line_no} raises TypeError because {name} is still a str.",
            "guiding_questions": [
                f"{name} comes from input(). Is its type text or number?",
                "Can Python 3 directly compare str and int with ordering operators?",
            ],
            "progressive_hints": [
                f"Add print(type({name})) before the comparison to observe the type.",
                "Use int(input(...)) or float(input(...)) before making a > / < comparison.",
            ],
            "teacher_explanation": "In Python 3, comparing str with int/float using ordering operators raises TypeError; it is not simply a logic result of False.",
            "fix_summary": f"Change {name} = input(...) to {name} = int(input(...)), or use float(...) if the task needs decimals.",
            "extension_activity": "Ask students to try == and > separately, then observe how string-number comparisons behave differently.",
            "related_code_snippet": line,
            "severity": "beginner",
        }
    return {
        "id": f"bug-type-{name}",
        "title": f"{name} 未轉成數字就比較大小",
        "error_type": "TypeError",
        "teaching_concept": "input() 回傳文字；文字和數字不能直接用 > 或 < 比較",
        "code_location": f"第{line_no}行：{line}",
        "classroom_symptom": f"執行到第{line_no}行時會出現 TypeError，因為 {name} 仍然是 str。",
        "guiding_questions": [
            f"{name} 是由 input() 得到，資料類型是文字還是數字？",
            "Python 3 可不可以直接比較 str 和 int 的大小？",
        ],
        "progressive_hints": [
            f"在比較前加 print(type({name})) 觀察類型。",
            f"用 int(input(...)) 或 float(input(...)) 先轉型，再做 > / < 比較。",
        ],
        "teacher_explanation": "在 Python 3，str 和 int/float 做大小比較會 TypeError；這不是單純的邏輯 False。",
        "fix_summary": f"把 {name} = input(...) 改成 {name} = int(input(...))，或按題目需要用 float(...)。",
        "extension_activity": "請學生分別試 == 和 >，觀察字串與數字比較時的差異。",
        "related_code_snippet": line,
        "severity": "beginner",
    }


def _card_falsely_accuses_if_elif(card: dict[str, Any], code: str) -> bool:
    text = _card_text(card).lower()
    has_elif_chain = bool(re.search(r"(?m)^\s*if\b[\s\S]*?^\s*elif\b", code))
    if not has_elif_chain:
        return False
    if re.search(r"(?m)^\s*else\s+\S.*:\s*$", code):
        return False

    says_two_branches = any(term in text for term in ("兩個訊息", "兩個輸出", "both", "two messages", "two outputs"))
    says_should_use_elif = "elif" in text and any(term in text for term in ("應該用", "should use", "確保只有一個"))
    return says_two_branches or says_should_use_elif


def _else_branch_card_from_code(code: str, language: Language = "zh-Hant") -> dict[str, Any] | None:
    lines = code.splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^\s*else\s*:\s*$", line):
            continue
        body_line_no = _next_nonblank_line_no(lines, index + 1)
        if not body_line_no:
            continue
        body = lines[body_line_no - 1].strip()
        if not re.search(r"print\s*\(", body):
            continue
        if not any(term in body for term in ("平手", "tie", "draw", "相同")):
            continue
        if language == "en":
            return {
                "id": f"bug-else-line-{body_line_no}",
                "title": "The else branch displays the wrong result",
                "error_type": "Logic Error",
                "teaching_concept": "if/elif/else runs only the first matching branch, so else must represent the remaining case.",
                "code_location": f"line {body_line_no}: {body}",
                "classroom_symptom": "The program can run, but some cases that miss the earlier conditions display an unreasonable result.",
                "guiding_questions": [
                    "Which cases have the previous if / elif branches already handled?",
                    "When execution reaches else, what case is actually left?",
                ],
                "progressive_hints": [
                    "if/elif/else does not run two branches at the same time; it chooses the first matching branch.",
                    "Change the output inside else so it matches the remaining case.",
                ],
                "teacher_explanation": "The issue is not missing elif and not two branches running together. The real check is whether the remaining case represented by else matches its printed message.",
                "fix_summary": f"Check the print message on line {body_line_no} inside else and change it to match the remaining case.",
                "extension_activity": "Ask students to list a table of branch conditions, then compare each print message with the matching case.",
                "related_code_snippet": body,
                "severity": "beginner",
            }
        return {
            "id": f"bug-else-line-{body_line_no}",
            "title": "else 分支顯示了錯誤結果",
            "error_type": "Logic Error",
            "teaching_concept": "if/elif/else 只會執行第一個符合條件的分支，else 要代表剩餘情況",
            "code_location": f"第{body_line_no}行：{body}",
            "classroom_symptom": "程式可以執行，但某些未命中前面條件的情況會顯示不合理的結果。",
            "guiding_questions": [
                "前面的 if / elif 已經處理了哪些情況？",
                "走到 else 時，實際剩下的是甚麼情況？",
            ],
            "progressive_hints": [
                "if/elif/else 不會同時執行兩個分支，只會揀第一個符合的分支。",
                "把 else 入面的輸出改成符合剩餘情況的訊息。",
            ],
            "teacher_explanation": "錯處不是缺少 elif，也不是兩個分支同時執行；真正要檢查的是 else 代表的剩餘情況和它輸出的訊息是否一致。",
            "fix_summary": f"檢查第{body_line_no}行 else 分支的 print 訊息，改成符合剩餘情況的結果。",
            "extension_activity": "請學生列出每個條件分支的情況表，再對照每個 print 是否符合該情況。",
            "related_code_snippet": body,
            "severity": "beginner",
        }
    return None


def _next_nonblank_line_no(lines: list[str], start_index: int) -> int:
    for index in range(start_index, len(lines)):
        if lines[index].strip():
            return index + 1
    return 0


def _python_name_analysis(code: str) -> dict[str, Any] | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    lines = code.splitlines()
    visitor = _NameUsageVisitor(lines)
    visitor.visit(tree)

    builtin_names = set(dir(builtins))
    problems: list[dict[str, Any]] = []
    for name, load in sorted(visitor.loads.items(), key=lambda item: item[1]["line_no"]):
        if name in builtin_names:
            continue
        bind = visitor.binds.get(name)
        if not bind:
            problems.append(
                {
                    "name": name,
                    "kind": "undefined",
                    "line_no": load["line_no"],
                    "line": load["line"],
                }
            )
        elif load["line_no"] < bind["line_no"]:
            problems.append(
                {
                    "name": name,
                    "kind": "used_before_bind",
                    "line_no": load["line_no"],
                    "line": load["line"],
                    "bind_line_no": bind["line_no"],
                }
            )

    return {
        "binds": visitor.binds,
        "loads": visitor.loads,
        "imports": visitor.imports,
        "problems": problems,
    }


class _NameUsageVisitor(ast.NodeVisitor):
    def __init__(self, lines: list[str]):
        self.lines = lines
        self.binds: dict[str, dict[str, Any]] = {}
        self.loads: dict[str, dict[str, Any]] = {}
        self.imports: list[dict[str, Any]] = []

    def visit_Import(self, node: ast.Import) -> None:
        line = self._line(node)
        for alias in node.names:
            source = alias.name.split(".")[0]
            bound = alias.asname or source
            self._bind(bound, node.lineno)
            self.imports.append(
                {
                    "kind": "import",
                    "source": source,
                    "bound": bound,
                    "line_no": node.lineno,
                    "line": line,
                }
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not node.module:
            return
        line = self._line(node)
        source = node.module.split(".")[0]
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            self._bind(bound, node.lineno)
            self.imports.append(
                {
                    "kind": "from",
                    "source": source,
                    "imported": alias.name,
                    "bound": bound,
                    "line_no": node.lineno,
                    "line": line,
                }
            )

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loads.setdefault(node.id, {"line_no": node.lineno, "line": self._line(node)})
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self._bind(node.id, node.lineno)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._bind(node.name, node.lineno)
        for default in node.args.defaults:
            self.visit(default)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._bind(node.name, node.lineno)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword)

    def _bind(self, name: str, line_no: int) -> None:
        self.binds.setdefault(name, {"line_no": line_no, "line": self._line_no(line_no)})

    def _line(self, node: ast.AST) -> str:
        return self._line_no(getattr(node, "lineno", 0))

    def _line_no(self, line_no: int) -> str:
        if 0 < line_no <= len(self.lines):
            return self.lines[line_no - 1].rstrip()
        return ""


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_as_string(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [_as_string(value)]


def fallback_pack(request: GeneratePackRequest) -> LessonPack:
    if request.language == "en":
        return _fallback_pack_en(request)

    topic_label = request.topic.strip() or "猜數字遊戲"
    concepts = ["secret_number", "guess", "input 轉型", "if/elif/else", "while 回合限制"]

    master_code = '''secret_number = 7
attempts = 0

print("Welcome to the number guessing game!")

while attempts < 3:
    guess = int(input("Guess a number from 1 to 10: "))
    attempts = attempts + 1

    if guess == secret_number:
        print("Correct! You found the number.")
        break
    elif guess < secret_number:
        print("Too low.")
    else:
        print("Too high.")

if guess != secret_number:
    print("Game over. The number was", secret_number)
'''

    starter_code = '''secret_number = 7
attempts = 0

print("Welcome to the number guessing game!")

while attempts < 3:
    # TODO: ask the player for a number and convert it to int
    guess = int(input("Guess a number from 1 to 10: "))
    attempts = attempts + 1

    # TODO: compare guess with secret_number
    if guess == secret_number:
        print("Correct! You found the number.")
        break
    elif guess < secret_number:
        # TODO: show a helpful hint
        print("Too low.")
    else:
        print("Too high.")

# TODO: show the answer if the player did not guess correctly
if guess != secret_number:
    print("Game over. The number was", secret_number)
'''

    buggy_code = '''secret_number = 7
attempts = 0

print("Welcome to the number guessing game!")

while attempts < 3:
    guess = input("Guess a number from 1 to 10: ")
    attempts = attempts + 1

    if gues == secret_number:
        print("Correct! You found the number.")
        break
    elif guess < secret_number:
        print("Too low.")
    else:
        print("Too high.")

if guess != secret_number:
    print("Game over. The number was", secret_number)
'''

    cards = [
        BugCard(
            id="bug-name-gues",
            title="Bug 1：變數名稱不一致",
            error_type="NameError",
            teaching_concept="變數名稱必須完全一致",
            code_location="第 9 行",
            classroom_symptom="學生輸入數字後，程式停止並顯示 NameError。",
            guiding_questions=[
                "錯誤訊息提到邊個變數名？",
                "程式前面有無建立過完全同名嘅變數？",
            ],
            progressive_hints=[
                "先睇 input() 儲存咗咩變數名。",
                "再睇 if statement 用咗邊個變數名。",
            ],
            teacher_explanation="Python 唔會自動估你想用邊個變數，串法唔同就係另一個名稱。",
            fix_summary="將 gues 改成 guess，統一 input() 同 if statement 使用嘅變數名稱。",
            extension_activity="叫學生自己製造一個 NameError，再交換俾同學修正。",
            related_code_snippet="if gues == secret_number:",
            severity="beginner",
        ),
        BugCard(
            id="bug-type-input",
            title="Bug 2：輸入文字未轉成數字",
            error_type="TypeError",
            teaching_concept="input() 回傳文字，要先轉成 int 先可以同數字比較",
            code_location="第 6、12 行",
            classroom_symptom="修正第一個 bug 後，程式會喺比較大小時出現 TypeError。",
            guiding_questions=[
                "input() 讀入嚟嘅資料係文字定數字？",
                "secret_number 係咩類型？兩者可以直接比較大小嗎？",
            ],
            progressive_hints=[
                "試下用 type(guess) 觀察變數類型。",
                "需要用 int(...) 將輸入轉成整數。",
            ],
            teacher_explanation="畫面見到 5 好似數字，但 input() 其實先俾 Python 一段文字。",
            fix_summary="將 guess = input(...) 改成 guess = int(input(...))。",
            extension_activity="加入輸入驗證，處理學生輸入 abc 時嘅 ValueError。",
            related_code_snippet='guess = input("Guess a number from 1 to 10: ")',
            severity="beginner",
        ),
    ]

    return LessonPack(
        topic=topic_label,
        level=request.level,
        duration=request.duration,
        lesson_title=f"用 Python 製作：{topic_label}",
        key_concepts=concepts[:5],
        lesson_flow=LessonFlow(
            warm_up=f"以「{topic_label}」開場：請學生先估 1 至 10 的 secret_number，板書 Too low / Too high / Correct 三種輸出，連到程式要記錄 guess 同 attempts。",
            build_activity=[
                "閱讀 Master Code 的三段結構：secret_number 固定答案、while attempts < 3 控制回合、if/elif/else 根據 guess 輸出提示。",
                "切換到 Starter Code，按 TODO 補回 int(input(...))、guess == secret_number 比較，以及猜錯後的 Too low / Too high 提示。",
                "用測試輸入 3、8、7 跑一次，要求學生對照 attempts 如何每回合加 1，並指出 break 在答中時停止遊戲。",
            ],
            debug_activity=[
                "執行 Buggy Code 並輸入 5，先定位 if gues == secret_number 造成的 NameError，讓學生圈出 gues / guess 差異。",
                "修正變數名後再次執行，觀察 guess = input(...) 令 guess 仍是文字，導致 elif guess < secret_number 出現 TypeError。",
                "把 guess 改為 int(input(...)) 後，用 3、8、7 驗證遊戲流程，確認兩張 Debug Card 對應的錯誤都已消失。",
            ],
            wrap_up="用本課兩個 bug 做總結：NameError 要先核對變數名稱是否一致；TypeError 要核對 input() 回傳文字是否已轉成 int。",
            teacher_notes=[
                "第一輪只讓學生看錯誤最後一行，找出 NameError 指向 gues，避免直接講答案。",
                "第二輪可插入 print(type(guess), type(secret_number))，讓學生看到 str 與 int 不能直接比較大小。",
                "若班級較初階，可把 while attempts < 3 當作固定框架，重點放在 guess、int(input(...))、if/elif/else 三個位置。",
            ],
        ),
        master_code=master_code,
        starter_code=starter_code,
        buggy_code=buggy_code,
        bug_cards=cards,
        run_suggestions=RunSuggestions(
            master_input="3\n8\n7\n",
            buggy_input="5\n",
            note="Master Code 可用 3、8、7 展示完整流程；Buggy Code 用任意數字即可觸發第一個錯誤。",
        ),
        metadata=Metadata(
            generated_at=_now_iso(),
            difficulty=request.level,
            source="fallback",
            language=request.language,
        ),
    )


def _fallback_pack_en(request: GeneratePackRequest) -> LessonPack:
    topic_label = request.topic.strip() or "number guessing game"
    concepts = ["secret_number", "guess", "input conversion", "if/elif/else", "while attempt limit"]

    master_code = '''secret_number = 7
attempts = 0

print("Welcome to the number guessing game!")

while attempts < 3:
    guess = int(input("Guess a number from 1 to 10: "))
    attempts = attempts + 1

    if guess == secret_number:
        print("Correct! You found the number.")
        break
    elif guess < secret_number:
        print("Too low.")
    else:
        print("Too high.")

if guess != secret_number:
    print("Game over. The number was", secret_number)
'''

    starter_code = '''secret_number = 7
attempts = 0

print("Welcome to the number guessing game!")

while attempts < 3:
    # TODO: ask the player for a number and convert it to int
    guess = int(input("Guess a number from 1 to 10: "))
    attempts = attempts + 1

    # TODO: compare guess with secret_number
    if guess == secret_number:
        print("Correct! You found the number.")
        break
    elif guess < secret_number:
        # TODO: show a helpful hint
        print("Too low.")
    else:
        print("Too high.")

# TODO: show the answer if the player did not guess correctly
if guess != secret_number:
    print("Game over. The number was", secret_number)
'''

    buggy_code = '''secret_number = 7
attempts = 0

print("Welcome to the number guessing game!")

while attempts < 3:
    guess = input("Guess a number from 1 to 10: ")
    attempts = attempts + 1

    if gues == secret_number:
        print("Correct! You found the number.")
        break
    elif guess < secret_number:
        print("Too low.")
    else:
        print("Too high.")

if guess != secret_number:
    print("Game over. The number was", secret_number)
'''

    cards = [
        BugCard(
            id="bug-name-gues",
            title="Bug 1: variable name mismatch",
            error_type="NameError",
            teaching_concept="Variable names must match exactly.",
            code_location="line 9",
            classroom_symptom="After students enter a number, the program stops and shows NameError.",
            guiding_questions=[
                "Which variable name does the error message mention?",
                "Has the program created an exactly matching variable earlier?",
            ],
            progressive_hints=[
                "First check which variable name stores the input.",
                "Then check which variable name the if statement uses.",
            ],
            teacher_explanation="Python will not guess which variable you meant. A different spelling is a different name.",
            fix_summary="Change gues to guess so the input line and if statement use the same variable name.",
            extension_activity="Ask students to create their own NameError, then swap code with a partner to repair it.",
            related_code_snippet="if gues == secret_number:",
            severity="beginner",
        ),
        BugCard(
            id="bug-type-input",
            title="Bug 2: input text is not converted to a number",
            error_type="TypeError",
            teaching_concept="input() returns text, so convert it to int before comparing with a number.",
            code_location="lines 6 and 12",
            classroom_symptom="After the first bug is fixed, the program raises TypeError during the size comparison.",
            guiding_questions=[
                "Does input() return text or a number?",
                "What type is secret_number? Can the two values be compared directly?",
            ],
            progressive_hints=[
                "Try print(type(guess)) to inspect the variable type.",
                "Use int(...) to convert the input to an integer.",
            ],
            teacher_explanation="The screen may show 5 like a number, but input() first gives Python a string.",
            fix_summary="Change guess = input(...) to guess = int(input(...)).",
            extension_activity="Add input validation for cases where students type abc and trigger ValueError.",
            related_code_snippet='guess = input("Guess a number from 1 to 10: ")',
            severity="beginner",
        ),
    ]

    return LessonPack(
        topic=topic_label,
        level=request.level,
        duration=request.duration,
        lesson_title=f"Build with Python: {topic_label}",
        key_concepts=concepts[:5],
        lesson_flow=LessonFlow(
            warm_up=f"Open with {topic_label}: ask students to guess a secret_number from 1 to 10, then connect the outputs Too low / Too high / Correct to the need for guess and attempts.",
            build_activity=[
                "Read the three-part structure in Master Code: fixed answer in secret_number, while attempts < 3 for turns, and if/elif/else for feedback.",
                "Switch to Starter Code and fill in int(input(...)), the guess == secret_number comparison, and the Too low / Too high hints.",
                "Run the sample inputs 3, 8, 7 once. Ask students to trace how attempts increases each turn and where break stops the game.",
            ],
            debug_activity=[
                "Run Buggy Code and enter 5. First locate the NameError caused by if gues == secret_number, then ask students to circle the gues / guess difference.",
                "After fixing the variable name, run again and observe that guess = input(...) leaves guess as text, causing TypeError at elif guess < secret_number.",
                "Change guess to int(input(...)), then test with 3, 8, 7 to confirm both debug-card issues are gone.",
            ],
            wrap_up="Summarize the two bugs: for NameError, check whether variable names match exactly; for TypeError, check whether input() text has been converted to int.",
            teacher_notes=[
                "In the first round, let students read only the final traceback line and find that NameError points to gues before giving the answer.",
                "In the second round, insert print(type(guess), type(secret_number)) so students can see why str and int cannot be compared with <.",
                "For a more beginner class, treat while attempts < 3 as a fixed frame and focus on guess, int(input(...)), and if/elif/else.",
            ],
        ),
        master_code=master_code,
        starter_code=starter_code,
        buggy_code=buggy_code,
        bug_cards=cards,
        run_suggestions=RunSuggestions(
            master_input="3\n8\n7\n",
            buggy_input="5\n",
            note="Use 3, 8, 7 with Master Code to show the complete flow. Any number in Buggy Code triggers the first error.",
        ),
        metadata=Metadata(
            generated_at=_now_iso(),
            difficulty=request.level,
            source="fallback",
            language=request.language,
        ),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
