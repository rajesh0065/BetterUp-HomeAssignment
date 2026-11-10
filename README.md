# BetterUp Onboarding Sync

**Slice:** Change Propagation — when a field changes in Ashby, sync it to Workday, Okta/Lumos, ExpoIT, and the cohort tracker, with Claude as a data-quality gate before any downstream write.

## Quick start

```bash
# 1. Create venv and install dependencies
uv venv .venv
uv pip install fastapi uvicorn pydantic anthropic httpx rich python-dotenv --python .venv/Scripts/python.exe

# 2. Run the demo (no credentials needed — all APIs are mocked)
.venv/Scripts/python.exe demo.py

# 3. Optional: enable live Claude assessment
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.venv/Scripts/python.exe demo.py

# 4. Optional: run the webhook server
.venv/Scripts/python.exe -m uvicorn main:app --reload
# POST http://localhost:8000/webhooks/ashby  (body: ChangeEvent JSON)
# GET  http://localhost:8000/audit/{candidate_id}
```

## Demo scenarios

| # | What it shows |
|---|---|
| 1 | Clean start-date change → all 4 systems updated in parallel |
| 2 | Name with digits (`Al3x J0hns0n`) → Claude/rules hold for review, nothing written |
| 3 | Address change → ExpoIT fails on attempt 1, retries, succeeds on attempt 2 |
| 4 | Same event re-delivered → idempotency fires, zero downstream calls |

## Project structure

```
models.py               Pydantic data models + change routing table
audit.py                SQLite idempotency store + audit trail
claude_handler.py       Claude data-quality gate (falls back to rules if no API key)
propagation_engine.py   Core orchestrator — idempotency → assess → dispatch → retry → audit
mock_clients/           Realistic mocks for Workday, Okta, ExpoIT, CohortTracker
main.py                 FastAPI webhook server
demo.py                 Standalone runnable demo
systems_map.md          Deliverable 1 — systems map
build_note.md           Deliverable 3 — design decisions and build note
```

## Deliverables

- **Deliverable 1:** [systems_map.md](systems_map.md)
- **Deliverable 2:** This repo — run `demo.py`
- **Deliverable 3:** [build_note.md](build_note.md)
