# substrate-executor

E2e coverage for the Substrate execution engine's success and failure paths
(OpenSpec `substrate-execution-backend` task 5.5: success + failure).

Egress default-deny coverage lives in [`../substrate-executor-egress`](../substrate-executor-egress).

## What it asserts

1. **Success** — an opt-in agent (`spec.executionEngine: substrate`) runs a query as a
   sandboxed Substrate actor and the query reaches `phase: done`.
2. **Failure surfaces** — an agent pointed at an unreachable model host fails the query
   (`phase: error`), proving the executor reports backend/agent failures rather than silent
   success.

## Prerequisites

- A live Agent Substrate control plane + `ark-substrate-executor` deployed, with the `substrate`
  `ExecutionEngine` registered. See `services/ark-substrate-executor/BRINGUP.md`.
- The `openai-gateway-key` secret (key `token`) must exist in the namespace the test runs in
  (the model/secret must be co-located with the Query). Run in a namespace that has it:

  ```bash
  kubectl -n default create secret generic openai-gateway-key --from-literal=token="$TOKEN"
  chainsaw test ./tests/substrate-executor --namespace default \
    --selector 'requires-substrate=true'
  ```

## Notes

- Labeled `requires-substrate: "true"` and excluded from default runs; select it explicitly once
  the Substrate stack is up.
- The failure case uses a deliberately unreachable model host (`unreachable.invalid`).
