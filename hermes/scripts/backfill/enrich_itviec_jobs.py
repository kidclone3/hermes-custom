#!/usr/bin/env python3
"""Backfill verified ITviec details into Notion and Obsidian.

Reads the preflight cache produced from the local OpenCLI ITviec adapter. Writes are
serialized and checkpointed. Re-running is idempotent unless --refresh is used.
"""

import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DETAILS_CACHE = Path("/home/delus/.hermes/cache/itviec-job-details-cache.json")
RESULTS = Path("/home/delus/.hermes/cache/itviec-job-enrichment-results.jsonl")
JOB_SCAN_PATH = Path("/home/delus/.hermes/scripts/job-scan.py")
HEADING = "## ITviec Job Details"
TOKEN = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_API_TOKEN")
LAST_REQUEST_AT = 0.0

spec = importlib.util.spec_from_file_location("job_scan", JOB_SCAN_PATH)
job_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job_scan)


def throttle():
    global LAST_REQUEST_AT
    wait = 0.36 - (time.monotonic() - LAST_REQUEST_AT)
    if wait > 0:
        time.sleep(wait)
    LAST_REQUEST_AT = time.monotonic()


def notion_request(url, method="GET", payload=None, attempts=6):
    if not TOKEN:
        raise RuntimeError("NOTION_API_KEY/NOTION_API_TOKEN is not set")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    for attempt in range(attempts):
        throttle()
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {TOKEN}")
        request.add_header("Notion-Version", "2025-09-03")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt + 1 < attempts:
                delay = int(exc.headers.get("Retry-After", "2"))
                time.sleep(max(delay, 1))
                continue
            if exc.code >= 500 and attempt + 1 < attempts:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Notion HTTP {exc.code}: {body[:1000]}") from exc
        except urllib.error.URLError as exc:
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Notion request failed: {exc}") from exc


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
        if record.get("verified") and record.get("status") in {"updated", "already_enriched"}:
            completed.add(record.get("page_id"))
    return completed


def property_value(properties, name):
    prop = properties.get(name) or {}
    kind = prop.get("type")
    value = prop.get(kind)
    if kind == "select":
        return (value or {}).get("name")
    if kind == "url":
        return value
    if kind == "rich_text":
        return "".join(item.get("plain_text", "") for item in (value or []))
    return value


def process(entry, refresh=False, dry_run=False):
    job = dict(entry["job"])
    detail = entry["detail"]
    page_id = job["page_id"]
    current_status = job.get("status") or "Saved"
    enriched, section = job_scan.apply_itviec_detail(job, detail)

    desired_status = current_status
    status_change_skipped = ""
    if detail.get("availability") in {"closed", "unavailable"}:
        if current_status in {"Saved", "To Apply"}:
            desired_status = "No Accept Apply"
        elif current_status not in {"No Accept Apply", "Closed"}:
            status_change_skipped = "preserved_application_pipeline_status"
    enriched["status"] = desired_status

    properties = {
        "Job URL": {"url": enriched["url"]},
    }
    if enriched.get("salary"):
        properties["Salary Range"] = {
            "rich_text": [{"text": {"content": enriched["salary"]}}]
        }
    normalized_location = job_scan.normalize_location(enriched.get("location", ""))
    if normalized_location:
        properties["Location"] = {"select": {"name": normalized_location}}
    if desired_status != current_status:
        properties["Status"] = {"select": {"name": desired_status}}

    markdown_url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
    current_markdown = notion_request(markdown_url).get("markdown", "")
    already_enriched = HEADING in current_markdown
    if already_enriched and not refresh:
        new_markdown = current_markdown
    elif current_markdown.strip():
        if HEADING in current_markdown:
            prefix = current_markdown.split(HEADING, 1)[0].rstrip().rstrip("-").rstrip()
            new_markdown = prefix + "\n\n---\n\n" + section
        else:
            new_markdown = current_markdown.rstrip() + "\n\n---\n\n" + section
    else:
        new_markdown = section

    if dry_run:
        return {
            "page_id": page_id,
            "name": enriched.get("role"),
            "status": "dry_run",
            "availability": detail.get("availability"),
            "notion_status_before": current_status,
            "notion_status_after": desired_status,
            "would_write_body": not already_enriched or refresh,
            "would_patch_properties": sorted(properties),
            "job_url": enriched.get("url"),
            "verified": False,
        }

    patched = notion_request(
        f"https://api.notion.com/v1/pages/{page_id}",
        method="PATCH",
        payload={"properties": properties},
    )
    patched_properties = patched.get("properties", {})
    if property_value(patched_properties, "Job URL") != enriched["url"]:
        raise RuntimeError("Notion Job URL read-back from PATCH response failed")
    if desired_status != current_status and property_value(patched_properties, "Status") != desired_status:
        raise RuntimeError("Notion Status read-back from PATCH response failed")

    if not already_enriched or refresh:
        notion_request(
            markdown_url,
            method="PATCH",
            payload={"type": "replace_content", "replace_content": {"new_str": new_markdown}},
        )
    verified_markdown = notion_request(markdown_url).get("markdown", "")
    if HEADING not in verified_markdown:
        raise RuntimeError("Notion Markdown read-back verification failed")

    note_path = job_scan.write_itviec_job_markdown(
        enriched,
        notion_page_id=page_id,
    )
    if not note_path.exists():
        raise RuntimeError("Obsidian note write verification failed")
    note_text = note_path.read_text(encoding="utf-8")
    if str(detail.get("job_id") or "") not in note_text or enriched["url"] not in note_text:
        raise RuntimeError("Obsidian note read-back verification failed")

    return {
        "page_id": page_id,
        "name": enriched.get("role"),
        "company": enriched.get("company"),
        "status": "already_enriched" if already_enriched and not refresh else "updated",
        "availability": detail.get("availability"),
        "notion_status_before": current_status,
        "notion_status_after": desired_status,
        "status_changed": desired_status != current_status,
        "status_change_skipped": status_change_skipped,
        "job_url": enriched.get("url"),
        "description_chars": len(str(detail.get("description") or "")),
        "note_path": str(note_path),
        "verified": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DETAILS_CACHE.exists():
        raise SystemExit(f"Missing preflight cache: {DETAILS_CACHE}")
    cache = json.loads(DETAILS_CACHE.read_text(encoding="utf-8"))
    entries = [cache[key] for key in sorted(cache)]
    entries = entries[args.start:]
    if args.limit is not None:
        entries = entries[:args.limit]
    completed = completed_pages()
    counts = {"updated": 0, "already_enriched": 0, "skipped_completed": 0, "dry_run": 0, "error": 0}

    for index, entry in enumerate(entries, start=1):
        page_id = entry["job"]["page_id"]
        if page_id in completed and not args.refresh and not args.dry_run:
            counts["skipped_completed"] += 1
            continue
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            record = process(entry, refresh=args.refresh, dry_run=args.dry_run)
        except Exception as exc:
            record = {
                "page_id": page_id,
                "name": entry["job"].get("role"),
                "status": "error",
                "error": str(exc)[:2000],
                "verified": False,
            }
        record["processed_at"] = started
        if not args.dry_run:
            append_result(record)
        counts[record["status"]] = counts.get(record["status"], 0) + 1
        print(json.dumps({"progress": f"{index}/{len(entries)}", **record}, ensure_ascii=False), flush=True)

    if not args.dry_run:
        index_path = job_scan.update_itviec_jobs_index()
    else:
        index_path = None
    print(json.dumps({"summary": counts, "results": str(RESULTS), "index": str(index_path or "")}, ensure_ascii=False), flush=True)
    return 1 if counts.get("error", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
