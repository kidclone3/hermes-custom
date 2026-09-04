#!/usr/bin/env python3
"""Regression tests for job-scan deduplication."""
import importlib.util
import base64
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("job-scan.py")
spec = importlib.util.spec_from_file_location("job_scan", SCRIPT)
job_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job_scan)


class JobFingerprintTests(unittest.TestCase):
    def test_distinct_itviec_tracking_urls_have_distinct_deduplication_keys(self):
        self.assertTrue(hasattr(job_scan, "normalized_job_url"))
        first = "https://links.itviec.com/ls/click?upn=first"
        second = "https://links.itviec.com/ls/click?upn=second"

        self.assertNotEqual(
            job_scan.normalized_job_url(first),
            job_scan.normalized_job_url(second),
        )

    def test_linkedin_comm_and_canonical_urls_share_one_deduplication_key(self):
        self.assertEqual(
            job_scan.normalized_job_url(
                "https://www.linkedin.com/comm/jobs/view/4429171647/?tracking=abc"
            ),
            job_scan.normalized_job_url(
                "https://www.linkedin.com/jobs/view/4429171647/"
            ),
        )

    def test_fingerprint_decodes_html_and_normalizes_whitespace(self):
        encoded = {
            "company": "Kai Asia",
            "role": "Data Engineer",
            "location": "",
            "salary": "You&amp;#39;ll   love it",
        }
        plain = {
            "company": "  KAI ASIA ",
            "role": "data engineer",
            "location": "",
            "salary": "You'll love it",
        }
        self.assertEqual(job_scan.job_fingerprint(encoded), job_scan.job_fingerprint(plain))

    def test_fingerprint_from_notes_requires_company_and_role(self):
        structured = "Company: Kai Asia | Role: Data Engineer | Salary: You'll love it"
        self.assertIsNotNone(job_scan.notes_fingerprint(structured))
        self.assertIsNone(job_scan.notes_fingerprint("HCMC office"))

    def test_url_backed_job_is_not_duplicate_by_notes_alone(self):
        job = {
            "company": "Example",
            "role": "Software Engineer",
            "location": "HCMC",
            "salary": "Competitive",
            "url": "https://example.com/jobs/new-opening",
        }

        self.assertIsNone(job_scan.duplicate_reason(
            job,
            {"https://example.com/jobs/other-opening"},
            {job_scan.job_fingerprint(job)},
        ))

    def test_url_less_job_uses_notes_fingerprint(self):
        job = {
            "company": "Example",
            "role": "Software Engineer",
            "location": "HCMC",
            "salary": "Competitive",
            "url": "",
        }

        self.assertEqual(job_scan.duplicate_reason(
            job,
            set(),
            {job_scan.job_fingerprint(job)},
        ), "Notes")

    def test_prune_keeps_only_latest_structured_duplicate(self):
        def page(page_id, created_time, notes):
            return {
                "id": page_id,
                "created_time": created_time,
                "properties": {"Notes": {"rich_text": [{"plain_text": notes}]}},
            }

        pages = [
            page("old", "2026-08-10T00:00:00.000Z", "Company: Kai Asia | Role: Data Engineer | Salary: You'll love it"),
            page("new", "2026-08-11T00:00:00.000Z", "Company: Kai Asia | Role: Data Engineer | Salary: You&amp;#39;ll love it"),
            page("generic-a", "2026-08-10T00:00:00.000Z", "HCMC office"),
            page("generic-b", "2026-08-11T00:00:00.000Z", "HCMC office"),
        ]
        self.assertEqual(job_scan.duplicate_page_ids_to_archive(pages), ["old"])

    def test_prune_keeps_distinct_urls_with_the_same_structured_notes(self):
        notes = "Company: Example | Role: Software Engineer | Location: HCMC"

        def page(page_id, created_time, url):
            return {
                "id": page_id,
                "created_time": created_time,
                "properties": {
                    "Job URL": {"url": url},
                    "Notes": {"rich_text": [{"plain_text": notes}]},
                },
            }

        pages = [
            page("first", "2026-08-10T00:00:00.000Z", "https://example.com/jobs/1"),
            page("second", "2026-08-11T00:00:00.000Z", "https://example.com/jobs/2"),
        ]

        self.assertEqual(job_scan.duplicate_page_ids_to_archive(pages), [])

    def test_prune_archives_same_normalized_url_even_when_notes_changed(self):
        def page(page_id, created_time, url, notes):
            return {
                "id": page_id,
                "created_time": created_time,
                "properties": {
                    "Job URL": {"url": url},
                    "Notes": {"rich_text": [{"plain_text": notes}]},
                },
            }

        pages = [
            page(
                "old",
                "2026-08-10T00:00:00.000Z",
                "https://www.linkedin.com/comm/jobs/view/4429171647/?tracking=old",
                "Company: Old Name | Role: Software Engineer",
            ),
            page(
                "new",
                "2026-08-11T00:00:00.000Z",
                "https://www.linkedin.com/jobs/view/4429171647/",
                "Company: New Name | Role: Senior Software Engineer",
            ),
        ]

        self.assertEqual(job_scan.duplicate_page_ids_to_archive(pages), ["old"])


class ITviecParsingTests(unittest.TestCase):
    def test_matches_url_when_text_title_contains_double_encoded_html_entity(self):
        body = (
            "Job 1: AI Software Engineer (Python/Go/C/C++ &amp;amp; AI Agents)\n"
            "Employer: MB Bank\n"
            "Salary: You'll love it\n"
        )
        tracking_url = "https://links.itviec.com/ls/click?upn=example"
        email_html = (
            f'<a class="text-decoration-none" href="{tracking_url}">'
            "<span class='job-title ifs-16'>"
            "AI Software Engineer (Python/Go/C/C++ &amp; AI Agents)"
            "</span></a>"
        )

        with tempfile.NamedTemporaryFile("w", suffix=".eml") as email_file:
            email_file.write(email_html)
            email_file.flush()
            jobs = job_scan.parse_itviec_alert(body, email_file.name)

        self.assertEqual(jobs[0]["url"], tracking_url)

    def test_assigns_distinct_links_when_one_job_title_contains_another(self):
        body = (
            "Job 1: Middle/Senior DevOps Engineer (Python, Linux, English)\n"
            "Employer: Recruitment Company\n"
            "Salary: You'll love it\n"
            "Job 2: Senior Devops Engineer\n"
            "Employer: Accenture\n"
            "Salary: You'll love it\n"
        )
        first_url = "https://links.itviec.com/ls/click?upn=first-example"
        second_url = "https://links.itviec.com/ls/click?upn=second-example"
        email_html = (
            f'<a class="text-decoration-none" href="{first_url}">'
            "<span class='job-title ifs-16'>"
            "Middle/Senior DevOps Engineer (Python, Linux, English)"
            "</span></a>"
            f'<a class="text-decoration-none" href="{second_url}">'
            "<span class='job-title ifs-16'>Senior Devops Engineer</span></a>"
        )

        with tempfile.NamedTemporaryFile("w", suffix=".eml") as email_file:
            email_file.write(email_html)
            email_file.flush()
            jobs = job_scan.parse_itviec_alert(body, email_file.name)

        self.assertEqual([job["url"] for job in jobs], [first_url, second_url])

    def test_reserves_later_exact_link_before_earlier_containment_fallback(self):
        body = (
            "Job 1: Senior Devops Engineer\n"
            "Employer: Accenture\n"
            "Salary: You'll love it\n"
            "Job 2: Middle/Senior DevOps Engineer (Python, Linux, English)\n"
            "Employer: Recruitment Company\n"
            "Salary: You'll love it\n"
        )
        short_url = "https://links.itviec.com/ls/click?upn=short-example"
        exact_url = "https://links.itviec.com/ls/click?upn=exact-example"
        email_html = (
            f'<a class="text-decoration-none" href="{exact_url}">'
            "<span class='job-title ifs-16'>"
            "Middle/Senior DevOps Engineer (Python, Linux, English)"
            "</span></a>"
            f'<a class="text-decoration-none" href="{short_url}">'
            "<span class='job-title ifs-16'>"
            "Senior Devops Engineer - Cloud Infrastructure Platform Kubernetes Team"
            "</span></a>"
        )

        with tempfile.NamedTemporaryFile("w", suffix=".eml") as email_file:
            email_file.write(email_html)
            email_file.flush()
            jobs = job_scan.parse_itviec_alert(body, email_file.name)

        self.assertEqual([job["url"] for job in jobs], [short_url, exact_url])
    def test_extracts_url_from_base64_mime_html(self):
        tracking_url = "https://links.itviec.com/ls/click?upn=base64-example"
        email_html = (
            f'<a class="text-decoration-none" href="{tracking_url}">'
            "<span class='job-title ifs-16'>Senior Cloud DevOps Engineer – ID9463</span>"
            "</a>"
        )
        encoded = base64.b64encode(email_html.encode()).decode()
        eml = (
            "MIME-Version: 1.0\n"
            "Content-Type: text/html; charset=utf-8\n"
            "Content-Transfer-Encoding: base64\n\n"
            f"{encoded}\n"
        )

        with tempfile.NamedTemporaryFile("w", suffix=".eml") as email_file:
            email_file.write(eml)
            email_file.flush()
            links = job_scan._extract_itviec_urls_from_eml(email_file.name)

        self.assertEqual(links, [{
            "title": "Senior Cloud DevOps Engineer – ID9463",
            "url": tracking_url,
        }])


class ITviecEnrichmentTests(unittest.TestCase):
    def detail(self, availability="accepting"):
        return {
            "job_id": "fresher-junior-ai-engineer-example-0022",
            "availability": availability,
            "accepting_applications": availability == "accepting",
            "status_reason": "jobposting_apply_action",
            "title": "Fresher/Junior AI Engineer Grit, Logic",
            "company": "Example AI",
            "location": "Ho Chi Minh City, VN",
            "listed": "2026-08-15",
            "criteria": {
                "job_type": "FULL_TIME",
                "valid_through": "2026-09-19",
                "salary": "500 - 2,000 USD",
                "skills": "Python, AI",
            },
            "links": {
                "listing": "https://itviec.com/it-jobs/fresher-junior-ai-engineer-example-0022",
                "apply": "https://itviec.com/job/example/apply",
            },
            "description": "### Job Description\n\nBuild reliable AI systems.",
        }

    def job(self):
        return {
            "role": "[Fresher/Junior] AI Engineer (Grit, Logic)",
            "company": "Example AI",
            "location": "HCMC",
            "url": "https://links.itviec.com/ls/click?upn=example",
            "source": "ITviec",
            "salary": "You'll love it",
        }

    def test_parses_identity_verified_itviec_detail(self):
        detail = job_scan.parse_opencli_itviec_detail(
            self.job(), json.dumps([self.detail()])
        )
        self.assertEqual(detail["availability"], "accepting")
        self.assertEqual(detail["company"], "Example AI")

    def test_rejects_active_itviec_identity_mismatch(self):
        detail = self.detail()
        detail["company"] = "Different Company"
        with self.assertRaisesRegex(ValueError, "company mismatch"):
            job_scan.parse_opencli_itviec_detail(self.job(), json.dumps([detail]))

    def test_accepts_itviec_jsonld_accent_loss_and_suffix_truncation(self):
        job = self.job()
        job["role"] = "[HN] 02 Security Engineer / Kỹ sư bảo mật"
        detail = self.detail()
        detail["title"] = "HN 02 Security Engineer / Ky su bao mat"

        parsed = job_scan.parse_opencli_itviec_detail(job, json.dumps([detail]))
        self.assertEqual(parsed["title"], detail["title"])

    def test_collects_itviec_detail_through_opencli(self):
        commands = []

        def fake_runner(command, timeout):
            commands.append((command, timeout))
            return json.dumps([self.detail()])

        detail = job_scan.collect_itviec_detail(self.job(), command_runner=fake_runner)
        self.assertEqual(detail["job_id"], "fresher-junior-ai-engineer-example-0022")
        self.assertEqual(commands[0][0][:3], ["opencli", "itviec", "job-public-detail"])

    def test_closed_itviec_job_builds_description_and_no_accept_status(self):
        enriched, body = job_scan.apply_itviec_detail(self.job(), self.detail("closed"))
        self.assertEqual(enriched["status"], "No Accept Apply")
        self.assertEqual(
            enriched["url"],
            "https://itviec.com/it-jobs/fresher-junior-ai-engineer-example-0022",
        )
        self.assertEqual(enriched["salary"], "500 - 2,000 USD")
        self.assertIn("**Application status:** closed", body)
        self.assertIn("Build reliable AI systems.", body)

    def test_writes_itviec_job_markdown_and_index(self):
        enriched, _ = job_scan.apply_itviec_detail(self.job(), self.detail())
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            path = job_scan.write_itviec_job_markdown(enriched, output_dir, "page-id")
            content = path.read_text(encoding="utf-8")
            index_path = job_scan.update_itviec_jobs_index(output_dir)
            index_content = index_path.read_text(encoding="utf-8")

        self.assertIn('itviec_job_id: "fresher-junior-ai-engineer-example-0022"', content)
        self.assertNotIn("[", path.name)
        self.assertNotIn("]", path.name)
        self.assertIn("## Job description", content)
        self.assertIn("job_count: 1", index_content)
        self.assertIn(f"[[{path.stem}]]", index_content)


class LinkedInEnrichmentTests(unittest.TestCase):
    def test_parses_identity_verified_opencli_job_detail(self):
        output = json.dumps([{
            "job_id": "4429171647",
            "availability": "closed",
            "accepting_applications": False,
            "status_reason": "linkedin_no_longer_accepting",
            "title": "Software Engineer",
            "company": "The Flex",
            "location": "Vietnam",
            "listed": "2 months ago",
            "applicants": "Over 200 applicants",
            "criteria": {"job_type": "Full-time", "seniority_level": "Entry level"},
            "links": {"listing": "https://www.linkedin.com/jobs/view/4429171647/"},
            "description": "Build reliable systems.",
        }])

        detail = job_scan.parse_opencli_linkedin_detail(
            "https://www.linkedin.com/comm/jobs/view/4429171647/",
            output,
        )

        self.assertEqual(detail["job_id"], "4429171647")
        self.assertEqual(detail["availability"], "closed")

    def test_rejects_opencli_job_detail_for_a_different_job_id(self):
        output = json.dumps([{"job_id": "9999999999", "availability": "accepting"}])

        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            job_scan.parse_opencli_linkedin_detail(
                "https://www.linkedin.com/jobs/view/4429171647/",
                output,
            )

    def test_closed_linkedin_job_builds_description_and_no_accept_status(self):
        job = {
            "role": "Software Engineer",
            "company": "The Flex",
            "location": "Vietnam",
            "url": "https://www.linkedin.com/comm/jobs/view/4429171647/",
            "source": "LinkedIn",
        }
        detail = {
            "job_id": "4429171647",
            "availability": "closed",
            "accepting_applications": False,
            "title": "Software Engineer",
            "company": "The Flex",
            "location": "Vietnam",
            "listed": "2 months ago",
            "applicants": "Over 200 applicants",
            "criteria": {"job_type": "Full-time", "seniority_level": "Entry level"},
            "links": {"listing": "https://www.linkedin.com/jobs/view/4429171647/"},
            "description": "Build reliable systems.",
        }

        enriched, body = job_scan.apply_linkedin_detail(job, detail)

        self.assertEqual(enriched["status"], "No Accept Apply")
        self.assertEqual(enriched["url"], "https://www.linkedin.com/jobs/view/4429171647/")
        self.assertIn("**Application status:** closed", body)
        self.assertIn("Build reliable systems.", body)

    def test_collects_linkedin_detail_through_opencli(self):
        commands = []

        def fake_runner(command, timeout):
            commands.append((command, timeout))
            return json.dumps([{
                "job_id": "4429171647",
                "availability": "accepting",
                "title": "Software Engineer",
            }])

        detail = job_scan.collect_linkedin_detail(
            "https://www.linkedin.com/comm/jobs/view/4429171647/",
            command_runner=fake_runner,
        )

        self.assertEqual(detail["job_id"], "4429171647")
        self.assertEqual(
            commands[0][0][:3],
            ["opencli", "linkedin", "job-public-detail"],
        )

    def test_writes_linkedin_job_markdown_to_obsidian_folder(self):
        job, _ = job_scan.apply_linkedin_detail(
            {
                "role": "Software Engineer",
                "company": "The Flex",
                "location": "Vietnam",
                "url": "https://www.linkedin.com/comm/jobs/view/4429171647/",
                "source": "LinkedIn",
            },
            {
                "job_id": "4429171647",
                "availability": "accepting",
                "accepting_applications": True,
                "title": "Software Engineer",
                "company": "The Flex",
                "location": "Vietnam",
                "listed": "2 months ago",
                "applicants": "Over 200 applicants",
                "criteria": {"job_type": "Full-time"},
                "links": {"listing": "https://www.linkedin.com/jobs/view/4429171647/"},
                "description": "Build reliable systems.",
            },
        )

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            path = job_scan.write_linkedin_job_markdown(job, output_dir)
            content = path.read_text(encoding="utf-8")
            index_path = job_scan.update_linkedin_jobs_index(output_dir)
            index_content = index_path.read_text(encoding="utf-8")

        self.assertTrue(path.name.endswith("4429171647.md"))
        self.assertIn('linkedin_job_id: "4429171647"', content)
        self.assertIn("## Job description", content)
        self.assertIn("Build reliable systems.", content)
        self.assertIn("job_count: 1", index_content)
        self.assertIn(f"[[{path.stem}]]", index_content)

    def test_notion_page_uses_collected_linkedin_status(self):
        captured = {}
        original = job_scan.notion_post

        def fake_notion_post(endpoint, payload, version=None):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {"id": "page-id"}

        job_scan.notion_post = fake_notion_post
        try:
            job_scan.create_notion_page({
                "role": "Software Engineer",
                "company": "The Flex",
                "location": "Vietnam",
                "url": "https://www.linkedin.com/jobs/view/4429171647/",
                "source": "LinkedIn",
                "status": "No Accept Apply",
            })
        finally:
            job_scan.notion_post = original

        self.assertEqual(
            captured["payload"]["properties"]["Status"]["select"]["name"],
            "No Accept Apply",
        )


class ScannerMainTests(unittest.TestCase):
    def test_rechecks_canonical_identity_after_itviec_enrichment(self):
        tracking_url = "https://links.itviec.com/ls/click?upn=example"
        canonical_url = "https://itviec.com/it-jobs/software-engineer-example-1234"
        raw_job = {
            "role": "Software Engineer",
            "company": "Example",
            "location": "",
            "url": tracking_url,
            "source": "ITviec",
            "salary": "You'll love it",
        }
        detail = {
            "job_id": "software-engineer-example-1234",
            "availability": "accepting",
            "accepting_applications": True,
            "title": "Software Engineer",
            "company": "Example",
            "location": "Ho Chi Minh City, VN",
            "criteria": {"salary": "You'll love it"},
            "links": {"listing": canonical_url},
            "description": "Build reliable systems.",
        }
        created_jobs = []

        def fake_create(job, dry_run=False, body_md=""):
            created_jobs.append(job.copy())
            return "new-page-id"

        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "last-id.txt"
            patches = [
                mock.patch.object(job_scan, "STATE_FILE", state_file),
                mock.patch.object(job_scan.sys, "argv", ["job-scan.py"]),
                mock.patch.object(job_scan, "get_existing_deduplication_keys", return_value=({canonical_url}, set())),
                mock.patch.object(job_scan, "list_new_emails", return_value=[{
                    "id": 4195,
                    "from": "itviec+jobrobot+1@itviec.com",
                    "subject": "Daily jobs",
                }]),
                mock.patch.object(job_scan, "read_email", return_value="email body"),
                mock.patch.object(job_scan, "read_email_raw", return_value=None),
                mock.patch.object(job_scan, "parse_email", return_value=[raw_job]),
                mock.patch.object(job_scan, "collect_itviec_detail", return_value=detail),
                mock.patch.object(job_scan, "write_itviec_job_markdown", return_value=Path(directory) / "job.md"),
                mock.patch.object(job_scan, "update_itviec_jobs_index", return_value=Path(directory) / "index.md"),
                mock.patch.object(job_scan, "create_notion_page", side_effect=fake_create),
            ]
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = job_scan.main()

            self.assertEqual(state_file.read_text(encoding="utf-8"), "4195")

        self.assertEqual(result, 0)
        self.assertEqual(created_jobs, [])

    def test_second_enriched_copy_is_skipped_after_first_create(self):
        canonical_url = "https://itviec.com/it-jobs/software-engineer-example-1234"
        raw_jobs = [{
            "role": "Software Engineer",
            "company": "Example",
            "location": "",
            "url": f"https://links.itviec.com/ls/click?upn=example-{index}",
            "source": "ITviec",
            "salary": "You'll love it",
        } for index in range(2)]
        detail = {
            "job_id": "software-engineer-example-1234",
            "availability": "accepting",
            "accepting_applications": True,
            "title": "Software Engineer",
            "company": "Example",
            "location": "Ho Chi Minh City, VN",
            "criteria": {"salary": "You'll love it"},
            "links": {"listing": canonical_url},
            "description": "Build reliable systems.",
        }
        created_jobs = []

        def fake_create(job, dry_run=False, body_md=""):
            created_jobs.append(job.copy())
            return f"page-{len(created_jobs)}"

        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "last-id.txt"
            patches = [
                mock.patch.object(job_scan, "STATE_FILE", state_file),
                mock.patch.object(job_scan.sys, "argv", ["job-scan.py"]),
                mock.patch.object(job_scan, "get_existing_deduplication_keys", return_value=(set(), set())),
                mock.patch.object(job_scan, "list_new_emails", return_value=[{
                    "id": 4195,
                    "from": "itviec+jobrobot+1@itviec.com",
                    "subject": "Daily jobs",
                }]),
                mock.patch.object(job_scan, "read_email", return_value="email body"),
                mock.patch.object(job_scan, "read_email_raw", return_value=None),
                mock.patch.object(job_scan, "parse_email", return_value=raw_jobs),
                mock.patch.object(job_scan, "collect_itviec_detail", return_value=detail),
                mock.patch.object(job_scan, "write_itviec_job_markdown", return_value=Path(directory) / "job.md"),
                mock.patch.object(job_scan, "update_itviec_jobs_index", return_value=Path(directory) / "index.md"),
                mock.patch.object(job_scan, "create_notion_page", side_effect=fake_create),
            ]
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = job_scan.main()

            self.assertEqual(state_file.read_text(encoding="utf-8"), "4195")

        self.assertEqual(result, 0)
        self.assertEqual(len(created_jobs), 1)
        self.assertEqual(created_jobs[0]["url"], canonical_url)

    def test_note_validation_error_is_recorded_without_advancing_checkpoint(self):
        raw_job = {
            "role": "Software Engineer",
            "company": "Example",
            "location": "",
            "url": "https://links.itviec.com/ls/click?upn=example",
            "source": "ITviec",
            "salary": "You'll love it",
        }
        detail = {
            "job_id": "software-engineer-example-1234",
            "availability": "accepting",
            "accepting_applications": True,
            "title": "Software Engineer",
            "company": "Example",
            "location": "Ho Chi Minh City, VN",
            "criteria": {"salary": "You'll love it"},
            "links": {"listing": "https://itviec.com/it-jobs/software-engineer-example-1234"},
            "description": "Build reliable systems.",
        }
        created_jobs = []

        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "last-id.txt"
            patches = [
                mock.patch.object(job_scan, "STATE_FILE", state_file),
                mock.patch.object(job_scan.sys, "argv", ["job-scan.py"]),
                mock.patch.object(job_scan, "get_existing_deduplication_keys", return_value=(set(), set())),
                mock.patch.object(job_scan, "list_new_emails", return_value=[{
                    "id": 4195,
                    "from": "itviec+jobrobot+1@itviec.com",
                    "subject": "Daily jobs",
                }]),
                mock.patch.object(job_scan, "read_email", return_value="email body"),
                mock.patch.object(job_scan, "read_email_raw", return_value=None),
                mock.patch.object(job_scan, "parse_email", return_value=[raw_job]),
                mock.patch.object(job_scan, "collect_itviec_detail", return_value=detail),
                mock.patch.object(job_scan, "write_itviec_job_markdown", side_effect=ValueError("missing job_id")),
                mock.patch.object(job_scan, "create_notion_page", side_effect=lambda job, **kwargs: created_jobs.append(job)),
            ]
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = job_scan.main()

            self.assertFalse(state_file.exists())

        self.assertEqual(result, 1)
        self.assertEqual(created_jobs, [])

    def test_dry_run_skips_second_copy_after_simulated_create(self):
        canonical_url = "https://itviec.com/it-jobs/software-engineer-example-1234"
        raw_jobs = [{
            "role": "Software Engineer",
            "company": "Example",
            "location": "",
            "url": f"https://links.itviec.com/ls/click?upn=example-{index}",
            "source": "ITviec",
            "salary": "You'll love it",
        } for index in range(2)]
        detail = {
            "job_id": "software-engineer-example-1234",
            "availability": "accepting",
            "accepting_applications": True,
            "title": "Software Engineer",
            "company": "Example",
            "location": "Ho Chi Minh City, VN",
            "criteria": {"salary": "You'll love it"},
            "links": {"listing": canonical_url},
            "description": "Build reliable systems.",
        }
        simulated_creates = []

        def fake_create(job, dry_run=False, body_md=""):
            self.assertTrue(dry_run)
            simulated_creates.append(job.copy())
            return None

        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "last-id.txt"
            patches = [
                mock.patch.object(job_scan, "STATE_FILE", state_file),
                mock.patch.object(job_scan.sys, "argv", ["job-scan.py", "--dry-run"]),
                mock.patch.object(job_scan, "get_existing_deduplication_keys", return_value=(set(), set())),
                mock.patch.object(job_scan, "list_new_emails", return_value=[{
                    "id": 4195,
                    "from": "itviec+jobrobot+1@itviec.com",
                    "subject": "Daily jobs",
                }]),
                mock.patch.object(job_scan, "read_email", return_value="email body"),
                mock.patch.object(job_scan, "read_email_raw", return_value=None),
                mock.patch.object(job_scan, "parse_email", return_value=raw_jobs),
                mock.patch.object(job_scan, "collect_itviec_detail", return_value=detail),
                mock.patch.object(job_scan, "create_notion_page", side_effect=fake_create),
            ]
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = job_scan.main()

            self.assertFalse(state_file.exists())

        self.assertEqual(result, 0)
        self.assertEqual(len(simulated_creates), 1)


class TelegramFormattingTests(unittest.TestCase):
    def test_formats_new_job_as_telegram_card(self):
        output = job_scan.format_telegram_update(
            [{
                "role": "Senior Backend Engineer",
                "company": "Example *Labs*",
                "location": "Singapore",
                "url": "https://example.com/jobs/42",
                "source": "LinkedIn",
                "salary": "$8k–$10k",
            }],
            total_jobs=3,
            skipped=2,
            timestamp=datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc),
        )

        self.assertIn("📦 **<backend engineer | LinkedIn | new> (#1)**", output)
        self.assertIn("💯 **Senior Backend Engineer**", output)
        self.assertIn("🏢 Example \\*Labs\\*", output)
        self.assertIn("📍 Singapore", output)
        self.assertIn("🗓 22-08-2026 12:30:00", output)
        self.assertIn("[Open on LinkedIn](https://example.com/jobs/42)", output)
        self.assertIn("💰 $8k–$10k", output)

    def test_formats_empty_daily_update(self):
        output = job_scan.format_telegram_update([], total_jobs=4, skipped=4)
        self.assertIn("No new jobs today.", output)
        self.assertIn("4 parsed · 4 duplicates", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
