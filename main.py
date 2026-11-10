"""
FastAPI webhook server.

Endpoints:
  POST /webhooks/ashby          Receive a change event from Ashby
  GET  /audit/{candidate_id}    View the full audit trail for a hire
  GET  /health                  Liveness check
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

import audit
from models import ChangeEvent
from propagation_engine import process_event

app = FastAPI(title="BetterUp Onboarding Sync", version="1.0.0")

audit.init_db()


@app.post("/webhooks/ashby", status_code=200)
def ashby_webhook(event: ChangeEvent):
    result = process_event(event)
    return result.model_dump(mode="json")


@app.get("/audit/{candidate_id}")
def get_audit(candidate_id: str):
    trail = audit.get_audit_trail(candidate_id)
    if not trail:
        raise HTTPException(status_code=404, detail="No audit records found for this candidate")
    return {"candidate_id": candidate_id, "events": trail}


@app.get("/health")
def health():
    return {"status": "ok"}
