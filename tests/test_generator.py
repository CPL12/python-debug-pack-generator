import json
import unittest

import httpx

from app.generator import (
    api_status,
    _describe_deepseek_error,
    _deepseek_payload,
    _extract_json,
    _lesson_flow_partial_events,
    _normalize_lesson_pack_data,
)
from app.schemas import GeneratePackRequest


class DeepSeekPayloadTests(unittest.TestCase):
    def _request(self, thinking="disabled") -> GeneratePackRequest:
        return GeneratePackRequest(
            topic="loops",
            level="小學",
            duration="30 分鐘",
            language="en",
            thinking=thinking,
        )

    def test_uses_v4_nonthinking_payload(self):
        payload = _deepseek_payload(self._request(thinking="disabled"), model="deepseek-v4-flash", stream=False)

        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("temperature", payload)
        self.assertNotIn("stream", payload)

    def test_uses_v4_thinking_payload(self):
        payload = _deepseek_payload(self._request(thinking="enabled"), model="deepseek-v4-flash", stream=False)

        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertNotIn("reasoning_effort", payload)

    def test_stream_payload_keeps_thinking_disabled(self):
        payload = _deepseek_payload(self._request(thinking="disabled"), model="deepseek-v4-flash", stream=True)

        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)
        self.assertTrue(payload["stream"])

    def test_api_status_reports_thinking_mode(self):
        status = api_status()

        self.assertEqual(status["thinking"], "disabled")
        self.assertNotIn("reasoning_effort", status)


class StreamingPartialTests(unittest.TestCase):
    def test_emits_lesson_flow_sections_as_fields_complete(self):
        emitted = set()
        content = (
            '{"topic":"loops","lesson_flow":{'
            '"warm_up":"Ask students to predict the output.",'
            '"build_activity":["Write a while loop.","Test with 3."],'
            '"debug_activity":["Find the wrong condition."]'
        )

        events = [json.loads(line) for line in _lesson_flow_partial_events(content, emitted)]

        self.assertEqual(
            [event["section"]["id"] for event in events],
            ["warmUp", "buildActivity", "debugActivity"],
        )
        self.assertEqual(events[1]["section"]["value"], ["Write a while loop.", "Test with 3."])
        self.assertEqual(_lesson_flow_partial_events(content, emitted), [])

        completed_content = (
            content
            + ',"wrap_up":"Share the fix.",'
            + '"teacher_notes":["Keep the discussion short."]},'
            + '"master_code":"print(1)"}'
        )
        events = [json.loads(line) for line in _lesson_flow_partial_events(completed_content, emitted)]

        self.assertEqual([event["section"]["id"] for event in events], ["wrapUp", "teacherNotes"])

    def test_waits_for_complete_json_values(self):
        emitted = set()
        content = '{"lesson_flow":{"warm_up":"Ask students'

        self.assertEqual(_lesson_flow_partial_events(content, emitted), [])
        self.assertEqual(emitted, set())

    def test_emits_run_suggestions_as_lesson_flow_section(self):
        emitted = {"warmUp", "buildActivity", "debugActivity", "wrapUp", "teacherNotes"}
        content = (
            '{"lesson_flow":{"warm_up":"Ask.","build_activity":["Build."],'
            '"debug_activity":["Debug."],"wrap_up":"Wrap.","teacher_notes":["Note."]},'
            '"run_suggestions":{"master_input":"1\\n","buggy_input":"2\\n",'
            '"note":"1. Run master first.\\n2. Run buggy next.\\n3. Compare outputs."},'
            '"master_code":"print(1)"}'
        )

        events = [json.loads(line) for line in _lesson_flow_partial_events(content, emitted)]

        self.assertEqual([event["section"]["id"] for event in events], ["runSuggestions"])
        self.assertEqual(
            events[0]["section"]["value"],
            "1. Run master first.\n2. Run buggy next.\n3. Compare outputs.",
        )

    def test_waits_for_complete_run_suggestions_note(self):
        emitted = {"warmUp", "buildActivity", "debugActivity", "wrapUp", "teacherNotes"}
        content = '{"run_suggestions":{"note":"1. Run master first.'

        self.assertEqual(_lesson_flow_partial_events(content, emitted), [])
        self.assertNotIn("runSuggestions", emitted)


class DeepSeekErrorDescriptionTests(unittest.TestCase):
    def test_describes_empty_timeout_exception(self):
        description = _describe_deepseek_error(httpx.ReadTimeout(""))

        self.assertIn("ReadTimeout", description)
        self.assertIn("timed out", description)

    def test_describes_http_status_without_losing_status_code(self):
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        response = httpx.Response(429, text='{"error":"rate limit"}', request=request)
        error = httpx.HTTPStatusError("bad response", request=request, response=response)

        description = _describe_deepseek_error(error)

        self.assertIn("HTTPStatusError", description)
        self.assertIn("HTTP 429", description)
        self.assertIn("rate limit", description)


class JsonExtractionTests(unittest.TestCase):
    def test_repairs_missing_comma_between_run_suggestions_and_code_field(self):
        content = (
            '{"lesson_flow":{"warm_up":"Ask.","build_activity":["Build."],'
            '"debug_activity":["Debug."],"wrap_up":"Wrap.","teacher_notes":["Note."]},'
            '\n"run_suggestions":{"master_input":"1\\n","buggy_input":"2\\n","note":"Run it."}'
            '\n"master_code":"print(1)"}'
        )

        data = _extract_json(content)

        self.assertEqual(data["run_suggestions"]["note"], "Run it.")
        self.assertEqual(data["master_code"], "print(1)")

    def test_repairs_missing_comma_inside_run_suggestions_object(self):
        content = (
            '{"run_suggestions":{"master_input":"1\\n"'
            '\n"buggy_input":"2\\n",'
            '\n"note":"Run it."}}'
        )

        data = _extract_json(content)

        self.assertEqual(data["run_suggestions"]["master_input"], "1\n")
        self.assertEqual(data["run_suggestions"]["buggy_input"], "2\n")

    def test_repairs_missing_comma_with_unknown_key(self):
        # "custom_extra" is not in JSON_FIELD_NAMES, but the generic repair
        # should still insert the comma so parsing succeeds.
        content = (
            '{"topic":"x",'
            '\n"bug_cards":[{"id":"bug-1","title":"T"'
            '\n"custom_extra":"value","error_type":"SyntaxError"}]}'
        )

        data = _extract_json(content)

        card = data["bug_cards"][0]
        self.assertEqual(card["title"], "T")
        self.assertEqual(card["custom_extra"], "value")

    def test_repairs_missing_comma_between_array_objects(self):
        content = (
            '{"bug_cards":['
            '{"id":"bug-1","title":"A"}'
            '\n{"id":"bug-2","title":"B"}'
            ']}'
        )

        data = _extract_json(content)

        self.assertEqual(len(data["bug_cards"]), 2)
        self.assertEqual(data["bug_cards"][1]["id"], "bug-2")

    def test_repairs_missing_comma_between_array_strings(self):
        content = (
            '{"lesson_flow":{"build_activity":['
            '"Step one."'
            '\n"Step two."'
            '\n"Step three."'
            ']}}'
        )

        data = _extract_json(content)

        self.assertEqual(
            data["lesson_flow"]["build_activity"],
            ["Step one.", "Step two.", "Step three."],
        )

    def test_repair_stages_compose_across_failures(self):
        # Combine two failure shapes that need different stages so the second
        # repair must build on top of the first.
        content = (
            '{"bug_cards":['
            '{"id":"bug-1","title":"A"}'
            '\n{"id":"bug-2","title":"B","unknown_key":"v"'
            '\n"error_type":"NameError"}'
            ']}'
        )

        data = _extract_json(content)

        self.assertEqual(data["bug_cards"][1]["unknown_key"], "v")
        self.assertEqual(data["bug_cards"][1]["error_type"], "NameError")


class DescriptiveTextNormalizationTests(unittest.TestCase):
    def test_strips_wrapping_quotes_and_decodes_literal_newlines_in_note(self):
        data = {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": "",
            "lesson_flow": {},
            "run_suggestions": {
                "master_input": "70\n1.75\n",
                "buggy_input": "70\n1.75\n",
                "note": "\"1. Run master_code with input.\\n2. Run buggy_code.\\n3. Compare outputs.\"",
            },
            "bug_cards": [],
        }

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(
            normalized["run_suggestions"]["note"],
            "1. Run master_code with input.\n2. Run buggy_code.\n3. Compare outputs.",
        )

    def test_normalizes_lesson_flow_text_fields(self):
        data = {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": "",
            "lesson_flow": {
                "warm_up": "\"Ask: what is BMI?\\nDiscuss for 2 minutes.\"",
                "build_activity": ["Step 1.\\nStep 2."],
                "debug_activity": ["Find error.\\nFix error."],
                "wrap_up": "Recap.\\nAssign homework.",
                "teacher_notes": ["Watch for confusion on line 5.\\nEncourage questions."],
            },
            "run_suggestions": {},
            "bug_cards": [],
        }

        normalized = _normalize_lesson_pack_data(data)
        flow = normalized["lesson_flow"]
        self.assertEqual(flow["warm_up"], "Ask: what is BMI?\nDiscuss for 2 minutes.")
        self.assertEqual(flow["wrap_up"], "Recap.\nAssign homework.")
        self.assertEqual(flow["build_activity"], ["Step 1.\nStep 2."])
        self.assertEqual(flow["debug_activity"], ["Find error.\nFix error."])
        self.assertEqual(
            flow["teacher_notes"], ["Watch for confusion on line 5.\nEncourage questions."]
        )

    def test_leaves_clean_text_untouched(self):
        data = {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": "",
            "lesson_flow": {"warm_up": "Real newline\nalready here.", "build_activity": [], "debug_activity": [], "wrap_up": "", "teacher_notes": []},
            "run_suggestions": {"note": "Already 'quoted' inside but not wrapped."},
            "bug_cards": [],
        }

        normalized = _normalize_lesson_pack_data(data)
        self.assertEqual(normalized["lesson_flow"]["warm_up"], "Real newline\nalready here.")
        self.assertEqual(
            normalized["run_suggestions"]["note"], "Already 'quoted' inside but not wrapped."
        )


class BugCardRepairTests(unittest.TestCase):
    def test_replaces_misleading_syntax_card_with_actual_error_line(self):
        data = {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": "msg = input('say:')\nif msg = 'yes':\n    print('ok')\n",
            "lesson_flow": {},
            "run_suggestions": {},
            "bug_cards": [
                {
                    "id": "bug-syntax",
                    "title": "Function call needs parentheses",
                    "error_type": "SyntaxError",
                    "teaching_concept": "input needs brackets",
                    "code_location": "line 1: msg = input('say:')",
                    "classroom_symptom": "SyntaxError: invalid syntax",
                    "guiding_questions": ["Does input have brackets?"],
                    "progressive_hints": ["Compare with print()."],
                    "teacher_explanation": "The input call is missing brackets.",
                    "fix_summary": "Add brackets after input.",
                    "extension_activity": "",
                    "related_code_snippet": "msg = input('say:')",
                    "severity": "beginner",
                }
            ],
        }

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["id"], "bug-syntax")
        self.assertEqual(card["related_code_snippet"], "if msg = 'yes':")
        self.assertIn("第2行", card["code_location"])
        self.assertIn("==", card["fix_summary"])

    def test_keeps_syntax_card_that_already_matches_actual_error_line(self):
        data = {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": "msg = input('say:')\nif msg = 'yes':\n    print('ok')\n",
            "lesson_flow": {},
            "run_suggestions": {},
            "bug_cards": [
                {
                    "id": "bug-syntax",
                    "title": "Use == in comparisons",
                    "error_type": "SyntaxError",
                    "teaching_concept": "condition comparison",
                    "code_location": "line 2: if msg = 'yes':",
                    "classroom_symptom": "SyntaxError: invalid syntax",
                    "guiding_questions": [],
                    "progressive_hints": [],
                    "teacher_explanation": "",
                    "fix_summary": "Change = to ==.",
                    "extension_activity": "",
                    "related_code_snippet": "if msg = 'yes':",
                    "severity": "beginner",
                }
            ],
        }

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(normalized["bug_cards"][0]["title"], "Use == in comparisons")

    def test_replaces_wrong_explanation_even_when_snippet_matches_line(self):
        data = {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": "msg = input('say:')\nif msg = 'yes':\n    print('ok')\n",
            "lesson_flow": {},
            "run_suggestions": {},
            "bug_cards": [
                {
                    "id": "bug-syntax",
                    "title": "Function call needs parentheses",
                    "error_type": "SyntaxError",
                    "teaching_concept": "input needs brackets",
                    "code_location": "line 2: if msg = 'yes':",
                    "classroom_symptom": "SyntaxError: invalid syntax",
                    "guiding_questions": [],
                    "progressive_hints": [],
                    "teacher_explanation": "The input call is missing brackets.",
                    "fix_summary": "Add brackets after input.",
                    "extension_activity": "",
                    "related_code_snippet": "if msg = 'yes':",
                    "severity": "beginner",
                }
            ],
        }

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(normalized["bug_cards"][0]["related_code_snippet"], "if msg = 'yes':")
        self.assertIn("==", normalized["bug_cards"][0]["fix_summary"])

    def test_replaces_missing_import_card_when_module_is_imported_with_alias(self):
        data = self._pack_with_single_card(
            "import random as r\nprint(random.randint(1, 6))\n",
            {
                "title": "Forgot import random",
                "error_type": "NameError",
                "teaching_concept": "missing import",
                "classroom_symptom": "NameError: name 'random' is not defined",
                "fix_summary": "Add import random.",
            },
        )

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["related_code_snippet"], "print(random.randint(1, 6))")
        self.assertNotEqual(card["title"], "Forgot import random")
        self.assertIn("r", card["fix_summary"])

    def test_replaces_missing_import_card_when_from_import_does_not_bind_module(self):
        data = self._pack_with_single_card(
            "from random import randint\nprint(random.randint(1, 6))\n",
            {
                "title": "Forgot import random",
                "error_type": "NameError",
                "teaching_concept": "missing import",
                "classroom_symptom": "NameError: name 'random' is not defined",
                "fix_summary": "Add import random.",
            },
        )

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["related_code_snippet"], "print(random.randint(1, 6))")
        self.assertNotEqual(card["title"], "Forgot import random")
        self.assertIn("import random", card["fix_summary"])

    def test_replaces_missing_import_card_when_import_is_after_first_use(self):
        data = self._pack_with_single_card(
            "print(random.randint(1, 6))\nimport random\n",
            {
                "title": "Forgot import random",
                "error_type": "NameError",
                "teaching_concept": "missing import",
                "classroom_symptom": "NameError: name 'random' is not defined",
                "fix_summary": "Add import random.",
            },
        )

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["related_code_snippet"], "print(random.randint(1, 6))")
        self.assertNotEqual(card["title"], "Forgot import random")
        self.assertIn("第1行", card["fix_summary"])

    def test_replaces_missing_random_import_card_with_actual_undefined_name(self):
        data = self._pack_with_single_card(
            "import random\nprint(randint(1, 6))\n",
            {
                "title": "Forgot import random",
                "error_type": "NameError",
                "teaching_concept": "missing import",
                "classroom_symptom": "NameError: name 'random' is not defined",
                "fix_summary": "Add import random.",
            },
        )

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["related_code_snippet"], "print(randint(1, 6))")
        self.assertIn("randint", card["title"])

    def test_replaces_name_error_card_that_accuses_defined_variable(self):
        data = self._pack_with_single_card(
            "guess = input('number: ')\nif gues == '7':\n    print('ok')\n",
            {
                "title": "guess is not defined",
                "error_type": "NameError",
                "teaching_concept": "variable names",
                "classroom_symptom": "NameError: name 'guess' is not defined",
                "fix_summary": "Create guess before using it.",
            },
        )

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["related_code_snippet"], "if gues == '7':")
        self.assertIn("gues", card["title"])
        self.assertIn("guess", card["fix_summary"])

    def test_keeps_exact_missing_import_card_when_not_contradicted(self):
        data = self._pack_with_single_card(
            "print(random.randint(1, 6))\n",
            {
                "title": "Forgot import random",
                "error_type": "NameError",
                "teaching_concept": "missing import",
                "classroom_symptom": "NameError: name 'random' is not defined",
                "fix_summary": "Add import random.",
            },
        )

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(normalized["bug_cards"][0]["title"], "Forgot import random")

    def test_replaces_false_if_elif_multiple_branch_accusation(self):
        data = self._pack_with_single_card(
            "if guess > dice:\n    print('你輸咗！')\nelif guess == dice:\n    print('你贏咗！')\nelse:\n    print('平手！')\n",
            {
                "title": "條件順序錯誤",
                "error_type": "Logic Error",
                "teaching_concept": "if/elif 條件順序影響程式流程",
                "classroom_symptom": "會輸出兩個訊息",
                "progressive_hints": ["應該用 elif 確保只有一個條件執行"],
                "fix_summary": "改用 elif。",
                "related_code_snippet": "if guess > dice:",
            },
        )

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["related_code_snippet"], "print('平手！')")
        self.assertIn("else", card["title"])
        self.assertNotIn("改用 elif", card["fix_summary"])

    def test_replaces_logic_card_that_contradicts_syntax_error(self):
        data = self._pack_with_single_card(
            "if guess = dice:\n    print('你贏了！')\n",
            {
                "title": "賦值等號用錯咗",
                "error_type": "Logic Error",
                "teaching_concept": "== 比較 vs = 賦值",
                "classroom_symptom": "程式冇報錯，但永遠輸出「你贏了！」",
                "fix_summary": "將 = 改做 ==。",
                "related_code_snippet": "if guess = dice:",
            },
        )

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["error_type"], "SyntaxError")
        self.assertIn("SyntaxError", card["classroom_symptom"])
        self.assertEqual(card["related_code_snippet"], "if guess = dice:")

    def test_runtime_card_after_syntax_error_is_qualified(self):
        data = {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": "dicee = 3\nprint(dice)\nelse if dicee > 2:\n    print('high')\n",
            "lesson_flow": {},
            "run_suggestions": {},
            "bug_cards": [
                {
                    "id": "bug-name",
                    "title": "dice 未定義",
                    "error_type": "NameError",
                    "teaching_concept": "變數名一致",
                    "code_location": "第2行：print(dice)",
                    "classroom_symptom": "執行時出現 NameError: name 'dice' is not defined",
                    "guiding_questions": [],
                    "progressive_hints": [],
                    "teacher_explanation": "第1行建立的是 dicee。",
                    "fix_summary": "將 dice 改成 dicee。",
                    "extension_activity": "",
                    "related_code_snippet": "print(dice)",
                    "severity": "beginner",
                },
                {
                    "id": "bug-syntax",
                    "title": "else if 寫法錯誤",
                    "error_type": "SyntaxError",
                    "teaching_concept": "Python 用 elif",
                    "code_location": "第3行：else if dicee > 2:",
                    "classroom_symptom": "執行時出現 SyntaxError: invalid syntax",
                    "guiding_questions": [],
                    "progressive_hints": [],
                    "teacher_explanation": "Python 要用 elif。",
                    "fix_summary": "將 else if 改成 elif。",
                    "extension_activity": "",
                    "related_code_snippet": "else if dicee > 2:",
                    "severity": "beginner",
                },
            ],
        }

        normalized = _normalize_lesson_pack_data(data)
        name_card = next(card for card in normalized["bug_cards"] if card["id"] == "bug-name")

        self.assertTrue(name_card["classroom_symptom"].startswith("修正語法錯誤後"))

    def test_attribute_error_card_after_syntax_error_is_qualified(self):
        data = {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": "import random\nx = random.randit(1, 6)\nif x = 3:\n    print(x)\n",
            "lesson_flow": {},
            "run_suggestions": {},
            "bug_cards": [
                {
                    "id": "bug-attr",
                    "title": "random.randit 拼寫錯誤",
                    "error_type": "AttributeError",
                    "teaching_concept": "函數名稱必須正確",
                    "code_location": "第2行：x = random.randit(1, 6)",
                    "classroom_symptom": "執行後出現 AttributeError",
                    "guiding_questions": [],
                    "progressive_hints": [],
                    "teacher_explanation": "randint 串錯。",
                    "fix_summary": "改成 random.randint。",
                    "extension_activity": "",
                    "related_code_snippet": "x = random.randit(1, 6)",
                    "severity": "beginner",
                },
                {
                    "id": "bug-syntax",
                    "title": "比較條件用了單一等號",
                    "error_type": "SyntaxError",
                    "teaching_concept": "條件判斷要用 ==",
                    "code_location": "第3行：if x = 3:",
                    "classroom_symptom": "SyntaxError: invalid syntax",
                    "guiding_questions": [],
                    "progressive_hints": [],
                    "teacher_explanation": "",
                    "fix_summary": "改成 ==",
                    "extension_activity": "",
                    "related_code_snippet": "if x = 3:",
                    "severity": "beginner",
                },
            ],
        }

        normalized = _normalize_lesson_pack_data(data)
        attr_card = next(card for card in normalized["bug_cards"] if card["id"] == "bug-attr")

        self.assertTrue(attr_card["classroom_symptom"].startswith("修正語法錯誤後"))

    def test_input_order_comparison_is_type_error_not_logic_false(self):
        data = self._pack_with_single_card(
            "secret = 7\nguess = input('guess: ')\nif guess > secret:\n    print('high')\n",
            {
                "title": "忘記轉型：input() 回傳字串",
                "error_type": "Logic Error",
                "teaching_concept": "input() 回傳字串，比較前需轉為整數",
                "classroom_symptom": "唔會出錯，只會永遠 False，所以走 else",
                "fix_summary": "用 int() 包住 input()。",
                "related_code_snippet": "guess = input('guess: ')",
            },
        )

        normalized = _normalize_lesson_pack_data(data)
        card = normalized["bug_cards"][0]

        self.assertEqual(card["error_type"], "TypeError")
        self.assertEqual(card["related_code_snippet"], "if guess > secret:")

    def test_drops_nonexistent_bug_card(self):
        data = self._pack_with_single_card(
            "if guess == secret:\n    print('ok')\n",
            {
                "title": "比較運算子錯誤：用 = 代替 ==",
                "error_type": "Syntax Error",
                "teaching_concept": "賦值 = vs 比較 ==",
                "classroom_symptom": "呢個 bug 唔存在，請忽略。",
                "fix_summary": "呢張卡要改為另一個 bug。",
                "related_code_snippet": "if guess == secret:",
            },
        )

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(normalized["bug_cards"], [])

    def test_drops_name_error_card_that_accuses_definition_line_when_syntax_error_blocks_ast(self):
        data = self._pack_with_single_card(
            "import random\n\nscpre = 0\nfor i in range(3):\n    tyre = random.randit(1, 5)\n    guess = int(input('估輸坎位置 (1-5): '))\n    if guess = tyre:\n        scpre += 10\nprint('總分:', scpre)\n",
            {
                "title": "變數名打錯",
                "error_type": "NameError",
                "teaching_concept": "變數名稱必須一致",
                "code_location": "第3行：scpre = 0",
                "classroom_symptom": "執行時出現 NameError: name 'scpre' is not defined",
                "guiding_questions": ["你見到咩錯誤？"],
                "progressive_hints": ["留意第3行同第8、11、14行嘅變數名。"],
                "fix_summary": "將 scpre 改成 score。",
                "related_code_snippet": "scpre = 0",
            },
        )

        normalized = _normalize_lesson_pack_data(data)

        self.assertNotIn("NameError", [card["error_type"] for card in normalized["bug_cards"]])
        self.assertTrue(any(card["error_type"] == "SyntaxError" for card in normalized["bug_cards"]))

    def test_drops_syntax_card_when_buggy_code_compiles(self):
        data = self._pack_with_single_card(
            "choice = input('轉換方向？輸入 C 或 F：')\nif choice == 'C':\n    print('ok')\n",
            {
                "title": "缺少右引號導致語法錯誤",
                "error_type": "SyntaxError",
                "teaching_concept": "字串必須用成對引號括住",
                "code_location": "第1行",
                "classroom_symptom": "執行時出現 SyntaxError: EOL while scanning string literal",
                "fix_summary": "補回右引號。",
                "related_code_snippet": "choice = input('轉換方向？輸入 C 或 F：')",
            },
        )

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(normalized["bug_cards"], [])

    def test_drops_input_not_converted_card_when_code_converts_variable(self):
        data = self._pack_with_single_card(
            "while True\n    guess = input('num: ')\n    guess = int(guess)\n    if guess > 3:\n        print('high')\n",
            {
                "title": "未將輸入轉為整數導致型別錯誤",
                "error_type": "TypeError",
                "teaching_concept": "input() 回傳字串，比較前需用 int() 轉換",
                "classroom_symptom": "TypeError: '>' not supported between str and int",
                "fix_summary": "用 int() 轉換 guess。",
                "related_code_snippet": "guess = input('num: ')",
            },
        )

        normalized = _normalize_lesson_pack_data(data)

        self.assertNotIn("TypeError", [card["error_type"] for card in normalized["bug_cards"]])

    def test_drops_input_not_converted_card_when_code_uses_inline_conversion(self):
        data = self._pack_with_single_card(
            "score = int(input('score: '))\nif score >= 60:\n    print('pass')\n",
            {
                "title": "Forgot to convert input",
                "error_type": "TypeError",
                "teaching_concept": "input() needs int()",
                "classroom_symptom": "TypeError comparing str and int",
                "fix_summary": "Use int() on score.",
                "related_code_snippet": "score = int(input('score: '))",
            },
        )

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(normalized["bug_cards"], [])

    def test_drops_name_error_card_that_accuses_defined_name(self):
        data = self._pack_with_single_card(
            "full_name = input('name: ')\nparts = full_name.split()\nlastname = parts[1]\nprint(lastname[1])\n",
            {
                "title": "lastname is not defined",
                "error_type": "NameError",
                "teaching_concept": "variable names must match",
                "classroom_symptom": "NameError: name 'lastname' is not defined",
                "fix_summary": "Define lastname before using it.",
                "related_code_snippet": "lastname = parts[1]",
            },
        )

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(normalized["bug_cards"], [])

    def test_drops_model_meta_reasoning_card(self):
        data = self._pack_with_single_card(
            "choice = input('choice: ')\nif choice == 1:\n    print('one')\n",
            {
                "title": "String and int comparison",
                "error_type": "TypeError",
                "teaching_concept": "input conversion",
                "classroom_symptom": "原 buggy_code 使用 ==，這不會報錯；我將調整描述。",
                "fix_summary": "為符合規則，我將修改 buggy_code。",
                "related_code_snippet": "if choice == 1:",
            },
        )

        normalized = _normalize_lesson_pack_data(data)

        self.assertEqual(normalized["bug_cards"], [])

    def _pack_with_single_card(self, buggy_code, card):
        base_card = {
            "id": "bug-import",
            "title": "",
            "error_type": "",
            "teaching_concept": "",
            "code_location": "",
            "classroom_symptom": "",
            "guiding_questions": [],
            "progressive_hints": [],
            "teacher_explanation": "",
            "fix_summary": "",
            "extension_activity": "",
            "related_code_snippet": "",
            "severity": "beginner",
        }
        base_card.update(card)
        return {
            "key_concepts": [],
            "master_code": "",
            "starter_code": "",
            "buggy_code": buggy_code,
            "lesson_flow": {},
            "run_suggestions": {},
            "bug_cards": [base_card],
        }


if __name__ == "__main__":
    unittest.main()
