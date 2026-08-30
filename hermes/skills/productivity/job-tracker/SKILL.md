---
name: job-tracker
description: "Scan job emails into Notion. Use for job-hunt automation."
version: 1.0.0
platforms: [linux, macos]
prerequisites:
  skills: [himalaya, notion]
  env_vars: [NOTION_API_KEY]
metadata:
  hermes:
    tags: [jobs, email, notion, automation, career]
    managed_by: curator
---

# Job Tracker — Automated Email-to-Notion Pipeline

End-to-end pipeline: Gmail filter → Job folder → daily cron → Notion Job Tracking database. Captures LinkedIn Job Alerts and ITviec Job Robot emails, parses structured job listings, deduplicates by URL, and populates a kanban-style tracking board.

## Architecture

```
Gmail filter rules (manual)
    ↓
Job folder (IMAP)
    ↓
himalaya envelope list → read → parse
    ↓
Notion Job Tracking DB (dedup by URL → insert)
    ↓
Daily cron @ 9 AM
```

## Prerequisites

1. `himalaya` configured with Gmail IMAP access (app password)
2. `NOTION_API_KEY` + `NOTION_KEYRING=0` exported in `~/.hermes/.env`
3. A Notion Job Tracking database already created (see `references/job-tracking-database.md` in `notion-operations`)
4. The `scripts/job-scan.py` script installed at `~/.hermes/scripts/job-scan.py`

## Phase 1: Gmail Filter Setup

Job alert emails come from multiple senders — a single filter must catch all of them or they'll land in the inbox untagged.

### Known sender addresses

| Display Name | From Address | Type |
|---|---|---|
| LinkedIn Job Alerts | `jobalerts-noreply@linkedin.com` | Daily job digest (multi-job) |
| LinkedIn | `jobs-noreply@linkedin.com` | "Company is hiring..." recommendations |
| ITviec Job Robot | `itviec+jobrobot+1@itviec.com` | Daily skill-matched jobs |
| ITviec | `itviec+discussion+4@itviec.com` | Recruitment consulting |

### Filter rule

In Gmail Settings → Filters and Blocked Addresses, create a filter for all known senders.

**When using Gmail's separate `From` field**, enter alternatives without commas:

```text
jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com OR itviec+jobrobot+1@itviec.com OR itviec+discussion+4@itviec.com
```

Gmail serializes this as:

```text
from:(jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com OR itviec+jobrobot+1@itviec.com OR itviec+discussion+4@itviec.com)
```

**When using Gmail's main search bar**, use the equivalent complete query:

```text
{from:jobalerts-noreply@linkedin.com from:jobs-noreply@linkedin.com from:itviec+jobrobot+1@itviec.com from:itviec+discussion+4@itviec.com}
```

Do not use comma-separated senders: Gmail can accept the filter but match no mail. Before saving, confirm Gmail reports a nonzero count in **“Also apply filter to N matching conversations”** if historical alerts exist.

Check both actions:
- **Apply the label: `Job`**
- **Skip the Inbox (Archive it)**

This silences notifications while preserving the emails in the `Job` folder for scanning.

## Phase 2: Email Parsing Patterns

### LinkedIn Job Alerts format

Each digest email contains multiple jobs separated by `---------------------------------------------------------` (30+ dashes). Each job block follows this structure:

```
Role Title
Company Name
Location
[optional: "This company is actively hiring"]
[optional: "N connections"]
Apply with resume & profile
View job: https://www.linkedin.com/comm/jobs/view/NNNNNNNN/...
```

**Parsing approach:**
1. Split body by `-{30,}` to get individual job blocks
2. Skip blocks containing "Your job alert", "See all jobs", "Job search smarter"
3. First line = role, second line = company, third line = location (skip metadata lines)
4. Extract URL from `View job:` line; strip query params for dedup key

**Pitfall:** `jobs-listings@linkedin.com` emails also match the same structure but the first block may contain email header text. Skip blocks that look like headers (`To:`, `From:`, `Subject:`).

### ITviec Job Robot format

Each email contains multiple jobs with this structure:

```
Job N: Role Title
Employer: Company Name
Salary: range (e.g. "800 - 2,500 USD")
Required Skills: skill1 • skill2 • skill3
```

**Parsing and collection approach:**
1. Split by `*{30,}` or process the whole plain-text body.
2. Match lines with `Job \d+ : (.+)`, `Employer : (.+)`, `Salary : (.+)`.
3. Export the raw `.eml` and decode it with Python's MIME parser before inspecting the HTML part. Some ITviec messages use base64 transfer encoding; regex over raw `.eml` text silently loses every job URL in those messages.
4. Extract each `https://links.itviec.com/ls/click?...` tracking URL from its HTML job-title anchor.
5. Match HTML anchors to plain-text jobs using recursively HTML-decoded, whitespace-normalized, case-folded titles. ITviec can encode the plain-text title as `&amp;amp;` while the HTML title uses `&amp;`; direct string comparison silently loses URLs.
6. Collect the public listing through `opencli itviec job-public-detail <url> -f json`. The local adapter follows tracking redirects, verifies the final ITviec path and JSON-LD breadcrumb, and returns availability, canonical URL, title, company, location, dates, salary, skills, apply URL, and description.
7. Treat HTTP 410 as `closed` and HTTP 404 as `unavailable`. Map `Saved`/`To Apply` to `No Accept Apply`, while preserving statuses such as `Applied` and `Interviewing`.
8. Store the canonical `/it-jobs/<slug>` URL in `Job URL`. Use the structured Notes fingerprint as the fallback identity when no URL can be matched.
9. Write an idempotent Obsidian note under `/mnt/d/Obsidian/40 Resources/Job Tracking/ITviec Jobs/` and regenerate `ITviec Jobs.md`.

### Location normalization

Map raw location strings to Notion select options:

| Raw pattern | Notion option |
|---|---|
| "District 1", "Quận 1", "Q1" | HCMC - District 1 |
| "District 2", "Thu Duc", "Thủ Đức" | HCMC - District 2 / Thu Duc |
| "District 7", "Quận 7" | HCMC - District 7 |
| "Ho Chi Minh", "Hồ Chí Minh", "HCM", "Saigon" | HCMC - Other |
| "Hanoi", "Hà Nội", "Ha Noi" | Other City |
| "Remote" | HCMC - Remote |
| "Da Nang", "Đà Nẵng" | Other City |

### Role normalization

Map raw titles to Notion select options. Key signals:

| Signal | Maps to |
|---|---|
| "senior", "sr", "sr." + "ai"/"ml"/"machine learning" | ML / AI Engineer |
| "senior", "sr", "sr." + "backend" | Backend Engineer |
| "senior", "sr", "sr." (generic) | Senior Software Engineer |
| "ai", "ml", "machine learning", "data scientist" | ML / AI Engineer |
| "backend", "back end", "back-end" | Backend Engineer |
| "full" + "stack" | Full-Stack Engineer |
| "devops", "sre" | DevOps / SRE |
| "principal", "staff" | Staff Software Engineer |
| "manager", "lead", "head" + "engineering"/"tech" | Engineering Manager |
| generic "engineer", "developer" | Software Engineer |
| fallback | Other |

### Company normalization

Normalize known aliases into canonical Company select names. Preserve an unknown parsed company name instead of collapsing it into `"Other"`; Notion accepts a select value by name when creating or updating a row and creates the option when needed.

- Keep `"Other"` only for an empty or unparseable company name.
- Notion rejects commas in select-option names. For unknown companies, create a readable comma-free select value (for example, `KMS Technology, Inc.` → `KMS Technology Inc.`), while retaining the exact source spelling in `Notes`.
- Match aliases longest-first so a specific taxonomy value, such as `FPT Software Career`, wins over a shorter overlap such as `FPT Software`.

## Phase 3: Incremental Scanning & Deduplication

### State tracking

A file at `~/.hermes/state/job-scan-last-id.txt` stores the last processed email ID. After each run, the script updates this to the max ID scanned.

### Deduplication

Before inserting, the script queries the Notion database for two identities:

1. **Normalized `Job URL`** — query parameters are stripped from stable direct job URLs. For `links.itviec.com/ls/click` tracking URLs, retain the full query token; stripping it would collapse every ITviec job to the same `/ls/click` key. Structured Notes still deduplicate repeated listings whose ITviec tracking token changes between emails.
2. **Structured Notes fingerprint** — canonicalized `Company`, `Role`, `Location`, and `Salary`. This is used when a listing has no stable URL, particularly ITviec alerts. HTML entities, case, and repeated whitespace are normalized before comparison.

A match on either identity is skipped. Generic or unstructured notes (for example, `HCMC office`) are not used as an identity, because they are not safe evidence that two jobs are the same.

**Critical ordering rule:** enrich/resolve a tracking URL before the final duplicate check, or compare both the pre-enrichment and post-enrichment identities. If deduplication checks the email tracking URL and raw fingerprint first, but the created page stores a canonical URL plus enriched location/salary, a retry will not match its own previous write and will create duplicate pages. Recompute the URL and Notes fingerprint after enrichment, check those canonical keys immediately before creation, and add the exact stored keys to the in-memory sets after creation. A regression test must process the same enriched email twice and assert zero creates on the second pass.

This makes re-running the script (or running with `--all`) idempotent. To clean up historical structured duplicates, run:

```bash
python3 ~/.hermes/scripts/job-scan.py --prune-duplicates
```

The cleanup archives older Notion pages and retains the latest by `created_time`; archiving is reversible from Notion's trash.

### Notion API version split

Critical distinction when implementing:

| Operation | API Version | Endpoint |
|---|---|---|
| Create pages (with typed properties) | `2022-06-28` | `POST /v1/pages` |
| Query data sources | `2025-09-03` | `POST /v1/data_sources/{id}/query` |

Using the wrong version on either operation causes silent failures or 400 errors.

### Backfill after a broken Gmail filter

If cron reports `0` new emails while matching sender alerts are in INBOX, diagnose Gmail routing first; the scheduler and scanner may be working correctly.

1. Correct the Gmail filter, retain the two actions above, and select **Also apply filter to N matching conversations** before clicking **Update filter**.
2. Verify that the `Job` folder now contains messages newer than the scanner checkpoint.
3. Preview the incremental run, loading the Hermes environment first:

   ```bash
   cd ~/.hermes
   set -a && . .env && set +a
   python3 scripts/job-scan.py --dry-run
   ```

4. Inspect parsed-job and duplicate-URL output. Then run `python3 scripts/job-scan.py` without `--dry-run`.

### Repairing Company values from existing Notes

Older rows can have `Company = Other` while `Notes` retains the authoritative parsed source, for example `Company: Breadstack | Role: ...`.

1. Query only rows whose current Company select is `Other`.
2. Extract the `Company:` segment from Notes and normalize it with the importer. PATCH only a usable result, so the job is idempotent.
3. Read back every PATCH response before counting it as updated, and keep to Notion's roughly three-requests-per-second rate limit.
4. Preserve the raw Notes value. It is the source of truth if aliases later need correction.
5. Re-query after the bulk update and report the remaining `Other` rows separately from rows that lacked a usable `Company:` source.

Do not overwrite non-`Other` Company values during this repair without a separate user-approved reconciliation rule.

## Phase 4: Cron Job

```bash
hermes cron create \
  --name "Daily Job Scan → Notion" \
  --schedule "0 9 * * *" \
  --script "scripts/job-scan.py" \
  --no-agent \
  --deliver local \
  --workdir ~/.hermes
```

Key decisions:
- `--no-agent`: script handles everything, no LLM needed
- `--deliver local`: output saved to disk; user checks Notion directly
- `--workdir ~/.hermes`: ensures relative paths in STATE_FILE resolve correctly

### Environment

The cron runtime inherits `~/.hermes/.env`. Ensure these are present:
```
NOTION_API_KEY=ntn_your_key_here
NOTION_KEYRING=0
```

## Script Reference

The pipeline is implemented in `scripts/job-scan.py`. See that file for full implementation. Key CLI flags:
- `python3 job-scan.py` — process new emails since last run
- `python3 job-scan.py --all` — process ALL emails in Job folder (idempotent)
- `python3 job-scan.py --dry-run` — show what would be inserted, don't insert

## Moving Stragglers

When the Gmail filter has been broken for a while, emails accumulate in the inbox that should be in the Job folder. To move them in bulk:

```bash
for eid in <id1> <id2> <id3> ...; do
  himalaya message move "Job" "$eid" --folder "INBOX"
done
```

Find straggler IDs with:
```bash
himalaya envelope list --folder "INBOX" from "linkedin"  # or "itviec"
```

## Himalaya Quirks

- **Folder context matters:** `message read` and `message move` require `--folder` when operating outside INBOX
- **JSON output:** The `from` field is an object `{"name": "Display Name", "addr": "email@example.com"}`, not a string
- **Search syntax:** `from "LinkedIn Job Alerts"` works for display name matching; the tokenizer treats multi-word names as a unit when quoted
- **Large emails may time out:** LinkedIn digest emails with many jobs can take 30-60s to fetch. Set generous timeouts and catch `TimeoutExpired` gracefully

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Emails missing "Job" tag | Gmail filter too narrow | Add all four sender addresses to filter |
| Filter stopped working | Sender address changed | Check raw From header with `himalaya message read` |
| Duplicate Notion entries | URL normalization issue | Check that query params are stripped before comparison |
| Notion 400 on query | Wrong API version | Use `2025-09-03` for data source queries |
| Notion page created without select values | Wrong API version on page creation | Use `2022-06-28` for typed properties |
| Company always "Other" | Company not in pre-populated select options | User must add company in Notion UI (API can't add select options) |
| himalaya read returns empty | HTML-only email, no text part | Use `--folder "Job" message read` for correct folder context |
