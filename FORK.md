# About this fork

This is a fork of [`mckinsey/agents-at-scale-ark`](https://github.com/mckinsey/agents-at-scale-ark).
It carries one focused body of work on top of upstream Ark: a **Substrate execution backend**
and the **human-in-the-loop (HITL) tool-approval** support it needs.

For the upstream project overview, see [README.md](README.md). This document explains only
what the fork adds and how it is organized.

## Purpose

Upstream Ark runs an agent's turn in an in-cluster executor (the default `completions`
executor, a normal Kubernetes Deployment). This fork adds a second, **sandboxed** execution
tier: agents can run as [Agent Substrate](https://github.com/agent-substrate/substrate) actors
(gVisor sandboxes) instead of plain pods, with per-agent egress policy and credential isolation.

Sandboxing is **per-agent opt-in** via the existing routing mechanism — nothing global changes:

- Agent `spec.executionEngine` **unset** → default `completions` executor (non-sandboxed tier).
- Agent `spec.executionEngine: substrate` → this fork's executor (sandboxed-actor tier).

The two tiers coexist; agents that don't opt in are untouched.

## What the fork adds

All fork work lives on the **`feat/substrate-exec-engine`** branch.

| Path | What it is |
| --- | --- |
| `services/ark-substrate-executor/` | An A2A `ExecutionEngine` (built on `ark-sdk`'s `BaseExecutor` + `ExecutorApp`) that bridges an Ark Query to the Substrate actor lifecycle — ActorTemplate, create/resume actor, EgressPolicy — via the real `ateapi` gRPC client. |
| `services/ark-runner/` | A generic, config-driven PID-1 runner image honoring Substrate's runner contract. It reads the agent/model/tool spec from its environment and runs the matching framework adapter (default: `completions`, reusing Ark's provider-agnostic model client) — rather than baking one framework per image. |
| `lib/ark-sdk/` (overlay) | HITL types (`ToolApprovalConfig`, `ExecutionContext`, `ResumeContext`, `ApprovalRequiredError`), `ExecutionEngineRequest.resume`, `ExecutorApp` input-required/resumption handling, and `broker.send_event`. These live in shared `ark-sdk`, so every ark-sdk-based executor gets HITL, not just substrate. |
| `openspec/changes/substrate-execution-backend/` | The OpenSpec change (proposal, design, tasks) that scopes this work. |

### Human-in-the-loop (HITL) tool approval

A gated tool (`agent.spec.tools[].approval.required: true`) pauses the agent for human
approval before the tool runs. The substrate path participates in Ark's existing HITL
protocol: the executor returns an A2A `input-required` Task, the controller creates an
`A2ATask`, a human approves/rejects via the dashboard/`ark-api`, and the same Query is
re-dispatched to resume. No controller/Go changes were required. The pending state rides in
the `A2ATask`, so the ephemeral-actor model works without relying on actor snapshot/resume.

## Status

Validated end-to-end on minikube against a live Substrate `ateapi`:

- Plain query, MCP tool calls, and teams of substrate agents all run.
- HITL verified for **approve**, **reject**, **timeout**, and **cascading** (a resumed turn
  whose next tool is also gated pauses again).

Implementation notes, verification detail, and the non-obvious gotchas (executor RBAC for
`a2atasks`, the a2a-sdk `Task`-before-status-event requirement, installing the `ark-sdk` wheel
by path) are in
[`services/ark-substrate-executor/docs/mcp-tool-calling-investigation.md`](services/ark-substrate-executor/docs/mcp-tool-calling-investigation.md)
and [`services/ark-substrate-executor/BRINGUP.md`](services/ark-substrate-executor/BRINGUP.md).

## Branches

- **`main`** — a clean mirror of upstream `main`, kept fast-forwardable
  (`git fetch upstream && git merge --ff-only upstream/main`). No fork work is committed here.
- **`feat/substrate-exec-engine`** — the fork's working branch; all of the above lives here.

## Working in this fork

- `upstream` = `mckinsey/agents-at-scale-ark`, `origin` = `amanvr/agents-at-scale-ark`.
- This fork is **public** and not under the `mckinsey` org, so the machine git-guard refuses
  pushes. Use its sanctioned, audited bypass for legitimate pushes to this personal fork:
  `GIT_GUARD_REASON="<reason, 10+ chars>" git push origin <branch>`. Do not use `--no-verify`
  (it leaves no audit record).
- Build/test instructions are unchanged from upstream — see [CLAUDE.md](CLAUDE.md) and
  [README.md](README.md). The new services follow the standard Python-service pattern
  (`make init`, `make dev`, `make test`, `make lint`, `make build`).

## Key documentation

- [`services/ark-substrate-executor/README.md`](services/ark-substrate-executor/README.md) — the executor, routing, config env.
- [`services/ark-substrate-executor/BRINGUP.md`](services/ark-substrate-executor/BRINGUP.md) — bringing it up on a live Substrate cluster.
- [`services/ark-substrate-executor/docs/architecture.md`](services/ark-substrate-executor/docs/architecture.md) — architecture and data flow.
- [`services/ark-substrate-executor/docs/mcp-tool-calling-investigation.md`](services/ark-substrate-executor/docs/mcp-tool-calling-investigation.md) — MCP tool calling + full HITL implementation and verification.
- [`services/ark-runner/README.md`](services/ark-runner/README.md) — the sandboxed runner.
