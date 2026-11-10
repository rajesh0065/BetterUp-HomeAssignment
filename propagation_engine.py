"""
Core orchestration engine.

Flow:
  1. Idempotency check — skip if this exact event was already processed.
  2. Claude assessment — validate the change before touching any downstream system.
  3. Routing — look up which systems need updating for this change type.
  4. Parallel dispatch — call each target system; retry up to MAX_RETRIES on failure.
  5. Audit — log every attempt regardless of outcome.
  6. Mark processed — write the content hash so re-deliveries are safe.
"""
import time
import concurrent.futures
from typing import Any, Dict, List

import audit
from claude_handler import assess_change
from models import ChangeEvent, ChangeType, PropagationResult, SystemResult, CHANGE_ROUTING
from mock_clients.workday import WorkdayClient
from mock_clients.okta import OktaClient
from mock_clients.expoit import ExpoITClient
from mock_clients.cohort_tracker import CohortTrackerClient

MAX_RETRIES = 3
BACKOFF_BASE = 0.1  # seconds (short for demo; production would be ~1s)

_CLIENTS = {
    "workday": WorkdayClient(),
    "okta": OktaClient(),
    "expoit": ExpoITClient(),
    "cohort_tracker": CohortTrackerClient(),
}


def _field_for_system(system: str, change_type: ChangeType, new_value: str) -> tuple[str, str]:
    """Translate a generic change type into the system-specific field name and value."""
    mapping: Dict[str, Dict[str, str]] = {
        "workday": {
            "start_date": "hire_date",
            "name": "legal_name",
            "address": "home_address",
            "location": "work_location",
            "title": "job_title",
            "department": "cost_center",
        },
        "okta": {
            "start_date": "startDate",
            "name": "displayName",
            "location": "city",
            "department": "department",
        },
        "expoit": {
            "start_date": "delivery_date",
            "name": "recipient_name",
            "address": "shipping_address",
            "location": "shipping_city",
        },
        "cohort_tracker": {
            "start_date": "start_date",
            "name": "full_name",
            "location": "office",
            "title": "job_title",
            "department": "department",
        },
    }
    field = mapping.get(system, {}).get(change_type.value, change_type.value)
    return field, new_value


def _call_system(system: str, event: ChangeEvent) -> SystemResult:
    client = _CLIENTS[system]
    field, value = _field_for_system(system, event.change_type, event.new_value)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if system == "workday":
                client.update_worker(event.candidate_id, field, value)
            elif system == "okta":
                profile = {field: value}
                client.update_user(f"okta-{event.candidate_id}", profile)
                if event.change_type == ChangeType.DEPARTMENT:
                    client.reassign_groups(f"okta-{event.candidate_id}", value)
            elif system == "expoit":
                client.update_order(f"order-{event.candidate_id}", field, value)
            elif system == "cohort_tracker":
                client.update_hire(event.candidate_id, field, value)

            return SystemResult(
                system=system,
                success=True,
                attempts=attempt,
                message=f"Updated {field}={value!r} successfully",
            )

        except Exception as exc:
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
            else:
                return SystemResult(
                    system=system,
                    success=False,
                    attempts=attempt,
                    message=str(exc),
                )

    # Unreachable but satisfies type checker
    return SystemResult(system=system, success=False, attempts=MAX_RETRIES, message="unknown error")


def process_event(event: ChangeEvent) -> PropagationResult:
    """Entry point: validate, assess, dispatch, audit."""

    # --- 1. Idempotency ---
    cached = audit.already_processed(
        event.event_id, event.candidate_id, event.change_type.value, event.new_value
    )
    if cached:
        cached["action"] = "duplicate_skipped"
        cached["overall_success"] = True
        return PropagationResult(**cached)

    # --- 2. Claude assessment ---
    assessment = assess_change(event)

    result = PropagationResult(
        event_id=event.event_id,
        candidate_id=event.candidate_id,
        change_type=event.change_type.value,
        action=assessment.action,
        claude_assessment=assessment,
    )

    if assessment.action in ("hold_for_review", "reject"):
        # Don't touch downstream systems — log and return
        audit.log_system_result(
            event.event_id, event.candidate_id, event.change_type.value,
            "all_systems", False, 0,
            f"Blocked by Claude: {assessment.reason}",
        )
        audit.mark_processed(
            event.event_id, event.candidate_id, event.change_type.value,
            event.new_value, result.model_dump(mode="json"),
        )
        result.overall_success = False
        return result

    # --- 3. Routing ---
    targets: List[str] = CHANGE_ROUTING.get(event.change_type, [])

    # --- 4. Parallel dispatch ---
    system_results: List[SystemResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = {pool.submit(_call_system, sys, event): sys for sys in targets}
        for future in concurrent.futures.as_completed(futures):
            system_results.append(future.result())

    # --- 5. Audit ---
    for sr in system_results:
        audit.log_system_result(
            event.event_id, event.candidate_id, event.change_type.value,
            sr.system, sr.success, sr.attempts, sr.message,
        )

    result.results = system_results
    result.overall_success = all(sr.success for sr in system_results)

    # --- 6. Mark processed ---
    audit.mark_processed(
        event.event_id, event.candidate_id, event.change_type.value,
        event.new_value, result.model_dump(mode="json"),
    )

    return result
