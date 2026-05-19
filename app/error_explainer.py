from __future__ import annotations

import re

from app.schemas import ErrorExplanation, Language


ERROR_MAP: dict[Language, dict[str, tuple[str, str]]] = {
    "zh-Hant": {
        "NameError": (
            "程式用咗一個未定義嘅變數名稱。可以引導學生先讀錯誤訊息入面提到嘅名稱，再回到前面檢查有無建立過同一個變數。",
            "變數命名一致性",
        ),
        "SyntaxError": (
            "Python 無法理解呢一行嘅格式。通常要檢查括號、冒號、引號，或者 if / for / while 後面嘅結構。",
            "Python 語法結構",
        ),
        "IndentationError": (
            "縮排層級唔一致，令 Python 分唔清邊幾行屬於同一個程式區塊。",
            "block structure",
        ),
        "TypeError": (
            "資料類型用法唔配合，例如將文字直接同數字比較或計算。可以問學生每個變數而家係文字定數字。",
            "string / int / float",
        ),
        "ValueError": (
            "資料格式唔符合轉換要求，例如想將非數字文字轉成 int。可以同學生思考輸入驗證。",
            "input validation",
        ),
        "IndexError": (
            "程式想拎列表入面不存在嘅位置。可以用 len() 同實際 index 範圍幫學生建立邊界概念。",
            "list index",
        ),
        "Logic Error": (
            "程式可以執行，但結果唔符合預期。適合用 print tracing 或逐行預測流程去定位問題。",
            "條件判斷 / 流程控制",
        ),
        "TimeoutError": (
            "程式跑太久沒有結束，常見原因是 while 條件一直成立、等待輸入，或迴圈內忘記更新變數。可以請學生先找出重複執行的位置，再檢查停止條件。",
            "loop stopping condition",
        ),
    },
    "en": {
        "NameError": (
            "The program used a name that has not been defined. Ask students to read the exact name in the error message, then trace upward to see whether that same name was created.",
            "consistent variable names",
        ),
        "SyntaxError": (
            "Python could not understand the structure of this line. Check brackets, colons, quotes, comparison operators, and the shape after if / for / while.",
            "Python syntax structure",
        ),
        "IndentationError": (
            "The indentation levels are inconsistent, so Python cannot tell which lines belong to the same block.",
            "block structure",
        ),
        "TypeError": (
            "The data types do not match the operation, such as comparing text directly with a number. Ask students whether each value is currently a string or a number.",
            "string / int / float",
        ),
        "ValueError": (
            "The data format does not fit the conversion, such as converting non-numeric text with int(). This is a good point to discuss input validation.",
            "input validation",
        ),
        "IndexError": (
            "The program tried to access a list position that does not exist. Use len() and the actual index range to build the boundary concept.",
            "list index",
        ),
        "Logic Error": (
            "The program can run, but the result does not match the expectation. Use print tracing or line-by-line prediction to locate the issue.",
            "condition checks / flow control",
        ),
        "TimeoutError": (
            "The program ran too long without finishing. Common causes are a while condition that never changes, waiting for input, or forgetting to update a loop variable.",
            "loop stopping condition",
        ),
    },
}


def detect_error_type(stderr: str) -> str:
    for name in ERROR_MAP["en"]:
        if name in stderr:
            return name

    match = re.search(r"([A-Za-z]+Error):", stderr)
    if match:
        return match.group(1)

    return "Logic Error"


def explain_error(error_type: str, error_message: str = "", language: Language = "zh-Hant") -> ErrorExplanation:
    messages = ERROR_MAP.get(language, ERROR_MAP["zh-Hant"])
    fallback = (
        "呢個錯誤未有固定模板。建議先叫學生讀最後一行錯誤訊息，再定位相關行數同變數值。",
        "error reading strategy",
    )
    if language == "en":
        fallback = (
            "There is no fixed template for this error yet. Start by reading the last line of the traceback, then locate the related line number and variable value.",
            "error reading strategy",
        )

    explanation, concept = messages.get(error_type, fallback)
    if error_message and "line" in error_message:
        if language == "en":
            explanation = f"{explanation} For this run, pay special attention to the line number shown in the traceback."
        else:
            explanation = f"{explanation} 今次可以特別留意 traceback 入面標示嘅行數。"

    return ErrorExplanation(error_type=error_type, explanation=explanation, teaching_concept=concept)
