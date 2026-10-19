---
name: llm-observability
description: Set up and verify fail-open LLM telemetry delivery.
version: 0.1.0
author: Delus, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [opentelemetry, llm, telemetry, exporter, debugging]
    related_skills: [agent-observability, use-phoenix, use-agentsview]
---

# LLM Observability

Plan and verify instrumentation and exporter changes across agent, model, tool, and runtime boundaries. Use `agent-observability` for incident interpretation and `use-phoenix` for backend-specific read-only queries. This skill does not assume an exporter is installed or authorize telemetry changes.

## When to Use

Use when setting up or repairing LLM traces, span propagation, exporter delivery, sampling, redaction, or fail-open behavior. Do not use a dashboard's absence alone as proof that no model request occurred.

## Prerequisites

Identify the application/profile, process owner, configured exporter, destination project, transport, and trace retention. Load `hermes-agent` and its matching configuration reference for Hermes changes; load `systematic-debugging` before editing. Verify current keys and settings from local configuration without printing secrets.

## How to Run

1. Define the desired signal and success criterion at each scope: session, turn, model/provider request, tool invocation, and gateway/plugin event. Keep native session/turn/tool IDs, trace/span IDs, parent IDs, timestamps, model, provider, status, and retry attempt where available.
2. Establish a bounded baseline with one known successful operation. Locate its source event and destination trace through the configured MCP backend. Record the newest trace timestamp and ingestion lag; discover MCP schemas rather than guessing tool names.
3. Trace the pipeline from instrumentation to batching/export, endpoint, authentication, ingestion, and query. Distinguish source omission, exporter error, delayed ingestion, wrong project, retention, and backend outage. Never label export failure as a model/provider failure without correlated evidence.
4. Design the smallest reversible change. Preserve context propagation across asynchronous and tool boundaries, avoid duplicate root spans, and specify which source owns each field. Make sampling and payload redaction explicit. Prompts, responses, headers, credentials, sender identifiers, and tool payloads must not be exported by default.
5. Obtain authorization before changing runtime configuration or deployment. Add a regression test or deterministic local probe for the exact missing signal, apply one change, and exercise a controlled model/tool operation.
6. Query the destination by stable trace ID and verify the expected parent-child structure, timestamps, status, and attributes. Compare with the baseline. Independently verify that a temporarily unavailable observer does not prevent the primary operation from completing; do not cause a production outage to run this test.

## Pitfalls

- Total trace duration is not time to first byte; record TTFB only when measured explicitly.
- Long-lived root/session spans are not necessarily slow provider requests.
- Parallel tools overlap; summed tool duration is not wall time.
- Incomplete parent trees can reflect propagation, retention, or ingestion delay; inspect settled traces before deciding.
- Backend project names do not prove agent-profile attribution.

## Verification

A completed setup produces one real, source-linked trace with expected child spans and safe attributes, plus a controlled fail-open result. If backend access or authorization is missing, report that verification as blocked rather than claiming completion.
