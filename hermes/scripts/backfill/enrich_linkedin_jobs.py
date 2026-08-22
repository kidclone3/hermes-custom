import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MANIFEST = Path("/home/delus/.hermes/cache/linkedin-jobs-manifest.json")
RESULTS = Path("/home/delus/.hermes/cache/linkedin-job-enrichment-results.jsonl")
DETAILS_CACHE = Path("/home/delus/.hermes/cache/linkedin-job-details-cache.json")
HEADING = "## LinkedIn Job Details"
TOKEN = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_API_TOKEN")
DETAILS = json.loads(DETAILS_CACHE.read_text(encoding="utf-8")) if DETAILS_CACHE.exists() else {}


def notion_request(url, method="GET", payload=None, attempts=5):
    if not TOKEN:
        raise RuntimeError("NOTION_API_KEY/NOTION_API_TOKEN is not set")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Notion-Version", "2025-09-03")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt + 1 < attempts:
                delay = int(exc.headers.get("Retry-After", "2"))
                time.sleep(max(delay, 1))
                continue
            raise RuntimeError(f"Notion HTTP {exc.code}: {body[:1000]}") from exc


def linkedin_url(url):
    match = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", url or "")
    if not match:
        raise ValueError(f"Unsupported LinkedIn job URL: {url}")
    return f"https://www.linkedin.com/jobs/view/{match.group(1)}/"


def fetch_job(url, attempts=2):
    canonical = linkedin_url(url)
    job_id = canonical.rstrip("/").rsplit("/", 1)[-1]
    if job_id in DETAILS:
        return canonical, DETAILS[job_id]
    last_error = ""
    for attempt in range(attempts):
        try:
            proc = subprocess.run(
                ["opencli", "linkedin", "job-public-detail", canonical, "--format", "json"],
                text=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            last_error = "OpenCLI timed out"
            if attempt + 1 < attempts:
                time.sleep(5)
                continue
            break
        output = proc.stdout.strip()
        if proc.returncode == 0:
            try:
                parsed = json.loads(output)
                detail = parsed[0] if isinstance(parsed, list) else parsed
                if not isinstance(detail, dict):
                    raise ValueError("response is not an object")
                if not detail.get("title") and detail.get("availability") != "unavailable":
                    raise ValueError("response has no job title")
                return canonical, detail
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = f"Invalid OpenCLI response: {exc}; output={output[:800]}"
        else:
            last_error = (output or proc.stderr.strip() or f"exit {proc.returncode}")[:1500]
        if attempt + 1 < attempts:
            if any(marker in last_error.lower() for marker in ("429", "rate limit", "too many")):
                time.sleep(60)
            else:
                time.sleep(5)
    raise RuntimeError(last_error)


def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def build_markdown(job, detail, canonical_url):
    lines = [HEADING, ""]
    criteria = detail.get("criteria") or {}
    links = detail.get("links") or {}
    fields = [
        ("Application status", detail.get("availability")),
        ("Company", detail.get("company") or job.get("company")),
        ("Location", detail.get("location") or job.get("location")),
        ("Employment type", criteria.get("job_type")),
        ("Seniority level", criteria.get("seniority_level")),
        ("Job function", criteria.get("job_function")),
        ("Industries", criteria.get("industries")),
        ("Applicants", detail.get("applicants")),
        ("Listed", detail.get("listed")),
    ]
    for label, value in fields:
        text = clean(value)
        if text:
            lines.append(f"- **{label}:** {text}")
    lines.append(f"- **LinkedIn listing:** {canonical_url}")
    apply_url = clean(links.get("apply"))
    if apply_url:
        lines.append(f"- **Application URL:** {apply_url}")
    company_url = clean(links.get("company"))
    if company_url:
        lines.append(f"- **Company page:** {company_url}")
    description = str(detail.get("description") or "").strip()
    lines.extend(["", "### Job Description", "", description or "Description unavailable."])
    return "\n".join(lines).rstrip() + "\n"


def append_result(record):
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()


def completed_pages():
    completed = set()
    if not RESULTS.exists():
        return completed
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("status_checked") and record.get("status") in {"updated", "already_enriched"}:
            completed.add(record.get("page_id"))
    return completed


def process(job, refresh=False):
    page_id = job["page_id"]
    canonical, detail = fetch_job(job["job_url"])
    availability = clean(detail.get("availability")) or "unknown"
    notion_status_before = job.get("status")
    notion_status_after = notion_status_before
    status_changed = False
    status_change_skipped = ""
    if availability in {"closed", "unavailable"}:
        if notion_status_before in {"Saved", "To Apply"}:
            notion_request(
                f"https://api.notion.com/v1/pages/{page_id}",
                method="PATCH",
                payload={"properties": {"Status": {"select": {"name": "No Accept Apply"}}}},
            )
            notion_status_after = "No Accept Apply"
            status_changed = notion_status_before != notion_status_after
        elif notion_status_before not in {"No Accept Apply", "Closed"}:
            status_change_skipped = "preserved_application_pipeline_status"
    markdown_url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
    current = notion_request(markdown_url).get("markdown", "")
    if HEADING in current and not refresh:
        return {
            "page_id": page_id,
            "name": job.get("name"),
            "status": "already_enriched",
            "job_url": canonical,
            "availability": availability,
            "notion_status_before": notion_status_before,
            "notion_status_after": notion_status_after,
            "status_changed": status_changed,
            "status_change_skipped": status_change_skipped,
            "status_checked": True,
        }
    section = build_markdown(job, detail, canonical)
    if current.strip():
        new_markdown = current.rstrip() + "\n\n---\n\n" + section
    else:
        new_markdown = section
    notion_request(
        markdown_url,
        method="PATCH",
        payload={"type": "replace_content", "replace_content": {"new_str": new_markdown}},
    )
    verify = notion_request(markdown_url).get("markdown", "")
    if HEADING not in verify:
        raise RuntimeError("Notion read-back verification failed")
    return {
        "page_id": page_id,
        "name": job.get("name"),
        "status": "updated",
        "job_url": canonical,
        "company": detail.get("company"),
        "location": detail.get("location"),
        "description_chars": len(clean(detail.get("description"))),
        "availability": availability,
        "notion_status_before": notion_status_before,
        "notion_status_after": notion_status_after,
        "status_changed": status_changed,
        "status_change_skipped": status_change_skipped,
        "status_checked": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    args = parser.parse_args()

    jobs = json.loads(MANIFEST.read_text(encoding="utf-8"))
    jobs = jobs[args.start :]
    if args.limit is not None:
        jobs = jobs[: args.limit]
    completed = completed_pages()
    counts = {"updated": 0, "already_enriched": 0, "skipped_completed": 0, "error": 0}

    for index, job in enumerate(jobs, start=1):
        if job["page_id"] in completed and not args.refresh:
            counts["skipped_completed"] += 1
            continue
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            record = process(job, refresh=args.refresh)
        except Exception as exc:
            record = {
                "page_id": job.get("page_id"),
                "name": job.get("name"),
                "job_url": job.get("job_url"),
                "status": "error",
                "error": str(exc)[:2000],
            }
        record["processed_at"] = started
        append_result(record)
        counts[record["status"]] = counts.get(record["status"], 0) + 1
        print(json.dumps({"progress": f"{index}/{len(jobs)}", **record}, ensure_ascii=False), flush=True)
        if index < len(jobs):
            time.sleep(max(args.delay, 0))

    print(json.dumps({"summary": counts, "results": str(RESULTS)}, ensure_ascii=False), flush=True)
    return 1 if counts.get("error", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
