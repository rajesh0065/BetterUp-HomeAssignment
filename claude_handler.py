"""
Claude is used here as an intelligent gatekeeper, not the whole solution.

Before propagating a change, the engine asks Claude to assess whether the
data looks valid and whether it should auto-propagate, hold for human review,
or be rejected outright.  This catches bad-data cascades before they hit
downstream systems.

Falls back to rule-based assessment when ANTHROPIC_API_KEY is not set.
"""
import json
import os
import re
from typing import Optional

from models import ChangeEvent, ClaudeAssessment

KNOWN_LOCATIONS = {
    "San Francisco, CA", "New York, NY", "Austin, TX", "Chicago, IL",
    "Seattle, WA", "Boston, MA", "Los Angeles, CA", "Denver, CO",
    "Atlanta, GA", "Remote",
}


# ---------------------------------------------------------------------------
# Claude-powered assessment
# ---------------------------------------------------------------------------

def assess_change(event: ChangeEvent) -> ClaudeAssessment:
    """Return a ClaudeAssessment for the incoming change event."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return _claude_assess(event, api_key)
    return _rule_based_assess(event)


def _claude_assess(event: ChangeEvent, api_key: str) -> ClaudeAssessment:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        payload = {
            "candidate_id": event.candidate_id,
            "candidate_name": event.candidate_name,
            "email": event.email,
            "change_type": event.change_type.value,
            "old_value": event.old_value,
            "new_value": event.new_value,
            "changed_by": event.changed_by,
        }

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=(
                "You are a data-quality gatekeeper for HR onboarding at BetterUp. "
                "Analyze the incoming field change from Ashby and decide whether it "
                "is safe to propagate automatically to downstream systems "
                "(Workday, Okta, ExpoIT, cohort tracker). "
                "Reply with ONLY valid JSON matching this schema:\n"
                '{"action": "auto_propagate|hold_for_review|reject", '
                '"risk_level": "low|medium|high", '
                '"reason": "one sentence", '
                '"flags": ["list of specific concerns, empty if none"]}'
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Evaluate this change event and return your JSON assessment:\n"
                        + json.dumps(payload, indent=2)
                    ),
                }
            ],
        )

        raw = message.content[0].text.strip()
        # Strip markdown fences if Claude wraps it
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return ClaudeAssessment(**data)

    except Exception as exc:
        # Claude call failed — fall back to rules so propagation isn't blocked
        assessment = _rule_based_assess(event)
        assessment.flags.append(f"claude_unavailable: {exc}")
        return assessment


# ---------------------------------------------------------------------------
# Rule-based fallback (runs when no API key is configured)
# ---------------------------------------------------------------------------

def _rule_based_assess(event: ChangeEvent) -> ClaudeAssessment:
    flags: list[str] = []

    # Name sanity checks
    if event.change_type.value == "name":
        if re.search(r"\d", event.new_value):
            flags.append("name_contains_digits")
        if len(event.new_value.strip()) < 2:
            flags.append("name_too_short")
        if event.new_value.upper() == event.new_value:
            flags.append("name_all_caps")

    # Location check
    if event.change_type.value == "location":
        if event.new_value not in KNOWN_LOCATIONS:
            flags.append(f"unknown_location: {event.new_value!r}")

    # Start date sanity
    if event.change_type.value == "start_date":
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(event.new_value)
            if dt < datetime.now():
                flags.append("start_date_in_the_past")
        except ValueError:
            flags.append("start_date_not_iso8601")

    # Email domain check
    if not event.email.endswith("@betterup.co") and not event.email.endswith("@gmail.com"):
        # Candidates often have personal emails — don't flag, just note
        pass

    if not flags:
        return ClaudeAssessment(
            action="auto_propagate",
            risk_level="low",
            reason="All fields passed rule-based validation.",
            flags=[],
        )
    elif len(flags) == 1 and "unknown_location" in flags[0]:
        return ClaudeAssessment(
            action="hold_for_review",
            risk_level="medium",
            reason="Location not in known office list — may be a new remote location or typo.",
            flags=flags,
        )
    else:
        return ClaudeAssessment(
            action="hold_for_review",
            risk_level="high",
            reason="Multiple data anomalies detected — holding for recruiter review.",
            flags=flags,
        )
