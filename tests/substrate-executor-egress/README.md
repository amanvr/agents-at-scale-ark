# substrate-executor-egress

E2e coverage for the Substrate execution engine's **egress default-deny** posture
(OpenSpec `substrate-execution-backend` task 3.6 and the egress-denied part of 5.5).

Complements [`../substrate-executor`](../substrate-executor) (success + failure paths).

## What it asserts

With the executor's dev `AX_ALLOW_ALL_EGRESS` turned **off** (so the per-actor allowlist
derived from `modelRef` + `tools`/`mcpServers` is the only egress granted):

1. **Declared host reachable** — a plain agent whose only outbound need is its model host
   (derived from `modelRef`) completes (`phase: done`). If default-deny had blocked the model
   host, the query would error.
2. **Undeclared host denied** — an agent with a built-in `http` fetch tool to `example.com`.
   Fetcher-tool hosts are **not** auto-added to the actor's egress allowlist (a fetcher reaches
   arbitrary hosts, so auto-opening egress to them would defeat the sandbox). Only `modelRef` +
   `mcpServers` hosts are derived. So under default-deny the fetch is blocked; the agent echoes
   the tool's raw result, which surfaces the egress failure. `example.com` is real and
   resolvable (and succeeds under allow-all), so a failure means egress blocked it — not DNS.

The `AX_ALLOW_ALL_EGRESS=true` toggle is restored in `finally`, regardless of outcome.

## Prerequisites

- A live Agent Substrate control plane + `ark-substrate-executor` deployed, with the `substrate`
  `ExecutionEngine` registered. See `services/ark-substrate-executor/BRINGUP.md`.
- The runner image must include built-in `http` (fetcher) tool support (ark-sdk `httpTools` +
  the runner's `_invoke_http_tool`).
- The `openai-gateway-key` secret (key `token`) must exist in the namespace the test runs in.
  Because the model/secret must be co-located with the Query, run the test in a namespace that
  has the secret, e.g.:

  ```bash
  kubectl -n default create secret generic openai-gateway-key --from-literal=token="$TOKEN"
  chainsaw test ./tests/substrate-executor-egress --namespace default \
    --selector 'requires-substrate=true'
  ```

## Credentials absent from the sandbox (task 3.6)

Zero-creds-in-sandbox is verified separately from this test, because the ephemeral actor is
torn down after each query (so its log cannot be grepped post-hoc from Chainsaw). To verify by
hand while a query runs with `ARK_SUBSTRATE_CREDENTIAL_URI` set on the executor:

1. The executor strips the resolved `apiKey` from the serialized request and attaches a
   credential-injection rule to the actor's https egress policy, so the real token never enters
   the sandbox; the egress gateway substitutes it on the outbound request.
2. Confirm the real token never appears in the actor log (it sends `Authorization: Bearer
   placeholder`): read the hosting worker pod's `ateom` log and grep for the secret value —
   expect zero matches. This was validated manually (query answered correctly with only the
   placeholder present in-sandbox). See
   `services/ark-substrate-executor/docs/mcp-tool-calling-investigation.md` and the
   credential-injection notes in `BRINGUP.md`.

## Run

```bash
# Secret must exist in the target namespace (see Prerequisites).
chainsaw test ./tests/substrate-executor-egress --namespace default
```
