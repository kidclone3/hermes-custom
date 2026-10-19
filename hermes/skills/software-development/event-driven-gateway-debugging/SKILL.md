---
name: event-driven-gateway-debugging
description: Diagnose Hermes gateway delivery and reconnect failures.
version: 0.1.0
author: Delus, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes, gateway, delivery, reconnect, debugging]
    related_skills: [agent-observability, use-agentsview, use-phoenix]
---

# Event-Driven Gateway Debugging

Investigate Hermes gateway, adapter, browser-control, and delivery incidents using bounded event timelines. This skill is a diagnostic procedure, not authority to restart a gateway or change production configuration.

## When to Use

Use for Telegram or other adapter reconnect loops, duplicate or missing deliveries, registration errors, plugin interruptions, and gateway lifecycle anomalies. Use `agent-observability` to correlate sessions and traces; load `systematic-debugging` before making a fix.

## Prerequisites

Identify the active Hermes profile, gateway owner, affected channel, and exact incident window with timezone. Load `hermes-agent` and its relevant gateway/configuration reference before relying on any Hermes-specific setting. Treat logs, requests, and message bodies as sensitive.

## How to Run

1. Record the expected event path and actual failure, including a stable message, delivery, request, or session ID if available. Freeze an observation cutoff for an ongoing incident.
2. Inspect the gateway's read-only process/listener state and timestamp-bounded logs via `terminal` and `read_file`. Identify the canonical log and avoid counting mirrored agent/error copies as independent failures. Do not dump raw payloads into the report.
3. Build a sequence across ingress, routing, adapter request, response/acknowledgment, retries, reconnect, and delivery. Preserve exact timestamps, attempt IDs, status codes, and component names. A successful reconnect is not proof that every message was delivered.
4. Compare one failed path with a nearby successful path on the same adapter and profile. Distinguish DNS/transport, authentication, route lookup, request-contract rejection, queueing, and process shutdown boundaries.
5. For an HTTP route anomaly, use a bounded, read-only method probe only where safe. A GET 405 with `Allow: POST` establishes route presence, not POST registration correctness; inspect a redacted real failure and handler contract before assigning cause. Never submit synthetic registration or mutate state as a diagnostic shortcut.
6. Correlate gateway timestamps with AgentsView lifecycle and Phoenix trace IDs where available. Missing telemetry is a coverage gap, not evidence that the primary operation failed. Form falsifiable hypotheses with an inexpensive discriminating probe.
7. Before remediation, obtain authorization for the affected profile and state change, establish a red-capable repro, and verify existing active sessions. After an authorized change, exercise the original path and read back a delivery/registration acknowledgment. Test that observer unavailability does not block primary delivery.

## Pitfalls

- Adapter restart and gateway restart are distinct events; identify which process changed.
- Repeated 404 or retry lines may share one cause and may be duplicated across logs.
- Avoid logging credentials, sender identifiers, message text, browser registration payloads, and raw trace bodies.
- Do not restart a gateway solely to gather evidence.

## Verification

A read-only investigation has a bounded timeline, a named successful comparator, a specific failing boundary, explicit evidence gaps, and one executed safe probe. A fix is complete only after the original operation succeeds and its destination or registration state is independently read back.
