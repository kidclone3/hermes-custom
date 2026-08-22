# Repository Rules

- Use `uv run python3` for Python commands. Do not use pip.
- Keep credentials, `.env`, raw email, Notion payload caches, and tracking URLs out of Git.
- Treat this repository as the canonical source. Active files under `~/.hermes` and `~/.opencli` are installed as symlinks by `tools/install-runtime.sh`.
- Do not commit mutable Hermes state, cron output, OpenCLI traces, generated job notes, or backfill caches.
- Run `bash tools/verify.sh` after changes. Use `--live` only when the required environment and services are available.
- After the initial repository commit, make code changes in a Git worktree rather than directly on `main`.
