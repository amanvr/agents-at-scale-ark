## Why

Ark selects execution per agent via `spec.executionEngine`, a CRD reference to a separate
per-framework A2A `ExecutionEngine` Deployment (unset = the default Go `completions` executor).
Meanwhile the Substrate work (`substrate-execution-backend`) already runs agents as a
**config-driven runner with framework adapters** inside a sandbox — a cleaner model where "which
framework" is just an adapter, not a Deployment. Collapsing onto that model (a **runner = tier +
framework**) gives one mental model, far fewer moving parts, and the foundation to run every
agent sandboxed — the prerequisite for Ark to replace AX. The substrate path is now proven
(execution, MCP + http tools, HITL approval, egress default-deny, broker-backed stateful
sessions), so the missing pieces are a unified runtime selector, frameworks-as-adapters, and
multi-agent delegation for sandboxed agents.

## What Changes

Phased; early phases are additive and reversible, the terminal phase is **BREAKING** and gated.

- **Runtime selector.** Introduce `agent.spec.runtime = { tier, framework }` (tier: `in-process`
  | `sandboxed`; framework: `completions` (default), `langchain`, `claude`, …) as the single way
  to choose execution. Added alongside `spec.executionEngine` first (non-breaking); the
  `ExecutionEngine` A2A seam becomes internal plumbing, not a user-facing concept.
- **Frameworks as runner adapters.** New frameworks are config-driven adapters in the runner,
  not separate executor Deployments. Absorb the marketplace per-framework executors
  (LangChain, Claude Agent SDK) into adapters (subsumes `substrate-execution-backend` task 5.3).
- **Mediated multi-agent for sandboxed agents.** `Team` CRDs continue to be orchestrated by the
  existing coordinator (already works for substrate members). `agent`/`team`-as-tool invoked
  *from inside* a sandbox is mediated by a **delegation gateway** (a k8s Service the runner
  reaches via egress + actor-JWT) — the runner gains `type: agent`/`type: team` tool support,
  reusing its existing outbound-tool-call pattern. Shared state flows through the broker.
  Direct actor-to-actor ("Model 2") is **out of scope**: a spike proved Substrate exposes no
  actor-addressability to peers today (actor names are NXDOMAIN from a sandbox); it is a Substrate
  feature request, tracked separately.
- **Keep the Go `completions` executor as the `in-process` tier** throughout the early phases
  (fast path for stateless calls; no sandbox tax).
- **BREAKING (terminal phase, GATED).** Remove the `ExecutionEngine` CRD/selector and retire the
  Go `completions` executor in favor of a `completions` runner adapter, making Substrate the sole
  execution path. **Gated** on: (a) Substrate exposing peer actor-addressability or an accepted
  mediated-delegation story at scale, and (b) acceptable sandbox cold-start latency for the
  common case (the deferred `substrate-execution-backend` 4.1/4.3 lifecycle work).

## Capabilities

### New Capabilities
- **`runner-execution-model`** — the `runtime = (tier, framework)` selector, framework-adapter
  resolution, and dispatch routing (controller → tier; tier → framework adapter).
- **`substrate-agent-delegation`** — mediated multi-agent for sandboxed agents: the delegation
  gateway contract, runner `agent`/`team` tool support, the derived who-may-delegate-to-whom
  authz graph, and broker-backed shared state.

### Modified Capabilities
- None in the early (additive) phases — the runtime selector is introduced alongside the existing
  `ExecutionEngine` model. The terminal phase modifies/removes `agent-engine-dependency` and the
  `execution-engine-*` capabilities; those deltas will be specced when that gated phase is
  undertaken (kept out of this proposal to avoid speccing behavior that is not yet being built).

## Impact

- **CRDs**: `Agent` gains `spec.runtime` (deprecates `spec.executionEngine`); `ExecutionEngine`
  CRD removed only in the terminal phase (**BREAKING** for dependents).
- **ark-controller**: dispatch by `runtime` (tier → engine); eventually dispatches to Substrate
  directly when the seam is removed.
- **ark-runner**: framework-adapter selection; new `agent`/`team` delegation tools.
- **ark-sdk**: resolve `runtime` into the request; delegation-gateway client.
- **completions executor**: reframed as the `in-process` tier / `completions` adapter; retired
  only in the terminal phase.
- **Delegation gateway**: new thin endpoint (likely on ark-api or the orchestrator).
- **Marketplace**: per-framework executors absorbed into runner adapters.
- **Substrate**: becomes mandatory only in the terminal phase; actor-to-actor exposure is an
  external dependency for any future "Model 2".
- Builds on `substrate-execution-backend` (the substrate execution path, HITL, egress, sessions).
