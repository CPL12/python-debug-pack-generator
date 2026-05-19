from __future__ import annotations

import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from app.error_explainer import detect_error_type, explain_error
from app.schemas import Language, RunCodeResponse, RunSessionState


SESSION_TIMEOUT_SECONDS = 120


def run_python_code(code: str, stdin: str = "", language: Language = "zh-Hant") -> RunCodeResponse:
    with tempfile.TemporaryDirectory(prefix="debug_pack_") as tmp:
        script_path = Path(tmp) / "lesson_code.py"
        script_path.write_text(code, encoding="utf-8")

        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(script_path)],
                input=stdin,
                text=True,
                capture_output=True,
                timeout=5,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return RunCodeResponse(
                ok=False,
                stderr="Code execution timed out after 5 seconds.",
                error_type="TimeoutError",
                explanation=explain_error("TimeoutError", language=language),
            )

    stdout = completed.stdout.replace(str(script_path), "lesson_code.py")
    stderr = completed.stderr.replace(str(script_path), "lesson_code.py")

    if completed.returncode == 0:
        return RunCodeResponse(ok=True, stdout=stdout, stderr=stderr)

    error_type = detect_error_type(stderr)
    return RunCodeResponse(
        ok=False,
        stdout=stdout,
        stderr=stderr,
        error_type=error_type,
        explanation=explain_error(error_type, stderr, language),
    )


class RunSession:
    def __init__(self, code: str, language: Language = "zh-Hant") -> None:
        self.id = uuid.uuid4().hex
        self.language = language
        self._tmp = tempfile.TemporaryDirectory(prefix="debug_pack_")
        self._script_path = Path(self._tmp.name) / "lesson_code.py"
        self._script_path.write_text(code, encoding="utf-8")
        self._output_queue: queue.Queue[str] = queue.Queue()
        self._output_parts: list[str] = []
        self._lock = threading.Lock()
        self.started_at = time.monotonic()
        self.last_seen_at = self.started_at

        self.process = subprocess.Popen(
            [sys.executable, "-I", "-u", str(self._script_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
            cwd=self._tmp.name,
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def send_input(self, text: str) -> None:
        if self.process.poll() is not None or self.process.stdin is None:
            return

        self._output_queue.put(f"{text}\n")
        self.process.stdin.write(f"{text}\n")
        self.process.stdin.flush()

    def state(self) -> RunSessionState:
        self.last_seen_at = time.monotonic()
        output = self._drain_output()
        exit_code = self.process.poll()
        error_type = None
        explanation = None

        if exit_code is not None and exit_code != 0:
            error_type = detect_error_type(output)
            explanation = explain_error(error_type, output, self.language)

        return RunSessionState(
            session_id=self.id,
            running=exit_code is None,
            output=output,
            exit_code=exit_code,
            error_type=error_type,
            explanation=explanation,
        )

    def stop(self) -> RunSessionState:
        if self.process.poll() is None:
            self.process.kill()
        return self.state()

    def expired(self) -> bool:
        return time.monotonic() - self.started_at > SESSION_TIMEOUT_SECONDS

    def cleanup(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self._drain_output()
        self._tmp.cleanup()

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        while True:
            char = self.process.stdout.read(1)
            if char == "":
                break
            self._output_queue.put(char)

    def _drain_output(self) -> str:
        while True:
            try:
                chunk = self._output_queue.get_nowait()
            except queue.Empty:
                break
            self._output_parts.append(chunk)

        output = "".join(self._output_parts)
        return output.replace(str(self._script_path), "lesson_code.py")


class RunSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, RunSession] = {}
        self._lock = threading.Lock()

    def start(self, code: str, language: Language = "zh-Hant") -> RunSessionState:
        self._sweep()
        session = RunSession(code, language)
        with self._lock:
            self._sessions[session.id] = session
        return session.state()

    def send_input(self, session_id: str, text: str) -> RunSessionState:
        session = self._get(session_id)
        session.send_input(text)
        return session.state()

    def state(self, session_id: str) -> RunSessionState:
        return self._get(session_id).state()

    def stop(self, session_id: str) -> RunSessionState:
        session = self._get(session_id)
        state = session.stop()
        session.cleanup()
        with self._lock:
            self._sessions.pop(session_id, None)
        return state

    def _get(self, session_id: str) -> RunSession:
        self._sweep()
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def _sweep(self) -> None:
        expired: list[str] = []
        with self._lock:
            for session_id, session in self._sessions.items():
                if session.expired():
                    expired.append(session_id)

        for session_id in expired:
            with self._lock:
                session = self._sessions.pop(session_id, None)
            if session is not None:
                session.cleanup()


run_sessions = RunSessionManager()
