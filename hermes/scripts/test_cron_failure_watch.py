import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("cron-failure-watch.py")
spec = importlib.util.spec_from_file_location("cron_failure_watch", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cron_failure_watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cron_failure_watch)


class CronFailureWatchTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.jobs_file = self.root / "jobs.json"
        self.executions_db = self.root / "executions.db"
        self.state_file = self.root / "state.json"
        self.jobs = [
            {
                "id": "failed-job",
                "name": "Failed Job",
                "enabled": True,
                "state": "scheduled",
                "last_status": "error",
            },
            {
                "id": "healthy-job",
                "name": "Healthy Job",
                "enabled": True,
                "state": "scheduled",
                "last_status": "ok",
            },
            {
                "id": "paused-job",
                "name": "Paused Job",
                "enabled": False,
                "state": "paused",
                "last_status": "error",
            },
        ]
        self.jobs_file.write_text(json.dumps({"jobs": self.jobs}), encoding="utf-8")
        with sqlite3.connect(self.executions_db) as connection:
            connection.execute(
                """
                CREATE TABLE executions (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    finished_at TEXT,
                    error TEXT
                )
                """
            )
            connection.executemany(
                "INSERT INTO executions (id, job_id, status, finished_at, error) VALUES (?, ?, ?, ?, ?)",
                [
                    ("old-failure", "failed-job", "failed", "2026-08-24T23:00:00+07:00", "old error"),
                    ("latest-failure", "failed-job", "failed", "2026-08-25T12:10:02+07:00", "latest error"),
                    ("healthy-run", "healthy-job", "completed", "2026-08-25T12:11:00+07:00", None),
                    ("paused-failure", "paused-job", "failed", "2026-08-25T12:12:00+07:00", "paused error"),
                ],
            )

    def tearDown(self):
        self.tempdir.cleanup()

    def collect(self):
        return cron_failure_watch.collect_failure_report(
            jobs_file=self.jobs_file,
            executions_db=self.executions_db,
            state_file=self.state_file,
        )

    def test_first_run_reports_only_latest_failure_for_currently_failed_enabled_jobs(self):
        report = self.collect()

        self.assertIn("Failed Job", report)
        self.assertIn("latest error", report)
        self.assertNotIn("old error", report)
        self.assertNotIn("paused error", report)
        self.assertEqual(self.collect(), "")

    def test_future_runs_report_each_new_failure_once_and_advance_past_successes(self):
        self.collect()
        with sqlite3.connect(self.executions_db) as connection:
            connection.executemany(
                "INSERT INTO executions (id, job_id, status, finished_at, error) VALUES (?, ?, ?, ?, ?)",
                [
                    ("new-success", "failed-job", "completed", "2026-08-25T12:13:00+07:00", None),
                    ("new-failure", "healthy-job", "failed", "2026-08-25T12:14:00+07:00", "new failure detail"),
                ],
            )

        report = self.collect()

        self.assertIn("Healthy Job", report)
        self.assertIn("new failure detail", report)
        self.assertNotIn("new-success", report)
        self.assertEqual(self.collect(), "")

    def test_failure_detail_is_bounded(self):
        self.collect()
        with sqlite3.connect(self.executions_db) as connection:
            connection.execute(
                "INSERT INTO executions (id, job_id, status, finished_at, error) VALUES (?, ?, ?, ?, ?)",
                ("large-failure", "healthy-job", "failed", "2026-08-25T12:15:00+07:00", "x" * 10000),
            )

        report = self.collect()

        self.assertLessEqual(len(report), cron_failure_watch.MAX_REPORT_CHARS)
        self.assertIn("truncated", report)


if __name__ == "__main__":
    unittest.main()
