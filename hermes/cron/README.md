# Weekly Agent Observability Scan

`weekly-agent-observability.json` is a sanitized recreation reference from the existing default-profile job `70e6f9dd7f67`. It contains the full task prompt, schedule, ordered skills, pre-run script, toolsets, continuity, and session-attachment intent. It is **not** a Hermes `jobs.json` entry. Do not copy it into `~/.hermes/cron/jobs.json` or create a second job on a machine that already has this job.

## Prerequisites

- Run the repository installer against the intended profile. It copies `agentsview-preflight.sh` as a regular file inside that profile's `scripts/` directory; cron script containment does not accept a symlink into this repository. The script requires Bash, curl, pgrep, and an executable `~/.local/bin/agentsview`. It probes localhost ports 8081 and 8080 and may start AgentsView when absent.
- Verify all six `skills` listed in the JSON are resolvable in the target profile. This repository ships `agent-observability`, `use-agentsview`, `use-phoenix`, and `event-driven-gateway-debugging`. `agent-runtime-observability` and `hermes-agent` are external dependencies and must be installed separately. `llm-observability` is shipped for instrumentation work but is not one of this scheduled job's skills.
- Configure and verify the AgentsView and Phoenix MCP adapters for that profile; this repository does not carry credentials, MCP server configuration, or Phoenix storage. Check the exact MCP tool schemas at run time. A reachable local AgentsView HTTP endpoint is not proof that MCP discovery works.
- Select a delivery target, failure-delivery target, and absolute profile workdir appropriate to the destination machine. The source Telegram chat ID and runtime history are intentionally omitted.

## Recreate or update

First list jobs with `cronjob_manage(action="list")` or `hermes cron list`. If a matching job exists, inspect and update it rather than creating a duplicate. Otherwise create it through the supported `cronjob_manage` interface, using the JSON `name`, `schedule`, `prompt`, `skills`, `script`, `no_agent`, `enabled_toolsets`, `continuity`, and `attach_to_session` fields. Supply the selected `deliver`, `failure_deliver`, and absolute `workdir` explicitly. Do not pin a model unless requested. Do not run the job simply to test installation; that launches the full scan and may deliver a report.

The CLI `hermes cron create` supports the schedule, prompt, repeated `--skill`, `--script`, `--continuity`, and delivery/workdir flags. It does not expose every stored field in this snapshot (notably `enabled_toolsets` and `attach_to_session`), so use the cronjob tool if those fields must be reproduced exactly. Never rely on default delivery for a recreated job.

After creation/update, list the exact job and check enabled state, Sunday 09:00 schedule in the target local timezone (Asia/Ho_Chi_Minh on the source machine), six resolved skills, script, toolsets, continuity, workdir, destination, and next run. The source report's timestamps and job ID are not portable. A dry installer check validates links only; an actual future scheduled run is still required to verify end-to-end MCP and delivery behavior.
