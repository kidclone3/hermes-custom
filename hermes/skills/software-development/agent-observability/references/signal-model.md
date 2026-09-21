# Agent Observability Signal Model

Use this reference to normalize evidence from session analytics, traces, and runtime logs.

## Required Record Fields

Every observation should preserve:

- `source`: AgentsView, Phoenix, Hermes log, runtime, or another named source.
- `observed_at`: timestamp and timezone.
- `session_id`: native agent session identifier when available.
- `turn_id` or `message_id`: turn boundary when available.
- `trace_id` and `span_id`: distributed trace identity when available.
- `tool_use_id`: invocation identity, not only tool name.
- `model` and `provider`: exact runtime values.
- `event_type`: session, turn, model request, tool, gateway, plugin, or exporter.
- `start`, `end`, and `duration`: preserve intervals rather than only totals.
- `status`: success, error, cancelled, interrupted, timeout, unknown, or source-native value.
- `attributes`: source-native fields needed to audit the interpretation.

Never invent a missing identifier. Record the correlation method and confidence when joining by timestamp.

## Latency Decomposition

Prefer this decomposition when the data permits:

```text
turn elapsed
├── queue or gateway delay
├── prompt assembly
├── provider time to first byte
├── provider streaming/generation
├── tool execution intervals
├── user/approval wait
├── plugin/exporter overhead
└── unobserved gap
```

Parallel intervals overlap. Calculate elapsed time from interval unions, not by summing call durations.

## High-Signal Abnormal Patterns

- **Silence:** an expected progress, first-byte, completion, or heartbeat event is absent before its deadline.
- **Retry amplification:** retries occur at more than one layer and multiply total attempts or delay.
- **Failure streak:** consecutive calls fail at the same boundary without a changed input or recovery action.
- **Loop:** semantically equivalent model or tool actions repeat without reducing uncertainty or changing state.
- **Orphan:** a start event or span lacks a terminal status after the allowed lifecycle window.
- **Latency outlier:** duration exceeds the relevant peer cohort percentile or a service objective.
- **Context anomaly:** reported context exceeds the model limit, grows contrary to compaction, or conflicts across fields.
- **Cost anomaly:** tokens or cost change materially against a comparable successful cohort.
- **Observer interference:** plugin, callback, flush, or exporter latency appears on the primary execution path.
- **Lifecycle inflation:** wall duration is dominated by inactivity, delayed closure, or a missing end event.

## Evidence Confidence

- **High:** stable identifier correlation and complete intervals from the authoritative layer.
- **Medium:** exact timestamp and matching model/provider/tool identity, but no shared identifier.
- **Low:** heuristic score, text similarity, display name, or coarse time bucket only.

A low-confidence signal can select the next query. It cannot establish root cause.

## Minimal Baselines

Choose the closest available comparator:

1. Same operation, model, provider, and tool in recent successful sessions.
2. Same model/provider across similar session archetypes.
3. Historical percentile for the same signal and environment.
4. Explicit service objective when no representative history exists.

Record cohort filters, sample size, and exclusions. Do not compare interactive user waits with automated execution.

## Privacy and Reliability

Begin with metadata-only capture. Enable prompt, response, conversation, tool payload, or sender previews only when required and approved. Redact secrets before durable storage or reports. Keep exporters asynchronous and bounded; exporter outage, backpressure, or flush failure must not fail the agent operation.
