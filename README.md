# Python Debug Pack Generator

**English** | [繁體中文](README.zh-Hant.md)

AI-assisted, one-page teacher demo for turning a Python lesson idea into a classroom-ready debugging pack. It generates a lesson flow, master code, starter code, intentionally buggy code, teacher debug cards, live model output, and a local interactive runner.

These screenshots are captured from a real generated lesson pack:

| Lesson Flow | Debug Cards | Interactive Runner |
| --- | --- | --- |
| ![Generated lesson flow](docs/images/readme-01-overview.png) | ![Teacher debug cards](docs/images/readme-02-debug-cards.png) | ![Interactive Python runner](docs/images/readme-03-runner.png) |

The UI starts in English by default unless the browser language is Chinese. Users can still switch language from the top bar.

## Highlights

- Browser-language aware English / Traditional Chinese UI
- Streaming lesson-pack generation from an OpenAI-compatible chat API
- Master, starter, and buggy Python code views with syntax highlighting
- Teacher debug cards that point to specific code evidence
- Local interactive Python runner for demoing inputs and runtime errors
- Fallback generation when no API key is configured

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Configure A Model

The app talks to OpenAI-compatible `/chat/completions` endpoints. Copy `.env.example` to `.env`, then edit these values:

```text
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

To use another OpenAI-compatible provider:

1. Set the provider's API key in `DEEPSEEK_API_KEY`.
2. Set `DEEPSEEK_BASE_URL` to the provider base URL, without `/chat/completions`.
3. Set `DEEPSEEK_MODEL` to that provider's model name.
4. Restart `uvicorn`.
5. Check `GET /api/status` or the status pill in the UI.

The variable names still use `DEEPSEEK_` because DeepSeek was the first provider used by this demo. Any provider that accepts OpenAI-style chat completions can be tried, but provider-specific options such as `thinking` and `reasoning_effort` may need code changes if the provider rejects them.

## API

- `GET /api/status`
- `POST /api/generate-pack`
- `POST /api/generate-pack/stream`
- `POST /api/run-session`
- `POST /api/explain-error`

The runner executes local demo code with a short timeout. Keep it on localhost; it is not a sandbox for untrusted public traffic.

## License

No license is currently declared. Add one before allowing broad reuse.
