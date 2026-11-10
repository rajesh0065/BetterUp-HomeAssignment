from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import uuid


class ChangeType(str, Enum):
    START_DATE = "start_date"
    NAME = "name"
    ADDRESS = "address"
    LOCATION = "location"
    TITLE = "title"
    DEPARTMENT = "department"


class ChangeEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    candidate_id: str
    candidate_name: str
    email: str
    change_type: ChangeType
    old_value: str
    new_value: str
    changed_by: str
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_system: str = "ashby"


class SystemResult(BaseModel):
    system: str
    success: bool
    attempts: int
    message: str
    payload: Optional[Dict[str, Any]] = None


class ClaudeAssessment(BaseModel):
    action: str           # auto_propagate | hold_for_review | reject
    risk_level: str       # low | medium | high
    reason: str
    flags: List[str] = []


class PropagationResult(BaseModel):
    event_id: str
    candidate_id: str
    change_type: str
    action: str
    claude_assessment: Optional[ClaudeAssessment] = None
    results: List[SystemResult] = []
    propagated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    overall_success: bool = False


# Which downstream systems need an update for each change type
CHANGE_ROUTING: Dict[ChangeType, List[str]] = {
    ChangeType.START_DATE:  ["workday", "okta", "expoit", "cohort_tracker"],
    ChangeType.NAME:        ["workday", "okta", "expoit", "cohort_tracker"],
    ChangeType.ADDRESS:     ["workday", "expoit"],
    ChangeType.LOCATION:    ["workday", "okta", "expoit", "cohort_tracker"],
    ChangeType.TITLE:       ["workday", "cohort_tracker"],
    ChangeType.DEPARTMENT:  ["workday", "okta", "cohort_tracker"],
}
