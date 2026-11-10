"""
Standalone demo — no server needed.

Runs four scenarios that showcase the core engine:
  1. Clean start-date change  → auto-propagates to all 4 systems in parallel
  2. Suspicious name change   → Claude/rules hold for review, nothing written downstream
  3. Address update with a forced ExpoIT failure on attempt 1 → retries, succeeds on attempt 2
  4. Duplicate event re-delivery → idempotency fires, zero downstream calls

Usage:
    python demo.py
    ANTHROPIC_API_KEY=sk-ant-... python demo.py   # enables live Claude assessment
"""
import os
from datetime import datetime, timedelta, timezone
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

import audit
from models import ChangeEvent, ChangeType
from mock_clients.expoit import ExpoITClient
from propagation_engine import process_event, _CLIENTS

console = Console()

audit.init_db()


def print_result(scenario: str, result) -> None:
    console.print()
    console.print(Panel(f"[bold cyan]{scenario}[/bold cyan]", box=box.ROUNDED))

    # Claude assessment
    if result.claude_assessment:
        ca = result.claude_assessment
        color = {"low": "green", "medium": "yellow", "high": "red"}.get(ca.risk_level, "white")
        console.print(f"  [bold]Claude assessment:[/bold] action=[{color}]{ca.action}[/{color}]  "
                      f"risk=[{color}]{ca.risk_level}[/{color}]")
        console.print(f"  [dim]Reason:[/dim] {ca.reason}")
        if ca.flags:
            console.print(f"  [dim]Flags:[/dim] {', '.join(ca.flags)}")

    if result.action in ("hold_for_review", "reject", "duplicate_skipped"):
        console.print(f"  [yellow]Propagation skipped — action: {result.action}[/yellow]")
        return

    # System results table
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
    table.add_column("System", style="cyan", width=18)
    table.add_column("Result", width=10)
    table.add_column("Attempts", justify="right", width=10)
    table.add_column("Message")

    for sr in sorted(result.results, key=lambda r: r.system):
        icon = "[green]✓ OK[/green]" if sr.success else "[red]✗ FAIL[/red]"
        table.add_row(sr.system, icon, str(sr.attempts), sr.message[:70])

    console.print(table)
    overall = "[green]ALL SYSTEMS UPDATED[/green]" if result.overall_success else "[red]PARTIAL FAILURE[/red]"
    console.print(f"  Overall: {overall}  (event_id={result.event_id[:8]}…)\n")


def main() -> None:
    using_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
    mode = "[green]live Claude API[/green]" if using_claude else "[yellow]rule-based fallback[/yellow]"
    console.print(Panel(
        f"[bold]BetterUp Onboarding Sync — Demo[/bold]\n"
        f"Assessment mode: {mode}\n"
        f"Set ANTHROPIC_API_KEY to enable live Claude assessment.",
        title="BetterUp", style="bold"
    ))

    # ── Scenario 1: Clean start-date change ──────────────────────────────────
    new_start = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    event1 = ChangeEvent(
        candidate_id="cand-1001",
        candidate_name="Priya Sharma",
        email="priya.sharma@gmail.com",
        change_type=ChangeType.START_DATE,
        old_value="2026-12-01",
        new_value=new_start,
        changed_by="recruiter@betterup.co",
    )
    result1 = process_event(event1)
    print_result("Scenario 1 — Start date change (clean)", result1)

    # ── Scenario 2: Suspicious name (contains digits) ────────────────────────
    event2 = ChangeEvent(
        candidate_id="cand-1002",
        candidate_name="Alex Johnson",
        email="alex.j@gmail.com",
        change_type=ChangeType.NAME,
        old_value="Alex Johnson",
        new_value="Al3x J0hns0n",        # digits in name — data error
        changed_by="system_import",
    )
    result2 = process_event(event2)
    print_result("Scenario 2 — Name with digits (suspicious — should be held)", result2)

    # ── Scenario 3: Address update — ExpoIT forced to fail on attempt 1 ───────
    # demo_fail_once guarantees the retry path is shown every run, not 10% of the time.
    expoit_client: ExpoITClient = _CLIENTS["expoit"]
    expoit_client.demo_fail_once = True
    expoit_client._failed_once = False

    event3 = ChangeEvent(
        candidate_id="cand-1003",
        candidate_name="Marcus Webb",
        email="marcus.webb@gmail.com",
        change_type=ChangeType.ADDRESS,
        old_value="123 Old Street, Austin, TX 78701",
        new_value="456 New Ave, Austin, TX 78702",
        changed_by="recruiter@betterup.co",
    )
    result3 = process_event(event3)
    print_result("Scenario 3 — Address change (ExpoIT fails attempt 1, retries to success)", result3)

    expoit_client.demo_fail_once = False  # restore normal behaviour

    # ── Scenario 4: Duplicate delivery (idempotency check) ───────────────────
    result4 = process_event(event1)   # same event as scenario 1
    print_result("Scenario 4 — Duplicate event1 re-delivered (should be skipped)", result4)

    # ── Audit trail ──────────────────────────────────────────────────────────
    console.print(Panel("[bold]Audit trail for cand-1001[/bold]", box=box.ROUNDED))
    trail = audit.get_audit_trail("cand-1001")
    for row in trail:
        status = "[green]✓[/green]" if row["success"] else "[red]✗[/red]"
        console.print(f"  {status} [{row['logged_at'][:19]}] {row['system']:18s} "
                      f"attempt={row['attempts']}  {row['message'][:60]}")
    console.print()


if __name__ == "__main__":
    main()
