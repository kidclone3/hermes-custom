---
name: honcho-config-audit
description: Use when auditing Hermes Honcho profile configuration.
version: 0.1.0
author: Duy Bui, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [honcho, hermes, profiles, discord, memory, audit]
    related_skills: [hermes-agent]
---

# Honcho Configuration Audit

Audit a live Hermes/Honcho deployment across profiles, bots, and gateway identities. Default to read-only inspection, protect credentials, and distinguish technical validity from whether the identity and isolation model matches the user's intent.

## When to Use

Use when the user asks whether Honcho is configured correctly, wants to review multiple Hermes profiles or Discord bots, reports mixed user memories, or plans a company deployment.

Do not use for general Honcho application development or to change production configuration without explicit approval. Route SDK or application-integration work to an application-engineering or software-development workflow.

## Safety Rules

1. Treat `.env`, `honcho.json`, `auth.json`, bot tokens, bearer tokens, and workspace keys as secrets. Never print their values or suffixes. Report only presence, absence, equality/conflict, source profile, and stable internal labels such as `credential-A`.
2. Audit before changing anything. Do not run setup, sync, migrate, enable, disable, reset, or config-write commands unless the user explicitly asks for remediation.
3. Resolve every profile through Hermes. Never assume the default home applies to named profiles or hardcode `~/.hermes` as an active profile home.
4. Treat Honcho scopes as recall boundaries, not authorization. Discord permissions, gateway allowlists, application policy, and separate workspaces enforce access boundaries.
5. Verify current behavior from the installed Hermes CLI and official docs when commands or keys differ from this skill.

## Audit Procedure

### 1. Establish intent and topology

Record the intended mapping before judging configuration:

- Which Hermes profiles represent distinct bots or agent roles?
- Which agents should share memory, and which must be isolated?
- Is each profile personal, multi-user, or bot-to-bot?
- Which Discord servers, channels, departments, clients, or environments form confidentiality boundaries?
- Should one human retain one identity across several bots or platforms?

Infer obvious answers from profile names and gateway configuration. Ask only where the missing answer changes whether sharing is correct. Completion: every profile has an intended role, audience, and isolation boundary, with unknowns labeled.

### 2. Inventory live Hermes state

Use `terminal` to run read-only commands supported by the installed version:

```text
hermes --version
hermes profile list
hermes gateway list
hermes gateway status
hermes memory status
```

For every discovered named profile, run the equivalent commands with `hermes -p <profile>`. Also inspect command availability with `hermes honcho --help` or `hermes memory --help` before relying on a subcommand.

Use `hermes config get` for specific non-secret settings instead of dumping whole configuration. Relevant settings include `memory.provider`, gateway multiplexing, enabled platforms, Discord policy, and terminal isolation. Never print an entire environment file.

Completion: the report accounts for every profile, its active memory provider, its gateway ownership, and whether it is currently served.

### 3. Inspect Honcho configuration per profile

When Honcho is active, run read-only commands such as:

```text
hermes -p <profile> honcho status
hermes -p <profile> honcho peers
hermes -p <profile> honcho sessions
```

If the installed version lacks one command, inspect `$HERMES_HOME/honcho.json` with `read_file` only after resolving that profile's actual home. Redact secrets from notes and output. The global `~/.honcho/config.json` may be a fallback; identify whether each profile uses global or profile-local configuration.

Check:

- provider is actually `honcho`, not merely configured but inactive;
- endpoint/cloud-vs-local selection and connectivity;
- workspace identity and whether sharing is intentional;
- unique AI peer identity for each Hermes profile;
- stable human peer mapping across surfaces where desired;
- `recallMode`, token budget, cadence, timeout, write frequency, and session strategy;
- observation mode or explicit user/AI observation flags;
- gateway-only identity keys: `pinUserPeer`, `userPeerAliases`, `runtimePeerPrefix`, and `a2aSessions`;
- legacy `pinPeerName` and other migration residue;
- local/server-side configuration divergence, because server-side observation settings can win at session initialization.

Completion: every relevant key is classified as correct, risky, incorrect, intentional exception, or unknown.

### 4. Validate identity resolution

Apply the gateway resolver in order:

```text
pinUserPeer
→ userPeerAliases[runtime_id]
→ runtimePeerPrefix + runtime_id
→ raw runtime_id
→ peerName
→ session-key fallback
```

Flag these high-risk patterns:

- `pinUserPeer: true` on a gateway used by multiple humans;
- two employees aliased to the same peer;
- one employee fragmented into unrelated peer IDs when continuity is intended;
- mutable usernames or display names used instead of stable Discord snowflakes;
- changing from pinned to unpinned without a migration plan for existing memory;
- bot-authored turns attributed to a human peer;
- empty `runtimePeerPrefix` where IDs from several platforms could collide.

For a company Discord deployment, the normal baseline is `pinUserPeer: false`, one peer per Discord user ID, and a Discord-specific prefix or explicit aliases. Completion: show at least three synthetic or consistently redacted runtime IDs and their resolved peer IDs without exposing personal identifiers or private message content.

### 5. Validate workspace, session, and privacy boundaries

Use Honcho's model correctly:

- Workspace: hard data-isolation boundary.
- Peer: persistent person, agent, or entity.
- Session: active conversational context, such as a Discord channel, thread, DM, task, or import.
- Scope/session allowlist: recall restriction, not authorization.

Flag profiles that should collaborate but accidentally use separate workspaces. Flag HR, legal, client, production, or regulated contexts sharing one workspace when policy requires hard isolation. Check that stable gateway per-chat sessions do not collapse unrelated channels or users.

Completion: produce an explicit desired-versus-observed mapping for workspaces, AI peers, human peers, and sessions.

### 6. Validate multi-profile Discord and gateway operation

Check that every Discord-enabled profile has its own bot credential. Compare credentials only by a one-way hash or secure equality test; never print tokens or hashes that could aid credential recovery. Detect duplicate credentials, disabled or parked adapters, missing allowlists, unsafe allow-all settings, mention policy surprises, and profiles not served by the host gateway.

For multiplexing, verify that one host gateway serves the expected profiles and that secondary profiles are not incorrectly running independent gateways. Confirm each routed turn keeps the owning profile's config, memory, skills, allowlists, and outbound bot identity.

Completion: every enabled Discord bot has a unique owning profile, unique credential, explicit audience policy, and observed gateway status.

### 7. Exercise the configuration safely

Static configuration is insufficient. With user approval for test messages, use non-sensitive canary identities and verify:

1. Two Discord users resolve to two distinct human peers.
2. The same authorized user reaches the intended stable peer through two configured bots when continuity is desired.
3. Each Hermes profile retains a distinct AI peer.
4. A forbidden channel or user is rejected by the gateway policy.
5. A synthetic sentinel stored in a disposable confidential test workspace cannot be recalled from a general test workspace. Never probe for or reproduce real confidential memory.
6. Bot-to-bot messages use A2A sessions rather than contaminating human memory.

If live Discord testing is unavailable, mark these checks unverified rather than inferring success. Completion: each canary has observed evidence or an explicit unverified status.

## Findings Format

Report:

```text
HONCHO CONFIG AUDIT
Overall: PASS | PASS WITH RISKS | FAIL | INCOMPLETE

Topology
Observed: ...
Intended: ...
Unknowns: ...

Profile matrix
Profile | Role | Provider | Workspace | AI peer | Human mapping | Gateway | Result

Findings
ID | Severity | Evidence | Impact | Recommended correction

Identity examples
Runtime identity | Resolution path | Resulting peer | Expected

Verification
Static checks: ...
Connectivity checks: ...
Live canaries: ...

Remediation order
1. Security and cross-user leakage
2. Workspace isolation
3. Duplicate bot/gateway ownership
4. Identity continuity
5. Cost, cadence, and quality tuning
```

Use severity `critical` for demonstrated cross-user or cross-boundary disclosure, `high` for a configuration likely to cause it, `medium` for broken continuity or duplicate processing, and `low` for cost or quality tuning.

## Remediation

Propose the smallest reversible correction. Prefer `hermes config set`, `hermes memory setup`, and supported `hermes honcho` or `hermes gateway` commands over direct file edits. Show commands before executing them. Changes to peer IDs, workspace IDs, pinning, aliases, or observation behavior may strand or reinterpret existing memory; require explicit confirmation and a migration/rollback plan.

For identity migrations, define five stages: snapshot the current mapping without exposing credentials; prepare the old-to-new peer map; validate with synthetic canaries; roll out to a limited bot or audience; then validate and expand. State rollback criteria and preserve the old mapping until the limited rollout passes.

After approved changes, repeat the inventory, identity-resolution checks, connectivity check, and relevant canaries. Never claim success from a write command alone.

## Pitfalls

- A configured API key does not prove Honcho is the active provider.
- Sharing a workspace does not automatically mean sharing an AI peer; Hermes profiles should retain distinct AI identities.
- Separate Hermes profiles are state isolation, not filesystem sandboxes.
- `sessionStrategy` does not override stable messaging-gateway chat sessions.
- `contextTokens` and cadence settings are irrelevant to automatic injection in `tools` mode.
- `initOnSessionStart: true` can block startup when a local Honcho server is unavailable.
- Switching `pinUserPeer` off does not migrate memories accumulated under `peerName`.
- A successful gateway process can still have one duplicate Discord adapter parked.

## Verification

An audit is complete only when all discovered profiles are included, no secret values appear in the artifact, intended identity/isolation decisions are explicit, static and runtime evidence are separated, and every finding has a concrete correction plus a verification step.
