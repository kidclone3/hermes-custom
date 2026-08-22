import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

MANIFEST = Path("/home/delus/.hermes/cache/linkedin-jobs-manifest.json")
DETAILS = Path("/home/delus/.hermes/cache/linkedin-job-details-cache.json")
RESULTS = Path("/home/delus/.hermes/cache/linkedin-job-enrichment-results.jsonl")
BACKUP = Path("/home/delus/.hermes/cache/flat-linkedin-notion-backup.json")
HEADING = "## LinkedIn Job Details"
TOKEN = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_API_TOKEN")

if not TOKEN:
    raise SystemExit("NOTION_API_KEY/NOTION_API_TOKEN is not set")


def notion_request(url, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    for attempt in range(5):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Notion-Version", "2025-09-03")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < 4:
                time.sleep(max(int(error.headers.get("Retry-After", "1")), 1))
                continue
            body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Notion HTTP {error.code}: {body[:800]}") from error


def job_id(url):
    match = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", url or "")
    if not match:
        raise ValueError(f"Unsupported LinkedIn URL: {url}")
    return match.group(1)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def build_section(job, detail):
    criteria = detail.get("criteria") or {}
    links = detail.get("links") or {}
    canonical = links.get("listing") or f"https://www.linkedin.com/jobs/view/{detail['job_id']}/"
    lines = [HEADING, ""]
    for label, value in (
        ("Application status", detail.get("availability")),
        ("Company", detail.get("company") or job.get("company")),
        ("Location", detail.get("location") or job.get("location")),
        ("Employment type", criteria.get("job_type")),
        ("Seniority level", criteria.get("seniority_level")),
        ("Job function", criteria.get("job_function")),
        ("Industries", criteria.get("industries")),
        ("Applicants", detail.get("applicants")),
        ("Listed", detail.get("listed")),
    ):
        if clean(value):
            lines.append(f"- **{label}:** {clean(value)}")
    lines.append(f"- **LinkedIn listing:** {canonical}")
    if links.get("company"):
        lines.append(f"- **Company page:** {links['company']}")
    description = str(detail.get("description") or "").strip()
    lines.extend(["", "### Job Description", "", description or "Description unavailable."])
    return "\n".join(lines).rstrip() + "\n"


def target_pages():
    latest = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        latest[record.get("page_id")] = record
    jobs = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return jobs, latest


def description_breaks(markdown):
    if "### Job Description" not in markdown:
        return -1
    description = markdown.split("### Job Description", 1)[1].strip()
    return description.count("\n\n")


def description_content_blocks(page_id):
    results = []
    cursor = None
    while True:
        endpoint = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            endpoint += f"&start_cursor={cursor}"
        data = notion_request(endpoint)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    in_description = False
    count = 0
    for block in results:
        block_type = block.get("type")
        payload = block.get(block_type, {})
        text = "".join(item.get("plain_text", "") for item in payload.get("rich_text", []))
        if block_type == "heading_3" and text.strip() == "Job Description":
            in_description = True
            continue
        if in_description and block_type in {
            "paragraph", "bulleted_list_item", "numbered_list_item", "quote",
            "callout", "heading_1", "heading_2", "heading_3",
        } and text.strip():
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--page-id")
    args = parser.parse_args()

    details = json.loads(DETAILS.read_text(encoding="utf-8"))
    jobs, latest = target_pages()
    if args.page_id:
        targets = [job for job in jobs if job["page_id"].replace("-", "") == args.page_id.replace("-", "")]
    elif args.all:
        targets = jobs
    else:
        targets = [job for job in jobs if latest.get(job["page_id"], {}).get("status") == "already_enriched"]
    backup = json.loads(BACKUP.read_text(encoding="utf-8")) if BACKUP.exists() else {}
    summary = {"targets": len(targets), "flat": 0, "repairable": 0, "updated": 0, "errors": 0}

    for job in targets:
        page_id = job["page_id"]
        url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
        detail = details[job_id(job["job_url"])]
        current_blocks = description_content_blocks(page_id)
        source_breaks = str(detail.get("description") or "").count("\n\n")
        current = ""
        current_breaks = -1
        description_chars = len(str(detail.get("description") or "").strip())
        is_flat = current_blocks <= 1 and source_breaks > 1 and description_chars > 500
        if is_flat:
            current = notion_request(url).get("markdown", "")
            current_breaks = description_breaks(current)
            backup.setdefault(page_id, current)
        repairable = is_flat and source_breaks > 1
        summary["flat"] += int(is_flat)
        summary["repairable"] += int(repairable)
        record = {
            "page_id": page_id,
            "name": job.get("name"),
            "current_breaks": current_breaks,
            "current_content_blocks": current_blocks,
            "source_breaks": source_breaks,
            "description_chars": description_chars,
            "repairable": repairable,
        }
        if args.apply and repairable:
            try:
                prefix = current.split(HEADING, 1)[0].rstrip()
                section = build_section(job, detail)
                new_markdown = f"{prefix}\n\n{section}" if prefix else section
                notion_request(
                    url,
                    method="PATCH",
                    payload={"type": "replace_content", "replace_content": {"new_str": new_markdown}},
                )
                verified_blocks = description_content_blocks(page_id)
                if verified_blocks <= 1:
                    raise RuntimeError(f"read-back still flat ({verified_blocks} content blocks)")
                record["verified_content_blocks"] = verified_blocks
                record["updated"] = True
                summary["updated"] += 1
            except Exception as error:
                record["error"] = str(error)
                summary["errors"] += 1
        print(json.dumps(record, ensure_ascii=False))

    BACKUP.write_text(json.dumps(backup, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    raise SystemExit(1 if summary["errors"] else 0)


if __name__ == "__main__":
    main()
