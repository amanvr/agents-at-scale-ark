## Context

See proposal.md — Why. Today the controller dispatches a Query to the agent's `ExecutionEngine`
over A2A (unset = the Go `completions` executor; named = a per-framework Deployment, e.g.
`substrate`). The `substrate-execution-backend` change already runs agents as a config-driven
runner with framework adapters inside a gVisor sandbox, with HITL, egress default-deny, and
broker-backed conversation history. This design reuses that machinery and reframes execution
around a `runtime = (tier, framework)` selector plus a mediated multi-agent model.

Two hard constraints shape the approach:
- **A spike proved Substrate exposes no peer actor-addressability today.** From inside a sandbox,
  actor names are NXDOMAIN and a worker-pod IP is rejected by the mesh (503), while k8s Services
  and external hosts are reachable. So an agent *can* call a k8s Service but *cannot* call another
  actor directly. Direct actor-to-actor ("Model 2") is therefore out of scope and a Substrate
  feature request.
- **Sandbox cold-start + actor lifecycle** (warm reuse / idle-suspend) is deferred and currently
  unreliable (`substrate-execution-backend` 4.1/4.3), so the common path should not be forced
  through a sandbox before that is solved.

## Goals / Non-Goals

**Goals:**
- A single execution selector (`runtime`) that subsumes tier and framework.
- Multi-agent (teams + agent-as-tool) for sandboxed agents using only capabilities that exist
  today (k8s Service reachability + actor identity), with no new Substrate dependency.
- A phased path whose early steps are additive and reversible, ending at an optional, gated
  "Substrate-only" terminal state.

**Non-Goals (design-level):**
- Direct actor-to-actor networking (Substrate dependency — tracked separately).
- Warm actor reuse / idle-suspend (inherited from `substrate-execution-backend`, still deferred).
- Changing team *strategies* (sequential/round-robin/selector/graph) — reused as-is.

## Decisions

### D1: `runtime = (tier, framework)`; keep the A2A seam as internal plumbing (early phases)
Introduce `spec.runtime` and route on it; the `ExecutionEngine`/A2A dispatch stays underneath as
an implementation detail, not a user-facing concept. **Alternative considered:** remove the
`ExecutionEngine` CRD immediately — rejected; it is the decoupling seam and keeping it makes the
early phases reversible and low-risk.

### D2: Frameworks are config-driven adapters in one runner image
A framework is an adapter selected from the spec (default `completions`), not a per-framework
Deployment or image. **Alternative:** framework-per-image (AX's model) — rejected; it is the
sprawl this change removes, and `substrate-execution-backend` already chose config-driven adapters.

### D3: Multi-agent via mediated delegation (Model 1), not direct actor-to-actor
- `Team` CRDs are run by the existing coordinator (the completions executor already orchestrates
  teams and fans members out over A2A to the substrate engine — verified working).
- `agent`/`team`-as-tool invoked from *inside* a sandbox is mediated by a **delegation gateway**:
  a k8s Service the runner reaches via egress (allowlisted) and authenticates to with its actor
  identity. The gateway dispatches the sub-agent/sub-team and returns the result.
**Alternative:** Model 2 (agents call each other directly) — rejected now; the spike proved it is
not possible with Substrate's current interfaces.

### D4: The runner's delegation reuses its existing outbound-tool-call pattern
`type: agent`/`type: team` tools become a new tool-type handler in the runner that calls the
gateway, blocks, and feeds the result back into the loop — identical in shape to how it already
calls MCP and http tools. This is the key answer to the duplication concern: delegation is a tool
handler, not a second orchestrator or a re-implementation of execution.

### D5: Delegation gateway reuses the controller's sub-dispatch; no new orchestrator
The gateway is a thin endpoint (preferably on an existing service — ark-api or the controller's
A2A surface) that creates/dispatches a child execution for the target and returns its result. It
holds no strategy logic (teams keep that in the coordinator).

### D6: Keep the Go `completions` executor as the `in-process` tier through the early phases
It is the mature default (memory, teams, streaming, tracing, providers, HITL). It is reframed as
the in-process tier / `completions` adapter and retired only in the gated terminal phase, after a
runner `completions` adapter reaches parity.

### D7: Shared state via Ark Memory (broker), keyed by conversationId
Reuse the broker-backed history already shipped. Delegated participants exchange context through
the broker, never sandbox-local state — this is what makes mediation work without actor-to-actor.

## Risks / Trade-offs

- **Substrate never exposes actor-to-actor** → Model 1 is permanent, not a stepping stone. The
  gateway becomes a hot path → keep it stateless and horizontally scalable; it is request-scoped.
- **Cold-start latency per delegation** (each callee may spin a fresh actor) → keep the in-process
  tier for latency-sensitive work; revisit when `substrate-execution-backend` 4.1/4.3 land.
- **Retiring the Go completions executor is large** (parity across memory/teams/streaming/
  providers/HITL) → gate the terminal phase on proven adapter parity; do not remove until then.
- **Substrate-mandatory couples Ark core to Substrate** → only in the terminal phase; the seam
  stays until the gate is met, so the coupling is opt-in and reversible before then.
- **Dual selectors** (`runtime` + legacy `executionEngine`) during migration → define precedence
  (runtime wins) and emit deprecation warnings via the existing migration-warning pattern.
- **Delegation fan-out / cycles** → enforce the declared-graph authz (default-deny) plus depth and
  breadth limits; detect cycles (spec requirement).

## Migration Plan

Phased; each early phase ships independently and is reversible.
- **Phase A — runtime selector (additive).** Add `spec.runtime`; map it to the existing tiers
  (in-process = completions executor, sandboxed = substrate). Honor legacy `executionEngine` with
  `runtime` taking precedence; annotate `executionEngine` as deprecated. Rollback: ignore
  `runtime`, fall back to `executionEngine`.
- **Phase B — frameworks as adapters.** Converge marketplace per-framework executors (LangChain,
  Claude Agent SDK) into runner adapters (subsumes `substrate-execution-backend` 5.3). Rollback:
  keep the standalone executors registered.
- **Phase C — mediated delegation.** Add the delegation gateway + runner `agent`/`team` tool
  support; derive the authz graph from the `Team`/tool spec; add the gateway host to egress.
  Enables teams-of-sandboxed-agents end-to-end and agent-as-tool from a sandbox. Rollback: drop
  the gateway; agent/team tools remain unsupported on the sandboxed tier (as today).
- **Phase D — terminal, GATED, BREAKING.** Remove the `ExecutionEngine` CRD/selector, retire the
  Go completions executor in favor of the `completions` runner adapter, make Substrate the sole
  execution path. **Gate:** (a) Substrate exposes peer actor-addressability, or the mediated model
  is accepted at the target scale; AND (b) cold-start latency is acceptable for the common case
  (4.1/4.3). No automatic rollback — this is the one-way door; it is not entered until the gate is
  met.

## Open Questions

- **Gateway placement** (endpoint on ark-api vs the controller's A2A surface vs a small dedicated
  service) — deferrable; it does not change the specs, the mediated approach, or the task spine.
- **Streaming of a delegated sub-agent's intermediate output** back to the caller/broker vs
  returning only the final result — deferrable; a refinement of the gateway contract.
