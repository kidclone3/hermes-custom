#!/usr/bin/env python3
"""Daily scan: read new emails from Gmail Job folder, parse job listings, insert into Notion Job Tracking DB.

State file: ~/.hermes/state/job-scan-last-id.txt — stores last processed himalaya email ID.
Deduplication: checks Notion for existing entries by normalized Job URL and structured Notes before inserting.
Older structured duplicates can be archived with --prune-duplicates; the newest page is retained.

Usage:
    python3 job-scan.py                  # process new emails since last run
    python3 job-scan.py --all            # process ALL emails in Job folder (idempotent)
    python3 job-scan.py --dry-run        # show what would be inserted, don't insert
    python3 job-scan.py --prune-duplicates  # archive old structured duplicates, keep newest
"""

import html as html_mod
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path

STATE_FILE = Path.home() / ".hermes" / "state" / "job-scan-last-id.txt"
NOTION_DB_ID = "3abf57f2-0087-8191-a112-f1dc8d6a5ea4"  # database_id for page creation
NOTION_DS_ID = "3abf57f2-0087-817d-8dd0-000bcdac80ef"  # data_source_id for query
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_VERSION_PAGES = "2022-06-28"  # required for typed properties on page creation
NOTION_VERSION_QUERY = "2025-09-03"  # required for data source queries
HIMALAYA_FOLDER = "Job"
OBSIDIAN_LINKEDIN_DIR = Path(
    os.environ.get(
        "OBSIDIAN_LINKEDIN_JOBS_DIR",
        "/mnt/d/Obsidian/40 Resources/Job Tracking/LinkedIn Jobs",
    )
)
OBSIDIAN_ITVIEC_DIR = Path(
    os.environ.get(
        "OBSIDIAN_ITVIEC_JOBS_DIR",
        "/mnt/d/Obsidian/40 Resources/Job Tracking/ITviec Jobs",
    )
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd: list[str], timeout: int = 60) -> str:
    """Run a shell command, return stdout."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout


def notion_post(endpoint: str, payload: dict, version: str | None = None) -> dict:
    """POST to Notion API, return parsed JSON."""
    ver = version or NOTION_VERSION_PAGES
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": ver,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def notion_patch(endpoint: str, payload: dict, version: str | None = None) -> dict:
    """PATCH a Notion API resource and return parsed JSON."""
    ver = version or NOTION_VERSION_PAGES
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": ver,
            "Content-Type": "application/json",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def normalized_text(value: str) -> str:
    """Canonicalize source text without changing its stored representation."""
    value = str(value or "")
    previous = None
    while value != previous:
        previous, value = value, html_mod.unescape(value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def normalized_job_url(value: str) -> str:
    """Return a deduplication key without collapsing ITviec tracking links."""
    value = str(value or "").strip()
    if urllib.parse.urlsplit(value).hostname == "links.itviec.com":
        return value
    linkedin_match = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", value)
    if linkedin_match:
        return f"https://www.linkedin.com/jobs/view/{linkedin_match.group(1)}/"
    return re.sub(r"\?.*", "", value)


def linkedin_job_id(value: str) -> str:
    """Extract the stable numeric job ID from a LinkedIn job URL."""
    match = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", str(value or ""))
    if not match:
        raise ValueError(f"Unsupported LinkedIn job URL: {value}")
    return match.group(1)


def parse_opencli_linkedin_detail(job_url: str, output: str) -> dict:
    """Parse an OpenCLI job response and fail closed on an identity mismatch."""
    rows = json.loads(output)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("OpenCLI LinkedIn response must contain exactly one job row")
    detail = rows[0]
    expected_id = linkedin_job_id(job_url)
    if str(detail.get("job_id", "")) != expected_id:
        raise ValueError(
            f"OpenCLI LinkedIn identity mismatch: expected {expected_id}, "
            f"received {detail.get('job_id', 'missing')}"
        )
    return detail


def collect_linkedin_detail(job_url: str, command_runner=None) -> dict:
    """Collect one exact LinkedIn job through the verified OpenCLI adapter."""
    job_id = linkedin_job_id(job_url)
    canonical_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    command = [
        "opencli", "linkedin", "job-public-detail", canonical_url,
        "--format", "json",
    ]
    if command_runner is not None:
        output = command_runner(command, timeout=90)
    else:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            message = result.stdout.strip() or result.stderr.strip() or f"exit {result.returncode}"
            raise RuntimeError(f"OpenCLI LinkedIn collection failed: {message[:500]}")
        output = result.stdout
    return parse_opencli_linkedin_detail(job_url, output)


def _identity_text(value: str) -> str:
    """Normalize a source title/company for fail-closed cross-source checks."""
    value = unicodedata.normalize("NFKD", normalized_text(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[\W_]+", " ", value, flags=re.UNICODE).strip()


def _same_itviec_title(expected: str, observed: str) -> bool:
    """Allow ITviec JSON-LD punctuation/accent loss and known suffix truncation."""
    expected_tokens = _identity_text(expected).split()
    observed_tokens = _identity_text(observed).split()
    if not expected_tokens or not observed_tokens:
        return False
    if expected_tokens == observed_tokens:
        return True
    common = len(set(expected_tokens) & set(observed_tokens))
    return min(len(set(expected_tokens)), len(set(observed_tokens))) >= 3 and (
        common / min(len(set(expected_tokens)), len(set(observed_tokens))) >= 0.8
    )


def parse_opencli_itviec_detail(job: dict, output: str) -> dict:
    """Parse one OpenCLI ITviec row and reject active identity mismatches."""
    rows = json.loads(output)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("OpenCLI ITviec response must contain exactly one job row")
    detail = rows[0]
    links = detail.get("links") or {}
    listing = str(links.get("listing") or "").strip()
    parsed = urllib.parse.urlsplit(listing)
    if parsed.hostname not in {"itviec.com", "www.itviec.com"} or not parsed.path.startswith("/it-jobs/"):
        raise ValueError("OpenCLI ITviec response does not contain a canonical listing URL")

    if detail.get("availability") not in {"closed", "unavailable"}:
        expected_title = job.get("role")
        observed_title = detail.get("title")
        if _identity_text(expected_title) and not _same_itviec_title(expected_title, observed_title):
            raise ValueError(
                f"OpenCLI ITviec title mismatch: expected {expected_title!r}, received {observed_title!r}"
            )
        expected_company = _identity_text(job.get("company"))
        observed_company = _identity_text(detail.get("company"))
        if expected_company and expected_company != observed_company:
            raise ValueError(
                "OpenCLI ITviec company mismatch: "
                f"expected {job.get('company')!r}, received {detail.get('company')!r}"
            )
    return detail


def collect_itviec_detail(job: dict, command_runner=None) -> dict:
    """Collect one ITviec listing through the local public OpenCLI adapter."""
    job_url = str(job.get("url") or "").strip()
    if not job_url:
        raise ValueError("ITviec collection requires a job URL")
    command = [
        "opencli", "itviec", "job-public-detail", job_url,
        "--format", "json",
    ]
    if command_runner is not None:
        output = command_runner(command, timeout=90)
    else:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            message = result.stdout.strip() or result.stderr.strip() or f"exit {result.returncode}"
            raise RuntimeError(f"OpenCLI ITviec collection failed: {message[:500]}")
        output = result.stdout
    return parse_opencli_itviec_detail(job, output)


def apply_linkedin_detail(job: dict, detail: dict) -> tuple[dict, str]:
    """Merge verified LinkedIn data into a parsed job and build its page body."""
    enriched = job.copy()
    criteria = detail.get("criteria") or {}
    links = detail.get("links") or {}
    enriched["role"] = str(detail.get("title") or job.get("role") or "LinkedIn Job").strip()
    enriched["company"] = str(detail.get("company") or job.get("company") or "Unknown company").strip()
    enriched["location"] = str(detail.get("location") or job.get("location") or "").strip()
    enriched["url"] = str(links.get("listing") or job.get("url") or "").strip()
    enriched["status"] = (
        "No Accept Apply"
        if detail.get("availability") in {"closed", "unavailable"}
        else "Saved"
    )
    enriched["linkedin_detail"] = detail

    lines = [
        "## LinkedIn Job Details",
        "",
        f"- **Application status:** {detail.get('availability') or 'unknown'}",
        f"- **Company:** {enriched['company']}",
    ]
    if enriched["location"]:
        lines.append(f"- **Location:** {enriched['location']}")
    for label, value in (
        ("Employment type", criteria.get("job_type")),
        ("Seniority level", criteria.get("seniority_level")),
        ("Job function", criteria.get("job_function")),
        ("Industries", criteria.get("industries")),
        ("Applicants", detail.get("applicants")),
        ("Listed", detail.get("listed")),
    ):
        if value:
            lines.append(f"- **{label}:** {str(value).strip()}")
    if enriched["url"]:
        lines.append(f"- **LinkedIn listing:** {enriched['url']}")
    if links.get("company"):
        lines.append(f"- **Company page:** {links['company']}")
    description = str(detail.get("description") or "").strip()
    lines.extend([
        "",
        "### Job Description",
        "",
        description or "The LinkedIn listing is unavailable; no job description could be collected.",
    ])
    return enriched, "\n".join(lines).rstrip() + "\n"


def apply_itviec_detail(job: dict, detail: dict) -> tuple[dict, str]:
    """Merge verified ITviec data into a parsed job and build its page body."""
    enriched = job.copy()
    criteria = detail.get("criteria") or {}
    links = detail.get("links") or {}
    # The email title/company preserve visible punctuation and Vietnamese accents
    # that ITviec's JSON-LD sometimes strips or truncates.
    enriched["role"] = str(job.get("role") or detail.get("title") or "ITviec Job").strip()
    enriched["company"] = str(job.get("company") or detail.get("company") or "Unknown company").strip()
    enriched["location"] = str(detail.get("location") or job.get("location") or "").strip()
    enriched["salary"] = str(criteria.get("salary") or job.get("salary") or "").strip()
    enriched["url"] = str(links.get("listing") or job.get("url") or "").strip()
    enriched["status"] = (
        "No Accept Apply"
        if detail.get("availability") in {"closed", "unavailable"}
        else "Saved"
    )
    enriched["itviec_detail"] = detail

    lines = [
        "## ITviec Job Details",
        "",
        f"- **Application status:** {detail.get('availability') or 'unknown'}",
        f"- **Company:** {enriched['company']}",
    ]
    if enriched["location"]:
        lines.append(f"- **Location:** {enriched['location']}")
    for label, value in (
        ("Employment type", criteria.get("job_type")),
        ("Date posted", detail.get("listed")),
        ("Valid through", criteria.get("valid_through")),
        ("Salary", enriched["salary"]),
        ("Skills", criteria.get("skills")),
        ("Experience", criteria.get("experience")),
    ):
        if value:
            lines.append(f"- **{label}:** {str(value).strip()}")
    if enriched["url"]:
        lines.append(f"- **ITviec listing:** {enriched['url']}")
    if links.get("apply"):
        lines.append(f"- **Application URL:** {links['apply']}")
    description = str(detail.get("description") or "").strip()
    lines.extend([
        "",
        "## Job Description",
        "",
        description or "The ITviec listing is unavailable; no job description could be collected.",
    ])
    return enriched, "\n".join(lines).rstrip() + "\n"


def _safe_job_filename(value: str, job_id: str) -> str:
    """Return a readable Windows-safe and Obsidian-safe Markdown filename."""
    # Square brackets are legal on Windows but break Obsidian wikilink syntax.
    name = re.sub(r'[<>:"/\\|?*\[\]\x00-\x1f]', '-', str(value or "LinkedIn Job"))
    name = re.sub(r"\s+", " ", name).strip(" .-")
    name = (name[:110].rstrip(" .-") or "LinkedIn Job")
    return f"{name} - {job_id}.md"


def write_linkedin_job_markdown(
    job: dict,
    output_dir: Path = OBSIDIAN_LINKEDIN_DIR,
    notion_page_id: str = "",
) -> Path:
    """Write an idempotent Obsidian note for one enriched LinkedIn job."""
    detail = job.get("linkedin_detail") or {}
    job_id = str(detail.get("job_id") or linkedin_job_id(job.get("url", "")))
    criteria = detail.get("criteria") or {}
    links = detail.get("links") or {}
    title = str(job.get("role") or detail.get("title") or "LinkedIn Job").strip()
    company = str(job.get("company") or detail.get("company") or "Unknown company").strip()
    location = str(job.get("location") or detail.get("location") or "").strip()
    listing = str(links.get("listing") or job.get("url") or "").strip()
    description = str(detail.get("description") or "").strip()
    if not description:
        description = "The LinkedIn listing is unavailable; no job description could be collected."
    notion_url = (
        f"https://www.notion.so/{notion_page_id.replace('-', '')}"
        if notion_page_id else ""
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / _safe_job_filename(f"{company} - {title}", job_id)
    for stale_path in output_dir.glob(f"* - {job_id}.md"):
        if stale_path != path:
            stale_path.unlink()
    yaml = lambda value: json.dumps(value if value is not None else "", ensure_ascii=False)
    content = [
        "---",
        f"type: {yaml('job')}",
        f"source: {yaml('LinkedIn')}",
        f"linkedin_job_id: {yaml(job_id)}",
        f"title: {yaml(title)}",
        f"company: {yaml(company)}",
        f"location: {yaml(location)}",
        f"availability: {yaml(detail.get('availability'))}",
        f"accepting_applications: {str(bool(detail.get('accepting_applications'))).lower()}",
        f"listed: {yaml(detail.get('listed'))}",
        f"applicants: {yaml(detail.get('applicants'))}",
        f"employment_type: {yaml(criteria.get('job_type'))}",
        f"seniority_level: {yaml(criteria.get('seniority_level'))}",
        f"job_function: {yaml(criteria.get('job_function'))}",
        f"industries: {yaml(criteria.get('industries'))}",
        f"job_url: {yaml(listing)}",
        f"company_url: {yaml(links.get('company'))}",
        f"notion_url: {yaml(notion_url)}",
        f"notion_status: {yaml(job.get('status', 'Saved'))}",
        f"collected: {yaml(date.today().isoformat())}",
        f"tags: {yaml(['job', 'linkedin'])}",
        "---",
        "",
        f"# {title}",
        "",
        f"**Company:** {company}",
        f"**Location:** {location or 'Not available'}",
        f"**LinkedIn availability:** {detail.get('availability') or 'unknown'}",
        f"**Notion status:** {job.get('status', 'Saved')}",
        "",
        "## Job metadata",
        "",
        f"- **Employment type:** {criteria.get('job_type') or 'Not available'}",
        f"- **Seniority level:** {criteria.get('seniority_level') or 'Not available'}",
        f"- **Job function:** {criteria.get('job_function') or 'Not available'}",
        f"- **Industries:** {criteria.get('industries') or 'Not available'}",
        f"- **Applicants:** {detail.get('applicants') or 'Not available'}",
        f"- **Listed:** {detail.get('listed') or 'Not available'}",
        f"- **LinkedIn listing:** {listing or 'Not available'}",
        "",
        "## Job description",
        "",
        description,
        "",
    ]
    if notion_url:
        content.extend(["## Tracking", "", f"- **Notion page:** {notion_url}", ""])
    path.write_text("\n".join(content), encoding="utf-8")
    return path


def _frontmatter_json_value(text: str, key: str):
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    if not match:
        return ""
    raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def update_linkedin_jobs_index(output_dir: Path = OBSIDIAN_LINKEDIN_DIR) -> Path:
    """Regenerate the Obsidian LinkedIn jobs index from current job notes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "LinkedIn Jobs.md"
    rows = []
    for path in output_dir.glob("*.md"):
        if path == index_path:
            continue
        text = path.read_text(encoding="utf-8")
        job_id = str(_frontmatter_json_value(text, "linkedin_job_id") or "")
        if not job_id:
            continue
        rows.append({
            "company": str(_frontmatter_json_value(text, "company") or "Unknown company"),
            "title": str(_frontmatter_json_value(text, "title") or "LinkedIn Job"),
            "availability": str(_frontmatter_json_value(text, "availability") or "unknown"),
            "status": str(_frontmatter_json_value(text, "notion_status") or "Saved"),
            "wikilink": path.stem,
        })
    counts = {}
    for row in rows:
        counts[row["availability"]] = counts.get(row["availability"], 0) + 1
    lines = [
        "---",
        'type: "job-index"',
        'source: "LinkedIn"',
        f'collected: "{date.today().isoformat()}"',
        f"job_count: {len(rows)}",
        "---",
        "",
        "# LinkedIn Jobs",
        "",
        f"Collected **{len(rows)}** LinkedIn job listings.",
        "",
        "## Availability",
        "",
    ]
    for availability in sorted(counts):
        lines.append(f"- **{availability}:** {counts[availability]}")
    lines.extend([
        "",
        "## Jobs",
        "",
        "| Company | Role | Availability | Notion status | Note |",
        "|---|---|---|---|---|",
    ])
    escape = lambda value: str(value).replace("|", "\\|").replace("\n", " ").strip()
    for row in sorted(rows, key=lambda item: (item["company"].casefold(), item["title"].casefold())):
        lines.append(
            f"| {escape(row['company'])} | {escape(row['title'])} | "
            f"{escape(row['availability'])} | {escape(row['status'])} | "
            f"[[{row['wikilink']}]] |"
        )
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path


def write_itviec_job_markdown(
    job: dict,
    output_dir: Path = OBSIDIAN_ITVIEC_DIR,
    notion_page_id: str = "",
) -> Path:
    """Write an idempotent Obsidian note for one enriched ITviec job."""
    detail = job.get("itviec_detail") or {}
    criteria = detail.get("criteria") or {}
    links = detail.get("links") or {}
    job_id = str(detail.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("ITviec detail is missing job_id")
    title = str(job.get("role") or detail.get("title") or "ITviec Job").strip()
    company = str(job.get("company") or detail.get("company") or "Unknown company").strip()
    location = str(job.get("location") or detail.get("location") or "").strip()
    listing = str(links.get("listing") or job.get("url") or "").strip()
    description = str(detail.get("description") or "").strip()
    if not description:
        description = "The ITviec listing is unavailable; no job description could be collected."
    notion_url = (
        f"https://www.notion.so/{notion_page_id.replace('-', '')}"
        if notion_page_id else ""
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / _safe_job_filename(f"{company} - {title}", job_id)
    for stale_path in output_dir.glob(f"* - {job_id}.md"):
        if stale_path != path:
            stale_path.unlink()
    yaml = lambda value: json.dumps(value if value is not None else "", ensure_ascii=False)
    content = [
        "---",
        f"type: {yaml('job')}",
        f"source: {yaml('ITviec')}",
        f"itviec_job_id: {yaml(job_id)}",
        f"title: {yaml(title)}",
        f"company: {yaml(company)}",
        f"location: {yaml(location)}",
        f"availability: {yaml(detail.get('availability'))}",
        f"accepting_applications: {str(bool(detail.get('accepting_applications'))).lower()}",
        f"date_posted: {yaml(detail.get('listed'))}",
        f"valid_through: {yaml(criteria.get('valid_through'))}",
        f"employment_type: {yaml(criteria.get('job_type'))}",
        f"salary: {yaml(criteria.get('salary') or job.get('salary'))}",
        f"skills: {yaml(criteria.get('skills'))}",
        f"job_url: {yaml(listing)}",
        f"apply_url: {yaml(links.get('apply'))}",
        f"notion_url: {yaml(notion_url)}",
        f"notion_status: {yaml(job.get('status', 'Saved'))}",
        f"collected: {yaml(date.today().isoformat())}",
        f"tags: {yaml(['job', 'itviec'])}",
        "---",
        "",
        f"# {title}",
        "",
        f"**Company:** {company}",
        f"**Location:** {location or 'Not available'}",
        f"**ITviec availability:** {detail.get('availability') or 'unknown'}",
        f"**Notion status:** {job.get('status', 'Saved')}",
        "",
        "## Job metadata",
        "",
        f"- **Employment type:** {criteria.get('job_type') or 'Not available'}",
        f"- **Date posted:** {detail.get('listed') or 'Not available'}",
        f"- **Valid through:** {criteria.get('valid_through') or 'Not available'}",
        f"- **Salary:** {criteria.get('salary') or job.get('salary') or 'Not available'}",
        f"- **Skills:** {criteria.get('skills') or 'Not available'}",
        f"- **ITviec listing:** {listing or 'Not available'}",
        "",
        "## Job description",
        "",
        description,
        "",
    ]
    if notion_url:
        content.extend(["## Tracking", "", f"- **Notion page:** {notion_url}", ""])
    path.write_text("\n".join(content), encoding="utf-8")
    return path


def update_itviec_jobs_index(output_dir: Path = OBSIDIAN_ITVIEC_DIR) -> Path:
    """Regenerate the Obsidian ITviec jobs index from current job notes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "ITviec Jobs.md"
    rows = []
    for path in output_dir.glob("*.md"):
        if path == index_path:
            continue
        text = path.read_text(encoding="utf-8")
        job_id = str(_frontmatter_json_value(text, "itviec_job_id") or "")
        if not job_id:
            continue
        rows.append({
            "company": str(_frontmatter_json_value(text, "company") or "Unknown company"),
            "title": str(_frontmatter_json_value(text, "title") or "ITviec Job"),
            "availability": str(_frontmatter_json_value(text, "availability") or "unknown"),
            "status": str(_frontmatter_json_value(text, "notion_status") or "Saved"),
            "wikilink": path.stem,
        })
    counts = {}
    for row in rows:
        counts[row["availability"]] = counts.get(row["availability"], 0) + 1
    lines = [
        "---",
        'type: "job-index"',
        'source: "ITviec"',
        f'collected: "{date.today().isoformat()}"',
        f"job_count: {len(rows)}",
        "---",
        "",
        "# ITviec Jobs",
        "",
        f"Collected **{len(rows)}** ITviec job listings.",
        "",
        "## Availability",
        "",
    ]
    for availability in sorted(counts):
        lines.append(f"- **{availability}:** {counts[availability]}")
    lines.extend([
        "",
        "## Jobs",
        "",
        "| Company | Role | Availability | Notion status | Note |",
        "|---|---|---|---|---|",
    ])
    escape = lambda value: str(value).replace("|", "\\|").replace("\n", " ").strip()
    for row in sorted(rows, key=lambda item: (item["company"].casefold(), item["title"].casefold())):
        lines.append(
            f"| {escape(row['company'])} | {escape(row['title'])} | "
            f"{escape(row['availability'])} | {escape(row['status'])} | "
            f"[[{row['wikilink']}]] |"
        )
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path


def job_fingerprint(job: dict) -> str | None:
    """Return a stable content key for a parsed job, or None when incomplete.

    URLs remain the preferred identity when available. This fallback is used for
    listings, particularly ITviec alerts, that do not expose a stable URL.
    """
    company = normalized_text(job.get("company", ""))
    role = normalized_text(job.get("role", ""))
    if not company or not role:
        return None
    return "\x1f".join((
        company,
        role,
        normalized_text(job.get("location", "")),
        normalized_text(job.get("salary", "")),
    ))


def duplicate_reason(
    job: dict,
    existing_urls: set[str],
    existing_fingerprints: set[str],
) -> str | None:
    """Return the matching identity type for a job, if it already exists."""
    url = str(job.get("url") or "").strip()
    if url:
        return "URL" if normalized_job_url(url) in existing_urls else None
    fingerprint = job_fingerprint(job)
    if fingerprint and fingerprint in existing_fingerprints:
        return "Notes"
    return None


def remember_job_identity(
    job: dict,
    existing_urls: set[str],
    existing_fingerprints: set[str],
) -> None:
    """Add the exact persisted identity keys for a real or simulated create."""
    stored_url = str(job.get("url") or "").strip()
    if stored_url:
        existing_urls.add(normalized_job_url(stored_url))
    stored_fingerprint = job_fingerprint(job)
    if stored_fingerprint:
        existing_fingerprints.add(stored_fingerprint)


def notes_fingerprint(notes: str) -> str | None:
    """Extract a job fingerprint from scanner-generated Notes.

    Unstructured notes are intentionally ignored: a generic note such as
    ``HCMC office`` is not a reliable job identity.
    """
    company_match = re.search(r"(?:^|\|)\s*Company:\s*(.*?)\s*\|\s*Role:", notes, re.DOTALL)
    role_match = re.search(r"\|\s*Role:\s*(.*?)(?=\s*\|\s*(?:Location|Salary):|$)", notes, re.DOTALL)
    if not company_match or not role_match:
        return None

    def optional_field(name: str) -> str:
        match = re.search(rf"\|\s*{name}:\s*(.*?)(?=\s*\|\s*(?:Location|Salary):|$)", notes, re.DOTALL)
        return match.group(1) if match else ""

    return job_fingerprint({
        "company": company_match.group(1),
        "role": role_match.group(1),
        "location": optional_field("Location"),
        "salary": optional_field("Salary"),
    })


def rich_text_value(prop: dict) -> str:
    """Return the plain-text value of a Notion rich-text property."""
    return "".join(item.get("plain_text", "") for item in prop.get("rich_text", []))


def duplicate_page_ids_to_archive(pages: list[dict]) -> list[str]:
    """Return older duplicates, preferring stable URL identity over Notes."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for page in pages:
        properties = page.get("properties", {})
        url = str(properties.get("Job URL", {}).get("url") or "").strip()
        if url:
            identity = ("url", normalized_job_url(url))
        else:
            notes = rich_text_value(properties.get("Notes", {}))
            fingerprint = notes_fingerprint(notes)
            if not fingerprint:
                continue
            identity = ("notes", fingerprint)
        groups.setdefault(identity, []).append(page)

    ids = []
    for group in groups.values():
        if len(group) > 1:
            ordered = sorted(group, key=lambda page: (page.get("created_time", ""), page.get("id", "")))
            ids.extend(page["id"] for page in ordered[:-1])
    return ids


def notion_get(endpoint: str) -> dict:
    """GET from Notion API."""
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{endpoint}",
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": NOTION_VERSION,
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ── Email Parsing ────────────────────────────────────────────────────────────

def list_new_emails(since_id: int | None = None) -> list[dict]:
    """List emails from Job folder, optionally only those with ID > since_id."""
    out = run(["himalaya", "envelope", "list", "--page-size", "100",
               "--folder", HIMALAYA_FOLDER, "--output", "json"])
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return _parse_table_output(out, since_id)

    emails = []
    for entry in data:
        eid = int(entry.get("id", 0))
        if since_id is not None and eid <= since_id:
            continue
        from_data = entry.get("from", "")
        if isinstance(from_data, dict):
            from_addr = from_data.get("addr", "") or from_data.get("name", "")
        else:
            from_addr = str(from_data)
        emails.append({"id": eid, "from": from_addr,
                       "subject": entry.get("subject", ""),
                       "date": entry.get("date", "")})
    return emails


def _parse_table_output(text: str, since_id: int | None = None) -> list[dict]:
    """Fallback: parse himalaya's table output."""
    emails = []
    for line in text.split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5 or not parts[1].isdigit():
            continue
        eid = int(parts[1])
        if since_id is not None and eid <= since_id:
            continue
        emails.append({"id": eid, "from": parts[3], "subject": parts[2],
                       "date": parts[4]})
    return emails


def read_email(eid: int) -> str:
    """Read plain-text email body from Job folder."""
    try:
        return run(["himalaya", "message", "read", str(eid), "--folder", HIMALAYA_FOLDER],
                   timeout=60)
    except subprocess.TimeoutExpired:
        print(f"  ⚠ Timeout reading email #{eid}, skipping")
        return ""


def read_email_raw(eid: int) -> str | None:
    """Export email as raw .eml to get full MIME/HTML. Returns file path or None."""
    try:
        eml_path = f"/tmp/job-scan-{eid}.eml"
        run(["himalaya", "message", "export", str(eid), "--folder", HIMALAYA_FOLDER,
             "--full", "--destination", eml_path], timeout=30)
        return eml_path if os.path.exists(eml_path) else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def parse_linkedin_alert(body: str) -> list[dict]:
    """Parse a LinkedIn Job Alerts digest email. Returns list of job dicts."""
    jobs = []
    # Split by the separator line (40+ dashes)
    blocks = re.split(r'-{30,}', body)

    for block in blocks:
        block = block.strip()
        if not block or "Your job alert" in block or "See all jobs" in block:
            continue
        if "Job search smarter" in block or "Unsubscribe" in block:
            continue

        job = _parse_linkedin_block(block)
        if job and job.get("role") and job.get("company"):
            jobs.append(job)

    return jobs


def _parse_linkedin_block(block: str) -> dict | None:
    """Parse one job block from a LinkedIn alert."""
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    if len(lines) < 3:
        return None

    # Skip email header lines that get picked up as blocks
    if any(line.startswith(p) for line in lines[:3] for p in ("From:", "To:", "Subject:", "Date:", "MIME", "Content-")):
        return None

    # First non-empty meaningful line is the role
    role = None
    company = None
    location = None
    url = None

    i = 0
    # Role is first line
    if i < len(lines):
        role = lines[i]
        i += 1

    # Company is second line
    if i < len(lines):
        company = lines[i]
        i += 1

    # Location is third line (unless it's "This company is actively hiring" etc.)
    for j in range(i, len(lines)):
        line = lines[j]
        if line.startswith("http"):
            # Extract the job URL (first one is the right one for this job)
            url_match = re.search(r'(https://www\.linkedin\.com/comm/jobs/view/\d+/\S*?)(?:\s|$)', line)
            if url_match:
                url = url_match.group(1)
                # Strip trailing tracking params for dedup
                url = re.sub(r'\?.*', '', url)
            break
        elif line in ("Apply with resume & profile", "This company is actively hiring",
                       "View job:"):
            continue
        elif line.startswith("View job:"):
            url_match = re.search(r'(https://www\.linkedin\.com/comm/jobs/view/\d+/\S*?)(?:\s|$)', line)
            if url_match:
                url = url_match.group(1)
                url = re.sub(r'\?.*', '', url)
            break
        elif re.match(r'^\d+\s*connection', line):
            continue
        elif re.match(r'^\d+\s*(applicant|applicants)', line, re.IGNORECASE):
            continue
        elif "ago" in line:
            continue
        else:
            # Could be location or another data line
            if location is None and "-" not in line and len(line) < 50:
                location = line

    if not role or not company:
        return None

    return {
        "role": role,
        "company": company,
        "location": location or "",
        "url": url or "",
        "source": "LinkedIn",
    }


def parse_itviec_alert(body: str, eml_path: str | None = None) -> list[dict]:
    """Parse an ITviec Job Robot email. Extracts job data from text, and URLs from raw HTML if available.

    Returns list of job dicts with 'url' populated when HTML links are found.
    """
    jobs = []
    # First, extract basic job data from text body (Job N: Title, Employer, Salary)
    job_pattern = re.compile(
        r'Job\s+\d+\s*:\s*(.+?)\n'           # Job N: Title
        r'.*?Employer\s*:\s*(.+?)\n'         # Employer: Company
        r'(?:.*?Salary\s*:\s*(.+?)\n)?'      # Salary: range (optional)
        r'(?:.*?Location\s*:\s*(.+?)\n)?',    # Location (optional)
        re.DOTALL
    )

    for match in job_pattern.finditer(body):
        role = match.group(1).strip() if match.group(1) else None
        company = match.group(2).strip() if match.group(2) else None
        salary = match.group(3).strip() if match.group(3) else ""
        location = match.group(4).strip() if match.group(4) else ""

        if role and company:
            role = role.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
            company = company.replace("&amp;", "&").replace("&#39;", "'")
            salary = salary.replace("&amp;", "&").replace("&#39;", "'")

            jobs.append({
                "role": role,
                "company": company,
                "location": location or "",
                "url": "",
                "source": "ITviec",
                "salary": salary,
            })

    # Match each parsed job to at most one HTML link. Reserve every exact
    # normalized title match first, across the whole email, so an earlier
    # truncated title cannot consume a later job's exact link. Only then use
    # containment as a fallback for the remaining jobs and links.
    if eml_path and os.path.exists(eml_path):
        unmatched_html_jobs = _extract_itviec_urls_from_eml(eml_path)
        unmatched_jobs = []
        for job in jobs:
            role_clean = normalized_text(job["role"])
            exact_match = next((
                html_job for html_job in unmatched_html_jobs
                if normalized_text(html_job["title"]) == role_clean
            ), None)
            if exact_match is None:
                unmatched_jobs.append(job)
                continue
            job["url"] = exact_match["url"]
            unmatched_html_jobs.remove(exact_match)

        for job in unmatched_jobs:
            role_clean = normalized_text(job["role"])
            candidates = [
                html_job for html_job in unmatched_html_jobs
                if role_clean in normalized_text(html_job["title"])
                or normalized_text(html_job["title"]) in role_clean
            ]
            if not candidates:
                continue
            chosen = min(
                candidates,
                key=lambda html_job: abs(len(normalized_text(html_job["title"])) - len(role_clean)),
            )
            job["url"] = chosen["url"]
            unmatched_html_jobs.remove(chosen)

    return jobs


def _extract_itviec_urls_from_eml(eml_path: str) -> list[dict]:
    """Parse raw .eml file to find ITviec job links with their anchor text.
    Returns list of {'title': str, 'url': str}."""
    results = []
    try:
        with open(eml_path, "rb") as f:
            message = BytesParser(policy=policy.default).parse(f)
        html_parts = []
        for part in message.walk():
            if part.get_content_type() != "text/html":
                continue
            try:
                html_parts.append(part.get_content())
            except (LookupError, UnicodeDecodeError):
                payload = part.get_payload(decode=True) or b""
                html_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        content = "\n".join(html_parts)
        if not content:
            with open(eml_path, "r", errors="ignore") as f:
                content = f.read()
            # Legacy fallback for non-MIME or malformed quoted-printable exports.
            content = re.sub(r'=\r?\n', '', content).replace("=3D", "=")
    except (OSError, ValueError):
        return results

    # Pattern: <a class="text-decoration-none" href="https://links.itviec.com/ls/click?...">
    #          <span class='job-title...'>Job Title</span>
    link_pattern = re.compile(
        r'<a\b(?=[^>]*class=["\'][^"\']*text-decoration-none[^"\']*["\'])'
        r'(?=[^>]*href=["\'](https://links\.itviec\.com/ls/click\?[^"\']+)["\'])'
        r'[^>]*>.*?<span\b[^>]*class=["\'][^"\']*job-title[^"\']*["\'][^>]*>'
        r'([\s\S]*?)</span>',
        re.IGNORECASE,
    )

    for match in link_pattern.finditer(content):
        url = match.group(1)
        title = re.sub(r"<[^>]+>", "", match.group(2))
        title = html_mod.unescape(title.strip())
        results.append({"title": title, "url": url})

    return results


def crawl_job_page(url: str, source: str = "itviec", playwright: bool = False,
                    cookies_file: str = "") -> dict:
    """Crawl a job page for description. Uses Playwright if available and requested.
    Returns {'description': str, 'real_url': str, 'error': str}."""
    if playwright:
        return _crawl_with_playwright(url, source, cookies_file)
    elif source == "itviec":
        return _crawl_itviec_curl(url)
    else:
        return {"description": "", "real_url": url, "error": "LinkedIn requires --playwright mode"}


def _crawl_with_playwright(url: str, source: str, cookies_file: str = "") -> dict:
    """Call the Node.js Playwright crawler."""
    scripts_dir = Path(__file__).parent
    crawler_script = scripts_dir / "job-crawler.mjs"
    if not crawler_script.exists():
        return {"description": "", "real_url": url,
                "error": f"Playwright crawler not found at {crawler_script}"}

    cmd = ["node", str(crawler_script), "--url", url, "--source", source]
    if cookies_file and os.path.exists(cookies_file):
        cmd += ["--cookies", cookies_file]

    try:
        output = run(cmd, timeout=60)
        data = json.loads(output)
        if data.get("error"):
            return {"description": data.get("description", ""),
                    "real_url": data.get("real_url", url),
                    "error": data["error"]}
        return {
            "description": data.get("description", ""),
            "real_url": data.get("real_url", url),
            "error": "",
            "salary": data.get("salary", ""),
            "benefits": data.get("benefits", ""),
            "requirements": data.get("requirements", ""),
        }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return {"description": "", "real_url": url, "error": str(e)[:100]}


def _crawl_itviec_curl(tracking_url: str, timeout: int = 15) -> dict:
    """Fallback: follow ITviec tracking URL via curl + regex extraction."""
    result = {"description": "", "real_url": "", "error": ""}
    try:
        req = urllib.request.Request(
            tracking_url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            result["real_url"] = resp.geturl()

        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', '\n', text)
        text = html_mod.unescape(text)
        lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 20]

        useful = []
        capture = False
        for line in lines:
            if any(kw in line.lower() for kw in
                   ["trách nhiệm", "responsibilities", "yêu cầu", "requirements",
                    "tại sao", "why you", "benefits", "phúc lợi", "mô tả",
                    "job description"]):
                capture = True
            if capture and not any(skip in line for skip in
                    ["ITviec", "Save Job", "Report", "Share", "Applied",
                     "Explore", "Top 30", "Best IT", "Reviews include"]):
                useful.append(line)
            if any(kw in line.lower() for kw in
                   ["việc làm cloud", "tags:", "report this job",
                    "itviec.com/companies"]):
                capture = False

        result["description"] = "\n".join(useful[:50])
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        result["error"] = str(e)[:100]

    return result


def parse_email(from_addr: str, body: str, eml_path: str | None = None) -> list[dict]:
    """Route to the correct parser based on sender."""
    if "linkedin" in from_addr.lower() and "job" in from_addr.lower():
        return parse_linkedin_alert(body)
    elif "itviec" in from_addr.lower():
        return parse_itviec_alert(body, eml_path=eml_path)
    return []


# ── Notion Operations ────────────────────────────────────────────────────────

def list_notion_pages() -> list[dict]:
    """Return every current Job Tracking page, handling Notion pagination."""
    pages = []
    payload = {"page_size": 100}
    cursor = None
    while True:
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_post(f"data_sources/{NOTION_DS_ID}/query", payload, version=NOTION_VERSION_QUERY)
        pages.extend(data.get("results", []))
        if not data.get("has_more", False):
            return pages
        cursor = data.get("next_cursor")


def get_existing_deduplication_keys() -> tuple[set[str], set[str]]:
    """Get URL and structured-Notes keys for idempotent inserts."""
    urls = set()
    fingerprints = set()
    for page in list_notion_pages():
        props = page.get("properties", {})
        url_val = props.get("Job URL", {}).get("url", "")
        if url_val:
            urls.add(normalized_job_url(url_val))
        fingerprint = notes_fingerprint(rich_text_value(props.get("Notes", {})))
        if fingerprint:
            fingerprints.add(fingerprint)
    return urls, fingerprints


def archive_older_duplicates(dry_run: bool = False) -> int:
    """Archive older structured duplicates, preserving the newest Notion page."""
    page_ids = duplicate_page_ids_to_archive(list_notion_pages())
    if not page_ids:
        print("No structured duplicate pages found.")
        return 0

    action = "Would archive" if dry_run else "Archiving"
    print(f"{action} {len(page_ids)} older duplicate page(s); keeping the latest in each group.")
    for page_id in page_ids:
        if dry_run:
            print(f"  [DRY-RUN] Would archive: {page_id}")
            continue
        try:
            updated = notion_patch(f"pages/{page_id}", {"archived": True})
            if updated.get("archived"):
                print(f"  ✓ Archived: {page_id}")
            else:
                raise RuntimeError("Notion did not confirm the archived state")
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError) as error:
            print(f"  ✗ Failed to archive {page_id}: {error}")
            raise
        time.sleep(0.35)
    return len(page_ids)


def normalize_location(loc: str) -> str:
    """Map raw location string to Notion select option."""
    loc = loc.strip().lower()
    if "district 1" in loc or "quận 1" in loc or "q1" in loc:
        return "HCMC - District 1"
    if "district 2" in loc or "thu duc" in loc or "thủ đức" in loc or "quận 2" in loc:
        return "HCMC - District 2 / Thu Duc"
    if "district 7" in loc or "quận 7" in loc:
        return "HCMC - District 7"
    if "tan binh" in loc or "tân bình" in loc:
        return "HCMC - Tan Binh"
    if "binh thanh" in loc or "bình thạnh" in loc:
        return "HCMC - Binh Thanh"
    if "ho chi minh" in loc or "hồ chí minh" in loc or "hcm" in loc or "saigon" in loc:
        return "HCMC - Other"
    if "hanoi" in loc or "hà nội" in loc or "ha noi" in loc:
        return "Other City"
    if "remote" in loc:
        return "HCMC - Remote"
    if "da nang" in loc or "đà nẵng" in loc:
        return "Other City"
    if loc:
        return "Other City"
    return ""


def normalize_role(role: str) -> str:
    """Map raw role title to Notion select option."""
    role_lower = role.lower()
    if "senior" in role_lower or "sr " in role_lower or "sr." in role_lower:
        if "ai" in role_lower or "ml" in role_lower or "machine learning" in role_lower:
            return "ML / AI Engineer"
        if "backend" in role_lower or "back end" in role_lower or "back-end" in role_lower:
            return "Backend Engineer"
        if "frontend" in role_lower or "front end" in role_lower:
            return "Frontend Engineer"
        if "full" in role_lower and "stack" in role_lower:
            return "Full-Stack Engineer"
        return "Senior Software Engineer"

    if "ai" in role_lower or "ml" in role_lower or "machine learning" in role_lower or "data scientist" in role_lower:
        return "ML / AI Engineer"

    if "backend" in role_lower or "back end" in role_lower or "back-end" in role_lower:
        return "Backend Engineer"

    if "frontend" in role_lower or "front end" in role_lower or "front-end" in role_lower:
        return "Frontend Engineer"

    if "full" in role_lower and "stack" in role_lower:
        return "Full-Stack Engineer"

    if "devops" in role_lower or "sre" in role_lower or "site reliability" in role_lower:
        return "DevOps / SRE"

    if "data engineer" in role_lower:
        return "Data Engineer"

    if "mobile" in role_lower or "android" in role_lower or "ios" in role_lower:
        return "Mobile Engineer"

    if "manager" in role_lower or "lead" in role_lower or "head" in role_lower:
        if "engineering" in role_lower or "tech" in role_lower:
            return "Engineering Manager"

    if "principal" in role_lower or "staff" in role_lower:
        if "ai" in role_lower or "ml" in role_lower:
            return "ML / AI Engineer"
        return "Staff Software Engineer"

    # Default: generic software engineer
    if "engineer" in role_lower or "developer" in role_lower or "software" in role_lower:
        return "Software Engineer"

    return "Other"


def normalize_company(company: str) -> str:
    """Return a canonical Company select value without discarding new companies.

    Notion accepts a select option by name. Known aliases are consolidated into
    the existing taxonomy; an unknown parsed company is retained verbatim so it
    becomes a useful Company value instead of the catch-all ``Other``.
    """
    aliases = {
        "google": "Google", "meta": "Meta", "microsoft": "Microsoft",
        "amazon": "Amazon", "apple": "Apple", "netflix": "Netflix",
        "grab": "Grab", "shopee": "Shopee (Sea Group)", "tiktok": "TikTok (ByteDance)",
        "bytedance": "TikTok (ByteDance)", "vng": "VNG (Zalo)", "zalo": "VNG (Zalo)",
        "momo": "MoMo", "axon": "Axon", "trust social": "Trust Social",
        "bosch": "Bosch", "intel": "Intel", "samsung": "Samsung",
        "oracle": "Oracle", "dell": "DELL", "sap": "SAP", "nvidia": "NVIDIA",
        # Existing Notion taxonomy aliases seen in job-alert data.
        "eastgate software": "Eastgate Software",
        "fpt software": "FPT Software",
        "fpt software career": "FPT Software Career",
        "larion": "LARION",
        "opswat": "OPSWAT",
        "xcapital technology": "XCapital Technology",
        "vinfast": "VINFAST",
        "vinsmart future": "VinSmart Future",
        "cyberlogictec": "CyberLogitec",
        "cyberlogitec": "CyberLogitec",
        "sotatek": "SOTATEK. JSC",
    }
    raw = html_mod.unescape(company).strip()
    if not raw:
        return "Other"

    key = raw.lower()
    # Use longest-first matching so a specific alias wins over a short one,
    # such as "fpt software career" over "fpt software".
    for alias, canonical in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in key:
            return canonical

    # Notion select option names cannot contain commas. The raw source is still
    # retained in Notes, while the Company select uses a valid, readable form.
    return re.sub(r"\s+", " ", raw.replace(",", "")).strip()


def _telegram_text(value: str) -> str:
    """Escape job-alert text that would otherwise alter Telegram Markdown."""
    return re.sub(r"([\\`*_\[\]])", r"\\\1", str(value or "").strip())


def format_telegram_update(jobs: list[dict], total_jobs: int, skipped: int,
                           timestamp: datetime | None = None) -> str:
    """Render the daily scan as compact job cards for Telegram."""
    timestamp = timestamp or datetime.now().astimezone()
    found_at = timestamp.strftime("%d-%m-%Y %H:%M:%S")

    if not jobs:
        return (
            "📦 **Daily Job Updates**\n"
            "No new jobs today.\n"
            f"`{total_jobs} parsed · {skipped} duplicates`\n"
        )

    cards = []
    for index, job in enumerate(jobs, start=1):
        role = _telegram_text(job.get("role", "Unknown role"))
        company = _telegram_text(job.get("company", "Unknown company"))
        source = _telegram_text(job.get("source", "Email"))
        category = _telegram_text(normalize_role(job.get("role", "")).lower())
        lines = [
            f"📦 **<{category} | {source} | new> (#{index})**",
            f"💯 **{role}**",
            f"🏢 {company}",
        ]

        if job.get("location"):
            lines.append(f"📍 {_telegram_text(job['location'])}")
        lines.append(f"🗓 {found_at}")

        if job.get("url"):
            safe_url = str(job["url"]).strip().replace(" ", "%20").replace("(", "%28").replace(")", "%29")
            lines.append(f"🔗 [Open on {source}]({safe_url})")
        if job.get("salary"):
            lines.append(f"💰 {_telegram_text(job['salary'])}")

        cards.append("\n".join(lines))

    heading = f"**Daily Job Updates — {len(jobs)} new**"
    footer = f"`{total_jobs} parsed · {skipped} duplicates`"
    return f"{heading}\n\n" + "\n\n".join(cards) + f"\n\n{footer}\n"


def create_notion_page(job: dict, dry_run: bool = False, body_md: str = "") -> str | None:
    """Create a page in the Job Tracking database. Optionally appends markdown body content.
    Returns page ID or None."""
    name = job['role']  # Name = role title only

    props = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Status": {"select": {"name": job.get("status", "Saved")}},
        "Source": {"select": {"name": job.get("source", "Email")}},
        "Date Found": {"date": {"start": date.today().isoformat()}},
    }

    # Company
    company_select = normalize_company(job["company"])
    props["Company"] = {"select": {"name": company_select}}

    # Role
    role_select = normalize_role(job["role"])
    props["Role"] = {"select": {"name": role_select}}

    # Location
    loc_select = normalize_location(job.get("location", ""))
    if loc_select:
        props["Location"] = {"select": {"name": loc_select}}

    # Job URL
    if job.get("url"):
        props["Job URL"] = {"url": job["url"]}

    # Notes: store original raw values for reference
    notes_parts = [f"Company: {job['company']}", f"Role: {job['role']}"]
    if job.get("location"):
        notes_parts.append(f"Location: {job['location']}")
    if job.get("salary"):
        notes_parts.append(f"Salary: {job['salary']}")
        props["Salary Range"] = {"rich_text": [{"text": {"content": job["salary"]}}]}
    props["Notes"] = {"rich_text": [{"text": {"content": " | ".join(notes_parts)}}]}

    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": props,
    }

    # Attach body as markdown if provided
    if body_md:
        payload["markdown"] = body_md

    if dry_run:
        print(f"  [DRY-RUN] Would create: {name}" + (f" (with body: {len(body_md)} chars)" if body_md else ""))
        return None

    try:
        data = notion_post("pages", payload)
        page_id = data.get("id", "")
        print(f"  ✓ Created: {name} ({page_id[:8]}...)" + (f" + description" if body_md else ""))
        return page_id
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else str(e)
        print(f"  ✗ Failed: {name} — {e.code}: {err_body[:200]}")
        return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    process_all = "--all" in sys.argv
    prune_duplicates = "--prune-duplicates" in sys.argv
    crawl = "--crawl" in sys.argv
    playwright = "--playwright" in sys.argv
    cookies_file = ""
    telegram_output_file = ""
    # Check for --cookies <file> argument
    for i, arg in enumerate(sys.argv):
        if arg == "--cookies" and i + 1 < len(sys.argv):
            cookies_file = sys.argv[i + 1]
            break
    for i, arg in enumerate(sys.argv):
        if arg == "--telegram-output" and i + 1 < len(sys.argv):
            telegram_output_file = sys.argv[i + 1]
            break

    if prune_duplicates:
        archived = archive_older_duplicates(dry_run=dry_run)
        print(f"Duplicate cleanup complete: {archived} page(s) {'would be archived' if dry_run else 'archived'}.")
        return

    # Read last processed ID
    last_id: int | None = None
    if not process_all and STATE_FILE.exists():
        try:
            last_id = int(STATE_FILE.read_text().strip())
        except (ValueError, OSError):
            last_id = None

    print(f"Last processed ID: {last_id or 'none (first run)'}")
    if crawl:
        mode = "Playwright (stealth browser)" if playwright else "curl"
        print(f"Crawling enabled: {mode}")
        if playwright and cookies_file:
            print(f"  Using cookies from: {cookies_file}")

    # Get existing URL and structured-Notes keys from Notion for deduplication.
    print("Fetching existing entries from Notion...")
    existing_urls, existing_fingerprints = get_existing_deduplication_keys()
    print(f"  Found {len(existing_urls)} URL keys and {len(existing_fingerprints)} structured Notes keys")

    # List new emails
    emails = list_new_emails(since_id=None if process_all else last_id)
    emails.sort(key=lambda e: e["id"])
    print(f"\nNew emails to process: {len(emails)}")

    total_jobs = 0
    created = 0
    skipped = 0
    failed = 0
    linkedin_notes_written = 0
    itviec_notes_written = 0
    created_jobs = []
    max_id = last_id or 0

    for email in emails:
        eid = email["id"]
        sender = email["from"]
        subject = email["subject"]
        email_failed = False
        print(f"\n── Email #{eid} | {sender} | {subject[:60]}...")

        body = read_email(eid)
        if not body.strip():
            print("  (empty body, skipping)")
            max_id = max(max_id, eid)
            continue

        # For ITviec emails, also get the raw HTML export for URL extraction
        eml_path = None
        if "itviec" in sender.lower():
            eml_path = read_email_raw(eid)

        jobs = parse_email(sender, body, eml_path=eml_path)
        if not jobs:
            print(f"  No jobs parsed")
        else:
            print(f"  Parsed {len(jobs)} job(s)" + (f" ({sum(1 for j in jobs if j.get('url'))} with URLs)" if any(j.get("url") for j in jobs) else ""))

        for job in jobs:
            total_jobs += 1
            url = job.get("url", "")

            # Avoid external enrichment for identities already known from the
            # email. A second check after enrichment handles canonical URLs and
            # changed location/salary fields.
            reason = duplicate_reason(job, existing_urls, existing_fingerprints)
            if reason:
                print(f"  ⊘ Skipped (duplicate {reason}): {job['company']} — {job['role']}")
                skipped += 1
                continue

            body_md = ""
            is_linkedin = "linkedin" in (job.get("source", "")).lower()
            is_itviec = "itviec" in (job.get("source", "")).lower()
            if is_linkedin and url:
                print(f"  Collecting LinkedIn details: {job['role'][:50]}...")
                try:
                    detail = collect_linkedin_detail(url)
                    job, body_md = apply_linkedin_detail(job, detail)
                    url = job.get("url", url)
                    print(
                        f"    Collected {len(detail.get('description', ''))} chars; "
                        f"availability={detail.get('availability', 'unknown')}"
                    )
                except (json.JSONDecodeError, OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
                    print(f"    Failed LinkedIn collection: {str(error)[:200]}")
                    failed += 1
                    email_failed = True
                    continue

            if is_itviec and url:
                print(f"  Collecting ITviec details: {job['role'][:50]}...")
                try:
                    detail = collect_itviec_detail(job)
                    job, body_md = apply_itviec_detail(job, detail)
                    url = job.get("url", url)
                    print(
                        f"    Collected {len(detail.get('description', ''))} chars; "
                        f"availability={detail.get('availability', 'unknown')}"
                    )
                except (json.JSONDecodeError, OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
                    print(f"    Failed ITviec collection: {str(error)[:200]}")
                    failed += 1
                    email_failed = True
                    continue

            # Optional legacy crawler remains available for non-LinkedIn sources.
            if crawl and url and not is_linkedin and not is_itviec:
                source = "linkedin" if "linkedin" in (job.get("source", "")).lower() else "itviec"
                print(f"  🔍 Crawling [{source}]: {job['role'][:50]}...")
                crawl_result = crawl_job_page(url, source=source,
                                              playwright=playwright,
                                              cookies_file=cookies_file)
                if crawl_result["description"]:
                    real_url = crawl_result.get("real_url", "")
                    body_md = f"## {job['role']}\n\n**Company:** {job['company']}\n\n"
                    if real_url:
                        body_md += f"**Source:** {real_url}\n\n"
                    body_md += crawl_result["description"]
                    print(f"    Extracted {len(crawl_result['description'])} chars of description")
                elif crawl_result["error"]:
                    print(f"    ⚠ Crawl error: {crawl_result['error'][:80]}")
                else:
                    print(f"    ⚠ No description extracted")

            # Enrichment can replace a tracking URL with the canonical listing
            # and can change fingerprint fields. Recheck the exact values that
            # will be persisted before writing either Notion or Obsidian.
            reason = duplicate_reason(job, existing_urls, existing_fingerprints)
            if reason:
                print(f"  ⊘ Skipped after enrichment (duplicate {reason}): {job['company']} — {job['role']}")
                skipped += 1
                continue

            if not dry_run:
                try:
                    if is_linkedin and job.get("linkedin_detail"):
                        note_path = write_linkedin_job_markdown(job)
                        linkedin_notes_written += 1
                        print(f"    Wrote Obsidian note: {note_path.name}")
                    if is_itviec and job.get("itviec_detail"):
                        note_path = write_itviec_job_markdown(job)
                        itviec_notes_written += 1
                        print(f"    Wrote Obsidian note: {note_path.name}")
                except (OSError, ValueError) as error:
                    print(f"    Failed to write Obsidian note: {error}")
                    failed += 1
                    email_failed = True
                    continue

            page_id = create_notion_page(job, dry_run=dry_run, body_md=body_md)
            if page_id:
                created += 1
                created_jobs.append(job.copy())
                if is_linkedin and job.get("linkedin_detail") and not dry_run:
                    try:
                        write_linkedin_job_markdown(job, notion_page_id=page_id)
                    except OSError as error:
                        print(f"    Failed to attach Notion link to Obsidian note: {error}")
                        failed += 1
                        email_failed = True
                if is_itviec and job.get("itviec_detail") and not dry_run:
                    try:
                        write_itviec_job_markdown(job, notion_page_id=page_id)
                    except OSError as error:
                        print(f"    Failed to attach Notion link to ITviec Obsidian note: {error}")
                        failed += 1
                        email_failed = True
                remember_job_identity(job, existing_urls, existing_fingerprints)
            elif dry_run:
                created += 1  # count dry-run as success
                created_jobs.append(job.copy())
                remember_job_identity(job, existing_urls, existing_fingerprints)
            else:
                failed += 1
                email_failed = True

        # Clean up temp eml file
        if eml_path and os.path.exists(eml_path):
            try:
                os.remove(eml_path)
            except OSError:
                pass

        if email_failed:
            print(f"  Email #{eid} had failures; leaving the checkpoint unchanged for retry.")
            break
        max_id = max(max_id, eid)

    if not dry_run and linkedin_notes_written:
        index_path = update_linkedin_jobs_index()
        print(f"\nObsidian index updated: {index_path} ({linkedin_notes_written} new/updated note(s))")
    if not dry_run and itviec_notes_written:
        index_path = update_itviec_jobs_index()
        print(f"\nObsidian index updated: {index_path} ({itviec_notes_written} new/updated ITviec note(s))")

    # Update state
    if not dry_run and max_id > (last_id or 0):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(str(max_id))
        print(f"\nState updated: last processed ID = {max_id}")

    print(f"\n{'='*50}")
    print(
        f"Summary: {total_jobs} jobs parsed, {created} created, "
        f"{skipped} skipped (duplicates), {failed} failed"
    )
    if dry_run:
        print("DRY RUN — no changes made")
    print(f"{'='*50}")

    if telegram_output_file:
        output_path = Path(telegram_output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            format_telegram_update(created_jobs, total_jobs, skipped),
            encoding="utf-8",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
