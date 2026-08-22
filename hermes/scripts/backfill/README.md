# Job backfill utilities

These scripts are reusable operational utilities that were originally authored under `~/.hermes/cache/`. Their source is versioned here. The installer keeps the old cache entrypoints as symlinks so historical commands continue to work.

Generated manifests, collected job descriptions, checkpoints, results, backups, email-derived data, and Notion payloads remain in `~/.hermes/cache/` and are deliberately excluded from Git.

## Utilities

| Script | Purpose | Side effects |
|---|---|---|
| `query_linkedin_jobs.py` | Query LinkedIn-source rows from the Notion Job Tracking data source | Writes `linkedin-jobs-manifest.json` in the runtime cache |
| `collect_linkedin_job_details.py` | Collect identity-verified LinkedIn details through OpenCLI | Writes LinkedIn detail/error cache files |
| `enrich_linkedin_jobs.py` | Backfill LinkedIn details and availability into Notion | Writes Notion pages and a JSONL checkpoint |
| `export_linkedin_jobs_to_obsidian.py` | Export collected LinkedIn jobs into Obsidian notes and an index | Writes Obsidian notes and an export manifest |
| `repair_flat_linkedin_notion.py` | Detect and repair flattened LinkedIn descriptions in Notion | Read-only by default; writes Notion only with `--apply`; always updates its runtime backup file |
| `enrich_itviec_jobs.py` | Backfill verified ITviec details into Notion and Obsidian | Supports `--dry-run`; otherwise writes Notion, Obsidian, and a JSONL checkpoint |

## Runtime data dependencies

The scripts intentionally read and write these unversioned runtime artifacts:

```text
~/.hermes/cache/linkedin-jobs-manifest.json
~/.hermes/cache/linkedin-job-details-cache.json
~/.hermes/cache/linkedin-job-details-errors.json
~/.hermes/cache/linkedin-job-enrichment-results.jsonl
~/.hermes/cache/obsidian-linkedin-job-export.json
~/.hermes/cache/flat-linkedin-notion-backup.json
~/.hermes/cache/itviec-job-details-cache.json
~/.hermes/cache/itviec-job-enrichment-results.jsonl
```

They also require the normal Hermes environment and integrations, including `NOTION_API_KEY`, OpenCLI, and the active job scanner.

## Safety

Run query/collection stages before enrichment. Review dry-run or inventory output before any Notion write. Do not copy generated runtime artifacts into this repository: they contain job descriptions, Notion identifiers, source URLs, and potentially email-derived data.
