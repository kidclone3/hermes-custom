import json
import re
import subprocess
import time
from pathlib import Path

MANIFEST = Path("/home/delus/.hermes/cache/linkedin-jobs-manifest.json")
CACHE = Path("/home/delus/.hermes/cache/linkedin-job-details-cache.json")
ERRORS = Path("/home/delus/.hermes/cache/linkedin-job-details-errors.json")
BATCH_SIZE = 25

jobs = json.loads(MANIFEST.read_text(encoding="utf-8"))
cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
errors = json.loads(ERRORS.read_text(encoding="utf-8")) if ERRORS.exists() else {}


def job_id(url):
    match = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", url or "")
    if not match:
        raise ValueError(f"Unsupported LinkedIn URL: {url}")
    return match.group(1)


def canonical(url):
    return f"https://www.linkedin.com/jobs/view/{job_id(url)}/"


def save():
    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    ERRORS.write_text(json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8")


def run_batch(batch, attempt=1):
    urls = ",".join(canonical(job["job_url"]) for job in batch)
    proc = subprocess.run(
        ["opencli", "linkedin", "job-public-detail", urls, "--format", "json"],
        text=True,
        capture_output=True,
        timeout=180,
    )
    if proc.returncode != 0:
        message = (proc.stdout.strip() or proc.stderr.strip() or f"exit {proc.returncode}")[:2000]
        if len(batch) > 1:
            midpoint = len(batch) // 2
            run_batch(batch[:midpoint])
            run_batch(batch[midpoint:])
            return
        jid = job_id(batch[0]["job_url"])
        if attempt < 3:
            time.sleep(3 * attempt)
            run_batch(batch, attempt + 1)
        else:
            errors[jid] = message
            save()
        return

    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        if len(batch) > 1:
            midpoint = len(batch) // 2
            run_batch(batch[:midpoint])
            run_batch(batch[midpoint:])
            return
        jid = job_id(batch[0]["job_url"])
        errors[jid] = f"Invalid JSON: {exc}; output={proc.stdout[:1000]}"
        save()
        return

    expected = {job_id(job["job_url"]) for job in batch}
    returned = {str(row.get("job_id")) for row in rows if isinstance(row, dict)}
    if returned != expected:
        if len(batch) > 1:
            midpoint = len(batch) // 2
            run_batch(batch[:midpoint])
            run_batch(batch[midpoint:])
            return
        jid = next(iter(expected))
        errors[jid] = f"Identity mismatch: expected {sorted(expected)}, returned {sorted(returned)}"
        save()
        return

    for row in rows:
        jid = str(row["job_id"])
        cache[jid] = row
        errors.pop(jid, None)
    save()


pending = [job for job in jobs if job_id(job["job_url"]) not in cache]
for start in range(0, len(pending), BATCH_SIZE):
    batch = pending[start : start + BATCH_SIZE]
    run_batch(batch)
    print(json.dumps({
        "processed": min(start + len(batch), len(pending)),
        "pending_total": len(pending),
        "cache_count": len(cache),
        "error_count": len(errors),
    }), flush=True)
    time.sleep(0.5)

print(json.dumps({
    "manifest_count": len(jobs),
    "cache_count": len(cache),
    "error_count": len(errors),
    "missing_count": len({job_id(job["job_url"]) for job in jobs} - set(cache)),
    "cache": str(CACHE),
    "errors": str(ERRORS),
}, indent=2))
raise SystemExit(1 if errors else 0)
