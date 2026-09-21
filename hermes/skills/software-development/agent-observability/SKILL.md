---
name: agent-observability
description: Use when detecting abnormal LLM-agent behavior.
version: 0.1.0
author: Delus, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [agents, observability, anomalies, tracing, debugging]
    related_skills: [use-agentsview, use-phoenix, agent-runtime-observability, llm-observability, systematic-debugging, event-driven-gateway-debugging]
---

# Agent Observability

Investigate LLM-agent reliability and performance using correlated evidence rather than one dashboard score. This skill owns the vendor-neutral signal model, triage procedure, and evidence standard; backend-specific MCP operations belong to `use-agentsview` and `use-phoenix`.

## When to Use

Use for stalled turns, slow agents, failed tools, retry loops, context growth, unexpected cost, incomplete tasks, gateway interruptions, or unexplained differences between wall time and active work.

Do not use this skill alone to implement telemetry exporters or modify observability infrastructure. Load `llm-observability` for instrumentation changes and `systematic-debugging` before applying a fix.

## Core Model

Observe five connected scopes:

1. **Session** — lifecycle, outcome, active duration, health, and abandonment.
2. **Turn** — user wait, reasoning, model wait, tool activity, and completion.
3. **Model request** — provider, model, time to first byte, duration, retries, tokens, and errors.
4. **Tool invocation** — unique call ID, arguments category, duration, result status, and side effects.
5. **Runtime boundary** — gateway events, plugins, queues, exporters, reconnects, and process state.

Preserve session IDs, trace/span IDs, message/turn IDs, tool-use IDs, timestamps, model, provider, and source system. Never merge records merely because names match.

Read `references/signal-model.md` when selecting metrics, anomaly rules, or a normalized evidence format.

## Backend Routing

Load backend skills explicitly with `skill_view`; `related_skills` metadata does not execute them.

- Session history, tool behavior, lifecycle, active time, churn, or session-level health: load `use-agentsview`.
- Provider/API spans, TTFB, retries, model latency, OTLP export, or trace hierarchy: load `use-phoenix`.
- Cross-layer or unclear incidents: load both and correlate by stable IDs and timestamps.
- Runtime supervision, PTY/ACP architecture, status authority, dashboards, or session restoration: load `agent-runtime-observability`.
- Gateway, attachment, interrupt, or delivery paths: also load `event-driven-gateway-debugging`.

If the required MCP server is unavailable, report the missing evidence source. Do not silently replace MCP evidence with guesses.

## Procedure

1. **State the symptom.** Record expected behavior, observed behavior, affected surface, and impact. Completion: the incident can be disproved by a concrete observation.
2. **Snapshot and bound the incident.** Capture the exact session/turn state before cohort analysis. Record timezone, start timestamp, immutable observation-time cutoff for an ongoing incident, session identifier, model, provider, and relevant deployment/configuration change. Completion: later queries cannot drift the original incident window.
3. **Route exact evidence collection.** Load `use-agentsview`, `use-phoenix`, or both according to Backend Routing. Inspect the exact session/trace first, then gather aggregate comparisons. Completion: each material claim has a source record.
4. **Establish a baseline.** Compare with similar successful sessions or the same operation under normal conditions. Prefer percentiles and peer cohorts over arbitrary universal thresholds. Completion: the claimed anomaly has a named comparator.
5. **Normalize the timeline.** Separate user wait, agent computation, model/provider wait, tool execution, exporter delay, and inactive wall time. Completion: overlapping and missing intervals are explicit.
6. **Detect abnormal patterns.** Check latency outliers, silence, retry amplification, consecutive failures, loops, orphaned spans, missing completion events, context pressure, token/cost changes, and instrumentation gaps. Treat absence of an expected event as evidence, not proof of its cause.
7. **Correlate boundaries.** Join records using stable IDs first, then exact timestamp windows plus model/provider/tool identity. Never correlate on display names alone. Completion: the suspected causal path is ordered end to end or marked with a specific gap.
8. **Rank hypotheses.** Produce up to five hypotheses, but include only hypotheses that are falsifiable and supported enough to justify a probe. State predictions and the cheapest discriminating probe. Load `systematic-debugging` before changing runtime behavior. Completion: the leading hypothesis has evidence for and against it.
9. **Verify resolution when authorized.** For a read-only investigation, stop after the evidence-backed next probe. Run a controlled reproduction or change runtime state only with explicit user authorization, then compare it with the baseline and verify the primary operation still works when telemetry is unavailable. Completion: the authorized success criterion is exercised without observer interference.

## Evidence Rules

- Separate facts, derived measurements, hypotheses, and unknowns.
- Do not call a health grade, heuristic signal, or duration bucket a root cause.
- Distinguish wall time from active time and user wait from agent latency.
- Do not infer provider TTFB from total turn duration.
- Parallel tool durations may overlap; do not sum them as elapsed time without interval data.
- Validate declared totals programmatically when enumerating records.
- Treat prompts, responses, tool inputs/results, sender IDs, and trace payloads as sensitive.
- Telemetry must fail open: an unavailable observer must not block the agent.

## Report Format

```text
Incident: <bounded symptom>
Window/timezone: <start> to <end>, <timezone>
Scope: <sessions, traces, models, providers>
Baseline: <comparison cohort>

Observed facts:
- <claim> — source: <backend and stable identifier>

Derived measurements:
- <calculation, source records, method>

Abnormal signals:
- <signal, measured value, baseline, confidence>

Timeline:
- <timestamp/range, layer, event, duration>

Correlation:
- <records joined, method, confidence>

Hypotheses:
1. <cause> — predicts <testable observation>

Evidence gaps:
- <missing span/event/attribute>

Next probe or verified fix:
- <one discriminating action and success criterion>
```

## Pitfalls

- Using one backend as the complete truth.
- Treating an open session as continuous work.
- Treating user response time as model latency.
- Counting repeated display names as one tool invocation.
- Mistaking telemetry exporter errors for provider errors without correlation.
- Exporting full prompts or secrets merely to make debugging easier.

## Verification

A completed investigation includes a bounded incident, baseline, normalized timeline, source identifiers, ranked hypotheses, explicit evidence gaps, and one executed discriminating probe. A completed fix also includes a controlled successful turn and proof that observer failure does not break the primary agent path.
