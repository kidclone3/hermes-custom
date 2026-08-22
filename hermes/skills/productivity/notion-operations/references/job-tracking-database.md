# Job Tracking Database — Proven Schema

Schema for tracking job applications via Notion. Focused on Software Engineer roles in a specific city market.

## Properties

| Property | Type | Purpose |
|---|---|---|
| Name | title | Role title only (e.g. `AI Engineer`). Company goes in the Company column. |
| Company | select | Pre-populate with target companies (20+ options). Unknown companies map to "Other"; raw name stored in Notes. |
| Role | select | SWE, Senior SWE, Staff SWE, Backend, Full-Stack, ML/AI, etc. (15 options) |
| Status | select | Saved → To Apply → Applied → Phone Screen → Interviewing → Offer → Rejected → Declined → Closed |
| Source | select | Email, LinkedIn, Company Website, Referral, Job Board, Recruiter Reachout |
| Location | select | City districts (District 1, 2/Thu Duc, 7, etc.) + Remote |
| Date Found | date | When the role was discovered |
| Date Applied | date | When application was submitted |
| Last Contact | date | For follow-up cadence |
| Salary Range | rich_text | Free-form |
| Job URL | url | Link to the job posting |
| Contact | rich_text | Recruiter/hiring manager name |
| Email Ref | rich_text | Link back to source email ID |
| Notes | rich_text | Free-form. Stores raw company name + original role text for unnormalized entries. |

## Creation Recipe

```bash
# Must use API version 2022-06-28 for databases with properties
curl -s -X POST "https://api.notion.com/v1/databases" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{
    "parent": {"type": "page_id", "page_id": "PARENT_PAGE_ID"},
    "title": [{"type": "text", "text": {"content": "Job Tracking"}}],
    "is_inline": true,
    "properties": {
      "Name": {"title": {}},
      "Company": {"select": {"options": [{"name": "Google", "color": "blue"}, ...]}},
      "Role": {"select": {"options": [...]}},
      "Status": {"select": {"options": [...]}},
      "Source": {"select": {"options": [...]}},
      "Location": {"select": {"options": [...]}},
      "Date Found": {"date": {}},
      "Date Applied": {"date": {}},
      "Last Contact": {"date": {}},
      "Salary Range": {"rich_text": {}},
      "Job URL": {"url": {}},
      "Contact": {"rich_text": {}},
      "Email Ref": {"rich_text": {}},
      "Notes": {"rich_text": {}}
    }
  }'
```

## Page Creation (with markdown body)

Use `2022-06-28` for page creation with typed properties. Attach a `markdown` body field for inline job descriptions:

```bash
curl -s -X POST "https://api.notion.com/v1/pages" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{
    "parent": {"database_id": "DATABASE_ID"},
    "properties": {
      "Name": {"title": [{"text": {"content": "AI Engineer"}}]},
      "Company": {"select": {"name": "Other"}},
      "Status": {"select": {"name": "Saved"}},
      "Source": {"select": {"name": "Email"}},
      "Date Found": {"date": {"start": "2026-07-30"}},
      "Job URL": {"url": "https://..."}
    },
    "markdown": "## Job Description\n\nFull description here..."
  }'
```

## Source-Specific Email Parsing

### LinkedIn Job Alerts

- **Sender:** `jobalerts-noreply@linkedin.com` (digest), `jobs-noreply@linkedin.com` (recommendations)
- **Format:** Text body with jobs separated by `---` (30+ dashes). Each block: Role, Company, Location, `View job: URL`.
- **URLs:** Full LinkedIn job URLs appear in text as `linkedin.com/comm/jobs/view/<id>/...`. Normalize both `/comm/jobs/view/<id>` and `/jobs/view/<id>` to the same stable job-ID key.
- **Detail collection:** The verified local OpenCLI adapter `opencli linkedin job-public-detail <url> -f json` reads LinkedIn's public job HTML, returning exact-ID-verified title, company, location, description, criteria, applicant count, and availability.
- **Identity safety:** Never trust the logged-in `/jobs/search/?currentJobId=<id>` route without verifying the embedded job ID; expired IDs can silently fall back to unrelated search results.
- **Closed state:** LinkedIn can return HTTP 200 for closed jobs. Use the explicit `No longer accepting applications` signal. Map `Saved`/`To Apply` to Notion `No Accept Apply`, but preserve application-pipeline statuses such as `Applied` and `Interviewing`.

### ITviec Job Robot

- **Sender:** `itviec+jobrobot@itviec.com` (daily matches), `itviec+ijm@itviec.com` (recruiter emails)
- **Format (text):** `Job N: Title`, `Employer: Company`, `Salary: range`, `Required Skills: skills`
- **URLs:** Individual job URLs are **in the HTML part only**, not the text render. They use tracking links (`links.itviec.com/ls/click?...`). Himalaya's `message read` strips these — you must use `message export --full` to get the raw `.eml`, then parse the HTML.

### ITviec URL Extraction from Raw .eml

```python
import re, html

with open("email.eml", "r", errors="ignore") as f:
    content = f.read()

# Join quoted-printable soft line breaks (line ending with =)
content = re.sub(r'=\r?\n', '', content)
# Fix =3D → =
content = content.replace("=3D", "=")

# Pattern: <a class="text-decoration-none" href="https://links.itviec.com/ls/click?...">
#          <span class='job-title...'>Job Title</span>
link_pattern = re.compile(
    r'<a\s+class="text-decoration-none"\s+href="'
    r'(https://links\.itviec\.com/ls/click\?[^"]+)"'
    r'[^>]*>.*?<span[^>]*class=\'job-title[^\']*\'>'
    r'([^<]+)</span>',
    re.IGNORECASE | re.DOTALL,
)

for match in link_pattern.finditer(content):
    url = match.group(1)
    title = html.unescape(match.group(2).strip())
    # Match to job by title substring
```

### ITviec Job Detail Collection

ITviec job pages are public and server-render schema.org `JobPosting` JSON-LD. The production path is the local OpenCLI adapter:

```bash
opencli itviec job-public-detail "https://links.itviec.com/ls/click?..." -f json
```

The adapter:

1. Accepts either an email tracking URL or canonical `/it-jobs/<slug>` URL.
2. Follows the redirect and rejects non-ITviec or non-job destinations.
3. Verifies the final path against the JSON-LD `BreadcrumbList` path.
4. Extracts title, company, location, posted/expiry dates, salary, skills, employment type, apply URL, benefits, and full description.
5. Returns `closed` for HTTP 410 and `unavailable` for HTTP 404.
6. Retries bounded HTTP 429/503 responses and limits concurrency to avoid ITviec throttling.

The scanner additionally compares active-listing title and company against the email data. It tolerates ITviec JSON-LD's observed accent loss and suffix truncation only when token overlap is high and the company still matches exactly after normalization.

The old curl/regex and Playwright crawler remains only as a legacy fallback for diagnosis; it is not the default collection path.

### Himalaya Timeouts

LinkedIn alert emails are HTML-only and large. `himalaya message read` can take >30s. Always set timeout to 60s minimum and catch `subprocess.TimeoutExpired`.

## Automated Pipeline

Production script at `~/.hermes/scripts/job-scan.py`. Usage:

```bash
python3 job-scan.py           # process new emails since last run
python3 job-scan.py --all     # process ALL emails (idempotent)
python3 job-scan.py --dry-run # preview without inserting
python3 job-scan.py --crawl   # also fetch ITviec job descriptions
```

**State tracking:** `~/.hermes/state/job-scan-last-id.txt` stores last processed himalaya email ID.

**Cron setup (daily, no agent):**
```
cronjob create --name "Daily Job Scan → Notion" --schedule "0 9 * * *" \
  --script scripts/job-scan.py --no_agent --workdir ~/.hermes
```

**Default mode** runs on cron at 23:00. It enriches every newly parsed LinkedIn job through the exact-ID-verified OpenCLI adapter and every URL-backed ITviec job through the local `opencli itviec job-public-detail` adapter. Both paths write idempotent Markdown notes under `/mnt/d/Obsidian/40 Resources/Job Tracking/{LinkedIn Jobs,ITviec Jobs}/`, regenerate their Obsidian indexes, store canonical listing URLs, and create Notion pages with full job bodies and availability-aware statuses. The legacy `--crawl` path is no longer needed for LinkedIn or ITviec.

## Gmail Filter Setup

To route job emails to the `Job` folder silently (skip inbox):

```
From: jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com OR itviec.com
Action: Apply label "Job" + Skip the Inbox (Archive it)
```
