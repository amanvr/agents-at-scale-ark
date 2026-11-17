# runtime-and-hitl

Examples for the `runner-based-execution` runtime model (`spec.runtime = {tier, framework}`),
teams, and human-in-the-loop (HITL) tool approval gating a file-gateway write.

## Prerequisites
- A `default` Model (Available) in the target namespace.
- The `file-gateway` MCP server installed (provides `file-gateway-write-file` / `-list-directory`).
- For the `assistant-sandboxed` agent only: a Substrate control plane + `ark-substrate-executor`
  (`ENABLE_SUBSTRATE=true devspace dev`). The in-process agents, the team, and HITL do not need it.

## Run

```bash
kubectl apply -f agents.yaml
kubectl apply -f queries.yaml

# In-process agent and team complete on the completions executor:
kubectl get query q-inproc q-team -w
kubectl get query q-inproc -o jsonpath='{.status.response.content}{"\n"}'
```

## HITL approval

`q-hitl` drives the model to call `file-gateway-write-file`, which is gated. The query halts:

```bash
kubectl get query q-hitl -o jsonpath='{.status.phase}{"\n"}'   # -> input-required
```

The controller creates an A2ATask holding the pending call. Inspect and approve (or reject):

```bash
T=$(kubectl get a2atasks -o jsonpath='{range .items[?(@.status.phase=="input-required")]}{.metadata.name}{"\n"}{end}' | head -1)
kubectl get a2atask "$T" -o jsonpath='{.status.protocolMetadata.toolCalls}{"\n"}'   # what is being approved
kubectl patch a2atask "$T" --type=merge -p '{"spec":{"input":"{\"decision\":\"approved\"}"}}'
# reject instead: '{"spec":{"input":"{\"decision\":\"rejected\"}"}}'
```

The query then resumes and executes (or skips) the write, reaching `phase: done`. Read tools on
the same agent are ungated — only the write pauses.

## Tiers

`assistant-inproc` and `assistant-sandboxed` are identical except for `spec.runtime.tier`. The
controller routes `in-process` to the completions executor and `sandboxed` to the `substrate`
ExecutionEngine — visible in the controller log line `stage=resolve-dispatch-address`. See
[Runtime Execution Model](../../docs/content/reference/runtime-model.mdx).
