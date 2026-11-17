# substrate-executor-sessions

E2e coverage for **conversation-history continuity** on the Substrate execution path
(OpenSpec `substrate-execution-backend` tasks 4.2 + 4.4 — "stateful sessions", done via Ark
Memory rather than actor snapshots).

Complements [`../substrate-executor`](../substrate-executor) (success/failure) and
[`../substrate-executor-egress`](../substrate-executor-egress) (egress default-deny).

## What it asserts

Substrate agents are ephemeral per query, so continuity comes from Ark's external memory (the
broker), keyed by `conversationId` — the same mechanism the completions executor uses. The
ExecutorApp loads prior turns from the broker and the runner prepends them before the model call.

1. **Turn 1** states a fact ("My favorite color is teal") on `conversationId: substrate-sessions-conv`.
2. **Turn 2** shares that `conversationId` and asks the color back → response must contain "teal"
   (recalled from history loaded off the broker).
3. **Fresh** query on a *different* `conversationId` asks the same thing → response must NOT
   contain "teal" (no prior history; continuity is conversation-scoped).

## Prerequisites

- A live Agent Substrate control plane + `ark-substrate-executor` deployed, `substrate`
  `ExecutionEngine` registered. See `services/ark-substrate-executor/BRINGUP.md`.
- A broker-backed `default` Memory (the standard Ark install provides one → `ark-broker`). The
  executor discovers the broker from the `ark-config-broker` streaming config.
- The `openai-gateway-key` secret (key `token`) in the namespace the test runs in.

## Run

```bash
kubectl -n default create secret generic openai-gateway-key --from-literal=token="$TOKEN"
chainsaw test ./tests/substrate-executor-sessions --config /tmp/chainsaw-min.yaml --namespace default
```

## Note

With a real LLM the assertions are worded to be robust (turn 2 is told to answer in one word;
the fresh query is told to answer "unknown" if it doesn't know). For a fully hermetic run,
repoint the model at an in-cluster mock-llm with scripted responses.
