# substrate-delegation

E2e coverage for mediated multi-agent delegation of sandboxed agents (OpenSpec
`runner-based-execution` task 3.6).

## What it asserts

1. **Agent-as-tool from a sandbox** — a sandboxed `coordinator` calls the `researcher` agent
   via an `agent`-typed tool. The runner cannot address the researcher's actor directly, so
   the call is mediated by the delegation gateway (ark-api); the query reaches `phase: done`
   and the coordinator relays the researcher's answer.
2. **Team of sandboxed agents** — a `Team` whose members run on the sandboxed tier runs per
   strategy via the existing coordinator; the team query reaches `phase: done`.

The negative paths — **delegation to an undeclared target is refused (403)** and a
**delegation cycle A→B→A is halted (409)** — are covered by unit tests, which assert the
gateway contract directly:

- `services/ark-api/ark-api/tests/api/test_delegation.py` — authz default-deny (403), cycle
  (409), depth limit (409), and that the child query inherits the conversation + extended
  delegation chain.
- `services/ark-runner/tests/test_adapters.py` — the runner's `delegate` tool handler posts
  to the gateway with the `X-Ark-Caller` identity + chain, and surfaces a refusal as an error.
- `lib/ark-sdk/.../test_overlay/test_query_extension.py` — agent/team tools are carried into
  the request (not dropped).
- `services/ark-substrate-executor/tests/test_delegation_wiring.py` — the gateway host is
  added to egress and the caller identity/chain are stamped only when agent/team tools exist.

## Prerequisites

- A live Agent Substrate control plane + `ark-substrate-executor` with the `substrate`
  `ExecutionEngine` registered (see `services/ark-substrate-executor/BRINGUP.md`).
- The ark-api **delegation gateway** reachable from the sandbox: set
  `ARK_DELEGATION_GATEWAY_URL` on the executor to the ark-api
  `/v1/delegation/delegate` endpoint. The executor adds that host to the actor's egress
  allowlist automatically when the agent declares agent/team tools.
- The `openai-gateway-key` secret (key `token`) in the test namespace, or repoint the model
  at the cluster's mock-llm for a hermetic run.

## Running

```bash
chainsaw test --selector requires-substrate=true
```

Successful completion validates that a sandboxed agent can delegate to another agent/team
through the gateway and that teams of sandboxed agents run end-to-end.
