from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Level = Literal["小學", "初中", "高中"]
Duration = Literal["30 分鐘", "1 小時", "90 分鐘"]
Language = Literal["zh-Hant", "en"]


class GeneratePackRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=160)
    level: Level
    duration: Duration
    language: Language = "zh-Hant"
    concepts: list[str] = Field(default_factory=list, max_length=6)


class LessonFlow(BaseModel):
    warm_up: str
    build_activity: list[str]
    debug_activity: list[str]
    wrap_up: str
    teacher_notes: list[str]


class BugCard(BaseModel):
    id: str
    title: str
    error_type: str
    teaching_concept: str
    code_location: str
    classroom_symptom: str
    guiding_questions: list[str]
    progressive_hints: list[str]
    teacher_explanation: str
    fix_summary: str
    extension_activity: str
    related_code_snippet: str
    severity: Literal["beginner", "intermediate", "advanced"] = "beginner"


class RunSuggestions(BaseModel):
    master_input: str = ""
    buggy_input: str = ""
    note: str = ""


class Metadata(BaseModel):
    generated_at: str
    difficulty: Level
    schema_version: str = "1.0"
    source: Literal["ai", "fallback"] = "fallback"
    language: Language = "zh-Hant"


class LessonPack(BaseModel):
    topic: str
    level: Level
    duration: Duration
    lesson_title: str
    key_concepts: list[str]
    lesson_flow: LessonFlow
    master_code: str
    starter_code: str
    buggy_code: str
    bug_cards: list[BugCard]
    run_suggestions: RunSuggestions
    metadata: Metadata


class RunCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20_000)
    stdin: str = Field(default="", max_length=4_000)
    language: Language = "zh-Hant"


class ErrorExplanation(BaseModel):
    error_type: str
    explanation: str
    teaching_concept: str


class RunCodeResponse(BaseModel):
    ok: bool
    stdout: str = ""
    stderr: str = ""
    error_type: str | None = None
    explanation: ErrorExplanation | None = None


class StartRunSessionRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20_000)
    language: Language = "zh-Hant"


class RunSessionInputRequest(BaseModel):
    text: str = Field(default="", max_length=1_000)


class RunSessionState(BaseModel):
    session_id: str
    running: bool
    output: str = ""
    exit_code: int | None = None
    error_type: str | None = None
    explanation: ErrorExplanation | None = None


class ExplainErrorRequest(BaseModel):
    error_type: str
    error_message: str = ""
    language: Language = "zh-Hant"
