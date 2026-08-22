import json
import os
import sys
import urllib.error
import urllib.request

DATA_SOURCE_ID = "3abf57f2-0087-817d-8dd0-000bcdac80ef"
OUTPUT = "/home/delus/.hermes/cache/linkedin-jobs-manifest.json"
TOKEN = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_API_TOKEN")
if not TOKEN:
    raise SystemExit("NOTION_API_KEY/NOTION_API_TOKEN is not set")


def request_json(url, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", "2025-09-03")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def plain(prop):
    if not prop:
        return None
    kind = prop.get("type")
    value = prop.get(kind)
    if kind in ("title", "rich_text"):
        return "".join(item.get("plain_text", "") for item in (value or []))
    if kind == "select":
        return value.get("name") if value else None
    if kind == "url":
        return value
    if kind == "checkbox":
        return bool(value)
    if kind == "date":
        return value.get("start") if value else None
    return value

url = f"https://api.notion.com/v1/data_sources/{DATA_SOURCE_ID}/query"
payload = {
    "page_size": 100,
    "filter": {"property": "Source", "select": {"equals": "LinkedIn"}},
    "sorts": [{"property": "Date Found", "direction": "ascending"}],
}
pages = []
while True:
    result = request_json(url, method="POST", payload=payload)
    pages.extend(result.get("results", []))
    if not result.get("has_more"):
        break
    payload["start_cursor"] = result["next_cursor"]

jobs = []
for page in pages:
    props = page.get("properties", {})
    jobs.append({
        "page_id": page["id"],
        "notion_url": page.get("url"),
        "name": plain(props.get("Name")),
        "company": plain(props.get("Company")),
        "role": plain(props.get("Role")),
        "status": plain(props.get("Status")),
        "location": plain(props.get("Location")),
        "level": plain(props.get("Level")),
        "salary_range": plain(props.get("Salary Range")),
        "job_url": plain(props.get("Job URL")),
        "notes": plain(props.get("Notes")),
        "checked": plain(props.get("Checked")),
        "date_found": plain(props.get("Date Found")),
        "last_edited_time": page.get("last_edited_time"),
    })

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(jobs, f, indent=2, ensure_ascii=False)

with_url = sum(bool(job["job_url"]) for job in jobs)
linkedin_urls = sum("linkedin.com" in (job["job_url"] or "").lower() for job in jobs)
print(json.dumps({
    "output": OUTPUT,
    "count": len(jobs),
    "with_job_url": with_url,
    "linkedin_urls": linkedin_urls,
    "missing_url": len(jobs) - with_url,
}, indent=2))
for job in jobs:
    print(f"{job['page_id']}\t{job['name']}\t{job['company']}\t{job['job_url']}")
