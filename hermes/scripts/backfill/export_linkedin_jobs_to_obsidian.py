import json
import re
from collections import Counter
from pathlib import Path

MANIFEST = Path("/home/delus/.hermes/cache/linkedin-jobs-manifest.json")
DETAILS = Path("/home/delus/.hermes/cache/linkedin-job-details-cache.json")
OUTPUT_DIR = Path("/mnt/d/Obsidian/40 Resources/Job Tracking/LinkedIn Jobs")
EXPORT_MANIFEST = Path("/home/delus/.hermes/cache/obsidian-linkedin-job-export.json")
COLLECTED_DATE = "2026-08-22"

jobs = json.loads(MANIFEST.read_text(encoding="utf-8"))
details = json.loads(DETAILS.read_text(encoding="utf-8"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def job_id(url):
    match = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", url or "")
    if not match:
        raise ValueError(f"Unsupported LinkedIn URL: {url}")
    return match.group(1)


def filename(value, jid):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', value or 'LinkedIn Job')
    name = re.sub(r'\s+', ' ', name).strip(' .-')
    name = name[:110].rstrip(' .-') or 'LinkedIn Job'
    return f"{name} - {jid}.md"


def yaml_value(value):
    return json.dumps(value if value is not None else "", ensure_ascii=False)


def md_value(value):
    text = str(value or "").strip()
    return text or "Not available"


def table_value(value):
    return str(value or "").replace('|', '\\|').replace('\n', ' ').strip()


def final_status(job, detail):
    current = job.get("status") or ""
    if detail.get("availability") in {"closed", "unavailable"} and current in {"Saved", "To Apply"}:
        return "No Accept Apply"
    return current


exports = []
seen_paths = set()
for job in jobs:
    jid = job_id(job["job_url"])
    detail = details.get(jid)
    if detail is None:
        raise RuntimeError(f"Missing collected detail for LinkedIn job {jid}")
    title = detail.get("title") or job.get("name") or "LinkedIn Job"
    company = detail.get("company") or job.get("company") or "Unknown company"
    criteria = detail.get("criteria") or {}
    links = detail.get("links") or {}
    note_name = filename(f"{company} - {title}", jid)
    path = OUTPUT_DIR / note_name
    if str(path).lower() in seen_paths:
        raise RuntimeError(f"Duplicate output path: {path}")
    seen_paths.add(str(path).lower())

    status = final_status(job, detail)
    description = str(detail.get("description") or "").strip() or "The LinkedIn listing is unavailable; no job description could be collected."
    frontmatter = [
        "---",
        f"type: {yaml_value('job')}",
        f"source: {yaml_value('LinkedIn')}",
        f"linkedin_job_id: {yaml_value(jid)}",
        f"title: {yaml_value(title)}",
        f"company: {yaml_value(company)}",
        f"location: {yaml_value(detail.get('location') or job.get('location'))}",
        f"availability: {yaml_value(detail.get('availability'))}",
        f"accepting_applications: {str(bool(detail.get('accepting_applications'))).lower()}",
        f"listed: {yaml_value(detail.get('listed'))}",
        f"applicants: {yaml_value(detail.get('applicants'))}",
        f"employment_type: {yaml_value(criteria.get('job_type'))}",
        f"seniority_level: {yaml_value(criteria.get('seniority_level'))}",
        f"job_function: {yaml_value(criteria.get('job_function'))}",
        f"industries: {yaml_value(criteria.get('industries'))}",
        f"job_url: {yaml_value(links.get('listing') or f'https://www.linkedin.com/jobs/view/{jid}/')}",
        f"company_url: {yaml_value(links.get('company'))}",
        f"notion_url: {yaml_value(job.get('notion_url'))}",
        f"date_found: {yaml_value(job.get('date_found'))}",
        f"notion_status: {yaml_value(status)}",
        f"collected: {yaml_value(COLLECTED_DATE)}",
        f"tags: {yaml_value(['job', 'linkedin'])}",
        "---",
    ]
    body = [
        f"# {title}",
        "",
        f"**Company:** {company}",
        f"**Location:** {md_value(detail.get('location') or job.get('location'))}",
        f"**LinkedIn availability:** {md_value(detail.get('availability'))}",
        f"**Notion status:** {md_value(status)}",
        "",
        "## Job metadata",
        "",
        f"- **Employment type:** {md_value(criteria.get('job_type'))}",
        f"- **Seniority level:** {md_value(criteria.get('seniority_level'))}",
        f"- **Job function:** {md_value(criteria.get('job_function'))}",
        f"- **Industries:** {md_value(criteria.get('industries'))}",
        f"- **Applicants:** {md_value(detail.get('applicants'))}",
        f"- **Listed:** {md_value(detail.get('listed'))}",
        f"- **LinkedIn listing:** {links.get('listing') or f'https://www.linkedin.com/jobs/view/{jid}/'}",
    ]
    if links.get("company"):
        body.append(f"- **Company page:** {links['company']}")
    body.extend([
        "",
        "## Job description",
        "",
        description,
        "",
        "## Tracking",
        "",
        f"- **Notion page:** {job.get('notion_url') or 'Not available'}",
        f"- **Date found:** {md_value(job.get('date_found'))}",
        f"- **Original tracker notes:** {md_value(job.get('notes'))}",
        "",
    ])
    path.write_text("\n".join(frontmatter + [""] + body), encoding="utf-8")
    exports.append({
        "job_id": jid,
        "title": title,
        "company": company,
        "availability": detail.get("availability") or "unknown",
        "notion_status": status,
        "path": str(path),
        "wikilink": path.stem,
        "description_chars": len(description),
    })

counts = Counter(item["availability"] for item in exports)
index_lines = [
    "---",
    f"type: {yaml_value('job-index')}",
    f"source: {yaml_value('LinkedIn')}",
    f"collected: {yaml_value(COLLECTED_DATE)}",
    f"job_count: {len(exports)}",
    "---",
    "",
    "# LinkedIn Jobs",
    "",
    f"Collected **{len(exports)}** LinkedIn job listings on {COLLECTED_DATE}.",
    "",
    "## Availability",
    "",
]
for key in sorted(counts):
    index_lines.append(f"- **{key}:** {counts[key]}")
index_lines.extend([
    "",
    "## Jobs",
    "",
    "| Company | Role | Availability | Notion status | Note |",
    "|---|---|---|---|---|",
])
for item in sorted(exports, key=lambda row: (row["company"].casefold(), row["title"].casefold(), row["job_id"])):
    index_lines.append(
        f"| {table_value(item['company'])} | {table_value(item['title'])} | "
        f"{table_value(item['availability'])} | {table_value(item['notion_status'])} | "
        f"[[{item['wikilink']}]] |"
    )
index_path = OUTPUT_DIR / "LinkedIn Jobs.md"
index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")

EXPORT_MANIFEST.write_text(json.dumps({
    "output_dir": str(OUTPUT_DIR),
    "index": str(index_path),
    "count": len(exports),
    "availability": dict(sorted(counts.items())),
    "jobs": exports,
}, indent=2, ensure_ascii=False), encoding="utf-8")

print(json.dumps({
    "output_dir": str(OUTPUT_DIR),
    "index": str(index_path),
    "count": len(exports),
    "availability": dict(sorted(counts.items())),
    "export_manifest": str(EXPORT_MANIFEST),
}, indent=2, ensure_ascii=False))
