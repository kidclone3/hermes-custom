---
name: use-phoenix
description: Query Phoenix MCP for LLM trace and span anomalies.
version: 0.1.0
author: Delus, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [phoenix, mcp, opentelemetry, traces, llm]
    related_skills: [agent-observability, systematic-debugging]
---

# Use Phoenix

Use the configured Phoenix MCP server to inspect OpenTelemetry projects, traces, spans, latency, model calls, tool calls, and export health. This skill is an MCP execution adapter; `agent-observability` owns incident correlation and diagnosis.

## When to Use

Use for provider/model latency, LLM request spans, time to first byte, retries, token usage, exceptions, incomplete traces, span hierarchy, tool spans, and read-only verification that already-configured Hermes OTel traces reached Phoenix.

Do not use Phoenix to infer session lifecycle facts that are absent from spans. Pair it with `use-agentsview` when the incident crosses session and provider boundaries. For exporter setup, configuration changes, instrumentation implementation, or delivery repair, use the installed `hermes_otel:observability` skill when available and inspect the actual Hermes runtime before changing it.

## Prerequisites

A Phoenix MCP server must be configured and visible to Hermes, and the relevant Hermes project must be receiving traces. Exact MCP tool names and schemas must be discovered from the active server.

Use read-only queries by default. Dataset mutation, annotation, evaluation writes, or project changes require explicit approval and read-back verification.

## MCP Discovery

1. Call `tool_search` with a capability query covering Phoenix projects, traces, spans, sessions, attributes, and exceptions.
2. Select only tools whose source identifies the configured Phoenix MCP server.
3. Call `tool_describe` for every selected tool before invocation.
4. Map discovered tools to these capabilities: service/project discovery, bounded trace search, trace detail, span hierarchy, span attributes/events, errors, latency, and evaluations when requested.
5. If no Phoenix MCP tools are found, stop and report that the MCP adapter is unavailable. Do not invent tool names or claim that a UI/HTTP probe is MCP evidence.

Completion: every intended call has a loaded schema and verified Phoenix source.

## Procedure

1. **Verify coverage.** Query server/project availability and newest trace timestamp. Record project, clock/timezone, trace retention window, and ingestion delay. Completion: the target incident falls inside verified coverage or is marked missing.
2. **Locate candidates.** Search a narrow time range using exact session ID, trace ID, model, provider, operation name, status, or attributes supported by the MCP schema. Broaden one filter at a time when empty.
3. **Fetch full traces.** Retrieve the root and all relevant descendants. Preserve trace/span IDs, parent IDs, start/end timestamps, status, attributes, and events. Completion: the span tree is complete or a specific missing branch is recorded.
4. **Decompose latency.** Measure queue/gateway spans, prompt assembly, provider TTFB when explicitly recorded, provider generation, tool calls, retries, plugins, and exporter/flush work. Do not derive TTFB from total request duration.
5. **Inspect failures.** Record exception type/message safely, status, retry/attempt number, reconnect markers, cancellation, and the last successful span. Separate provider, tool, plugin, and exporter failures.
6. **Compare a baseline.** Query comparable successful traces for the same model/provider/operation. Record cohort filters, sample size, and percentile or representative values.
7. **Detect instrumentation gaps.** Look for orphan spans, missing terminal status, broken parentage, missing session/model/provider attributes, clock skew, duplicate exports, and missing traces despite a known request.
8. **Return normalized evidence.** Use the output format below and pass it to `agent-observability` for correlation with AgentsView and Hermes logs.

## Privacy and Reliability

- Prefer metadata and attributes before requesting prompt, response, conversation, or tool payloads.
- Do not reproduce secrets, authorization headers, sender IDs, or unnecessary user content.
- Treat prompt/output previews as sensitive even when truncated.
- An unavailable exporter must not block or fail the primary agent path.
- A backend connection error proves export failure, not provider failure.

## Output Format

```text
PHOENIX EVIDENCE
Source/project: <MCP server, project>
Coverage: <newest trace, retention, ingestion delay>
Window/timezone: <bounded interval>
Filters/count: <query and verified results>

Trace path:
- <trace_id/span_id, parent, operation, start/end, status>

Latency breakdown:
- <layer, measured duration, baseline>

Errors/retries:
- <span ID, boundary, safe error class, attempt>

Instrumentation gaps:
- <missing span/attribute/terminal event>

Cross-backend keys:
- session ID, trace ID, timestamps, model/provider, tool-use ID
```

## Pitfalls

- Querying the wrong Phoenix project or time window.
- Confusing ingestion delay with a missing trace.
- Treating OTLP export failure as an LLM provider failure.
- Inferring retry count from duplicate-looking spans without attempt attributes.
- Reading only the root span and missing slow descendants.
- Exposing prompt or response content in reports without necessity.
- Falling back to undocumented endpoints while claiming MCP evidence.

## Verification

A successful run proves MCP connectivity, identifies the Phoenix project and coverage, retrieves at least one real trace with stable IDs, and verifies the queried span hierarchy. For a controlled Hermes test, verify the expected model/provider and tool spans appear and confirm Hermes still completes when the observer is unavailable. If MCP is absent, report the blocked verification explicitly.
