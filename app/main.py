from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.error_explainer import explain_error
from app.generator import api_status, generate_lesson_pack, stream_lesson_pack
from app.runner import run_python_code, run_sessions
from app.schemas import (
    ExplainErrorRequest,
    GeneratePackRequest,
    LessonPack,
    RunCodeRequest,
    RunCodeResponse,
    RunSessionInputRequest,
    RunSessionState,
    StartRunSessionRequest,
)


app = FastAPI(title="Python Debug Pack Generator")


@app.get("/api/status")
def status() -> dict[str, object]:
    return {"api": api_status()}


@app.post("/api/generate-pack", response_model=LessonPack)
async def generate_pack(request: GeneratePackRequest) -> LessonPack:
    return await generate_lesson_pack(request)


@app.post("/api/generate-pack/stream")
async def generate_pack_stream(request: GeneratePackRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_lesson_pack(request),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/run-code", response_model=RunCodeResponse)
def run_code(request: RunCodeRequest) -> RunCodeResponse:
    return run_python_code(request.code, request.stdin, request.language)


@app.post("/api/run-session", response_model=RunSessionState)
def start_run_session(request: StartRunSessionRequest) -> RunSessionState:
    return run_sessions.start(request.code, request.language)


@app.get("/api/run-session/{session_id}", response_model=RunSessionState)
def get_run_session(session_id: str) -> RunSessionState:
    try:
        return run_sessions.state(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run session not found") from exc


@app.post("/api/run-session/{session_id}/input", response_model=RunSessionState)
def send_run_session_input(session_id: str, request: RunSessionInputRequest) -> RunSessionState:
    try:
        return run_sessions.send_input(session_id, request.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run session not found") from exc


@app.delete("/api/run-session/{session_id}", response_model=RunSessionState)
def stop_run_session(session_id: str) -> RunSessionState:
    try:
        return run_sessions.stop(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run session not found") from exc


@app.post("/api/explain-error")
def explain(request: ExplainErrorRequest):
    return explain_error(request.error_type, request.error_message, request.language)


@app.get("/")
def index() -> FileResponse:
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
