#!/usr/bin/env python3
"""Emit one idempotent report for newly failed enabled Hermes cron jobs."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

MAX_REPORT_CHARS = 7000
_TRUNCATION_MARKER = "\n\n… [truncated]"
_FAILURE_JOB_STATUSES = {"error", "failed"}
_SUCCESS_EXECUTION_STATUS = "completed"


def _load_jobs(jobs_file: Path) -> dict[str, dict]:
    data = json.loads(jobs_file.read_text(encoding="utf-8"))
    return {
        str(job["id"]): job
        for job in data.get("jobs", [])
        if job.get("enabled") is True and job.get("state") == "scheduled"
    }


def _load_state(state_file: Path) -> dict | None:
    if not state_file.exists():
        return None
    return json.loads(state_file.read_text(encoding="utf-8"))


def _write_state(state_file: Path, cursor: tuple[str, str] | None) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_finished_at": cursor[0] if cursor else "",
        "last_execution_id": cursor[1] if cursor else "",
    }
    temporary = state_file.with_suffix(state_file.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(state_file)


def _execution_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    return connection.execute(
        """
        SELECT id, job_id, status, finished_at, error
        FROM executions
        WHERE finished_at IS NOT NULL
        ORDER BY finished_at, id
        """
    ).fetchall()


def _format_failure(job: dict, execution: sqlite3.Row) -> str:
    error = str(execution["error"] or "No error detail was recorded.").strip()
    return (
        "## Cron job failed\n"
        f"- Job: **{job.get('name') or execution['job_id']}** (`{execution['job_id']}`)\n"
        f"- Finished: `{execution['finished_at']}`\n"
        f"- Execution status: `{execution['status']}`\n\n"
        f"```text\n{error}\n```"
    )


def _bounded_report(chunks: list[str]) -> str:
    if not chunks:
        return ""
    report = "# Hermes cron failure report\n\n" + "\n\n---\n\n".join(chunks)
    if len(report) <= MAX_REPORT_CHARS:
        return report
    return report[: MAX_REPORT_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER


def collect_failure_report(
    *,
    jobs_file: Path,
    executions_db: Path,
    state_file: Path,
) -> str:
    """Return newly failed enabled-job executions and advance the durable cursor."""
    jobs = _load_jobs(jobs_file)
    state = _load_state(state_file)

    with sqlite3.connect(executions_db) as connection:
        rows = _execution_rows(connection)

    cursor = (rows[-1]["finished_at"], rows[-1]["id"]) if rows else None
    failures: list[sqlite3.Row] = []

    if state is None:
        # Establish a baseline without replaying historical failures. Surface only
        # the latest failed execution of each enabled job whose current state is
        # failed, so setup immediately proves the alert path with relevant data.
        for job_id, job in jobs.items():
            if str(job.get("last_status") or "").lower() not in _FAILURE_JOB_STATUSES:
                continue
            matching = [
                row
                for row in rows
                if row["job_id"] == job_id and row["status"] != _SUCCESS_EXECUTION_STATUS
            ]
            if matching:
                failures.append(matching[-1])
    else:
        previous = (
            str(state.get("last_finished_at") or ""),
            str(state.get("last_execution_id") or ""),
        )
        new_rows = [
            row for row in rows if (row["finished_at"], row["id"]) > previous
        ]
        failures = [
            row
            for row in new_rows
            if row["job_id"] in jobs and row["status"] != _SUCCESS_EXECUTION_STATUS
        ]

    _write_state(state_file, cursor)
    return _bounded_report([_format_failure(jobs[row["job_id"]], row) for row in failures])


def main() -> int:
    hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    report = collect_failure_report(
        jobs_file=hermes_home / "cron" / "jobs.json",
        executions_db=hermes_home / "cron" / "executions.db",
        state_file=hermes_home / "state" / "cron-failure-watch.json",
    )
    if report:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
