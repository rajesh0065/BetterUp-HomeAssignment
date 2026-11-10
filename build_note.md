# Build Note — BetterUp Onboarding Sync

## Why change propagation

The three problems in the assignment (changes don't propagate, bad data cascades, nobody watching deadlines) all share the same root: there is no authoritative propagation layer. Exception monitoring and cross-system validation are downstream features; you can't build either reliably without a propagation layer underneath. I picked the foundation.

---

## Key design decisions

### 1. Idempotency via content hash

Ashby (or n8n/Zapier delivering its events) can re-fire a webhook on network failure. I hash `event_id + candidate_id + change_type + new_value` and store it in SQLite before dispatching. If the same hash arrives twice, the engine returns the original result with zero downstream calls. This means retrying a webhook delivery is always safe.

A pure `event_id` check isn't enough: the same event ID could carry a corrected value if Ashby reuses IDs. Hashing the content catches that case.

### 2. Claude as a data-quality gate, not the orchestrator

Claude sits between Ashby and the downstream systems. Its job is narrow: given a change event, decide `auto_propagate | hold_for_review | reject`. It doesn't call any APIs, doesn't write to any database — it only classifies. This keeps the blast radius small if the LLM call fails (the engine falls back to rule-based assessment and continues) and keeps the prompt short and auditable.

The rule-based fallback also documents the validation logic in plain Python, which is easier to maintain than a prompt. Claude adds judgment for cases the rules can't anticipate (e.g., a name change from one legitimate name to another that happens to look like a typo).

### 3. Parallel dispatch with per-system retry

Each downstream system is called in its own thread (`ThreadPoolExecutor`). They are independent — an ExpoIT timeout shouldn't block the Workday write. Retry is per-system (up to 3×, exponential backoff), so a transient failure in one system doesn't cascade.

Partial success is a first-class outcome: `overall_success = all(sr.success)`. The audit log records which systems succeeded and which failed, so a human or a follow-up job can replay only the failed legs.

### 4. Field-name translation at the boundary

Each downstream system uses different field names for the same concept (`hire_date` in Workday, `startDate` in Okta, `delivery_date` in ExpoIT). The translation lives in a single dict in `propagation_engine.py::_field_for_system`. Adding a new system means adding one dict entry, not touching orchestration logic.

### 5. Audit trail as the source of truth

Every propagation attempt is written to `audit_log` with system name, success, attempt count, and message. This solves "nobody's watching the gates" in audit form: a simple query on `success = 0` surfaces every failed downstream write for a hire. In production this would feed a Slack alert or n8n monitoring flow.

---

## Data model

```
processed_events          audit_log
─────────────────         ────────────────────────────
event_hash PK             id PK (autoincrement)
event_id                  event_id
candidate_id              candidate_id
processed_at              change_type
result_json               system
                          success (0/1)
                          attempts
                          message
                          logged_at
```

---

## What I would productionize

| Area | Current (prototype) | Production |
|---|---|---|
| Transport | FastAPI + SQLite | n8n webhook node → engine as a service (or n8n Code node) |
| Auth | None | Ashby webhook HMAC signature verification |
| DB | SQLite | Postgres with connection pool |
| Retry | In-process backoff | n8n error workflow or a dedicated retry queue |
| Secrets | Env vars | Okta, Workday, ExpoIT credentials in Vault or AWS Secrets Manager |
| Observability | `audit_log` table | Datadog / CloudWatch + Slack alert on `overall_success = false` |
| Claude | Per-event call | Batch borderline cases; cache known-good patterns |
| Hold queue | Logged but dropped | Slack message to recruiter with one-click approve/reject |

The n8n fit is natural: the webhook receiver becomes an n8n HTTP trigger, the propagation engine becomes a Code node or a set of system-specific nodes, and the audit log feeds an n8n error handler. Claude stays as an API call in an n8n AI Agent node.

---

## AI tools used

- **Claude (claude-sonnet-4-6)** — wrote initial scaffolding for mock clients and the FastAPI routes; reviewed the idempotency design.
- **Claude Code** — used for iterative edits to the propagation engine and to validate the retry logic.

### One thing the AI got wrong and how I caught it

Claude initially generated the idempotency check using only `event_id` as the unique key. I caught it during review: Ashby can re-use or reassign event IDs in certain webhook retry scenarios, meaning a corrected value on a re-fired event would be silently skipped. I changed the hash to include `new_value` so that a change to the value always creates a new idempotency key, while a true duplicate delivery of the same content is still safely ignored.

---

## Bonus: MCP tool definition sketch

```json
{
  "name": "propagate_onboarding_change",
  "description": "Propagate a candidate field change from Ashby to all downstream systems.",
  "input_schema": {
    "type": "object",
    "properties": {
      "candidate_id":   { "type": "string" },
      "candidate_name": { "type": "string" },
      "email":          { "type": "string", "format": "email" },
      "change_type":    { "type": "string", "enum": ["start_date","name","address","location","title","department"] },
      "old_value":      { "type": "string" },
      "new_value":      { "type": "string" },
      "changed_by":     { "type": "string" }
    },
    "required": ["candidate_id","candidate_name","email","change_type","old_value","new_value","changed_by"]
  }
}
```

An n8n MCP server node could expose this tool so a recruiter can trigger propagation directly from a Claude conversation: "Priya's start date changed to Jan 15 — update everything." Claude calls the tool, the engine runs, and the response summarises which systems were updated.
