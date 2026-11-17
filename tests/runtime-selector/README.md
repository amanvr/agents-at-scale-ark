# runtime-selector

Verifies the `spec.runtime = (tier, framework)` execution selector.

## What it tests
- An `in-process` / `completions` agent runs a query to completion via mock-llm.
- `runtime` takes precedence over a legacy `executionEngine`: an agent declaring
  both still completes via the completions executor, never the named engine.
- Using `executionEngine` emits a deprecation warning pointing at `spec.runtime`.
- An unknown tier is rejected at admission.

The `sandboxed` tier needs a live Agent Substrate backend and is covered by the
minikube `substrate-executor` tests, not here.

## Running
```bash
chainsaw test
```

Successful completion validates that execution is selected by `spec.runtime`, with
backward-compatible precedence over the deprecated `executionEngine` field.
