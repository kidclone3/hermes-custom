## 2026-08-22 by Hermes
- ITviec public listings are server-rendered Pattern C pages with no observed anti-bot challenge or JSON XHR dependency.
- Active pages expose schema.org `JobPosting` JSON-LD containing title, company, location, dates, salary, skills, description, benefits, and apply URL.
- `links.itviec.com` email links redirect to canonical `/it-jobs/<slug>` pages. Verify the final host/path and JSON-LD BreadcrumbList path to fail closed on identity drift.
- Expired listings return HTTP 410 rather than HTTP 200. Treat 410 as `closed`; treat 404 as `unavailable`.
