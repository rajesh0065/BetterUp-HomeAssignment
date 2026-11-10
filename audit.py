"""
SQLite-backed audit trail and idempotency store.
Every propagation attempt is logged; duplicate events are detected by
content hash so re-deliveries from Ashby are safely ignored.
"""
import sqlite3
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "audit.db"


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS processed_events (
                event_hash   TEXT PRIMARY KEY,
                event_id     TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                result_json  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id     TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                change_type  TEXT NOT NULL,
                system       TEXT NOT NULL,
                success      INTEGER NOT NULL,
                attempts     INTEGER NOT NULL,
                message      TEXT,
                logged_at    TEXT NOT NULL
            );
        """)


def _event_hash(event_id: str, candidate_id: str, change_type: str, new_value: str) -> str:
    raw = f"{event_id}|{candidate_id}|{change_type}|{new_value}"
    return hashlib.sha256(raw.encode()).hexdigest()


def already_processed(event_id: str, candidate_id: str, change_type: str, new_value: str) -> Optional[dict]:
    h = _event_hash(event_id, candidate_id, change_type, new_value)
    with _conn() as con:
        row = con.execute(
            "SELECT result_json FROM processed_events WHERE event_hash = ?", (h,)
        ).fetchone()
    return json.loads(row["result_json"]) if row else None


def mark_processed(event_id: str, candidate_id: str, change_type: str, new_value: str, result: dict) -> None:
    h = _event_hash(event_id, candidate_id, change_type, new_value)
    with _conn() as con:
        con.execute(
            """INSERT OR IGNORE INTO processed_events
               (event_hash, event_id, candidate_id, processed_at, result_json)
               VALUES (?, ?, ?, ?, ?)""",
            (h, event_id, candidate_id, datetime.utcnow().isoformat(), json.dumps(result)),
        )


def log_system_result(event_id: str, candidate_id: str, change_type: str,
                       system: str, success: bool, attempts: int, message: str) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO audit_log
               (event_id, candidate_id, change_type, system, success, attempts, message, logged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, candidate_id, change_type, system,
             int(success), attempts, message, datetime.utcnow().isoformat()),
        )


def get_audit_trail(candidate_id: str) -> list:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM audit_log WHERE candidate_id = ? ORDER BY logged_at DESC",
            (candidate_id,),
        ).fetchall()
    return [dict(r) for r in rows]
