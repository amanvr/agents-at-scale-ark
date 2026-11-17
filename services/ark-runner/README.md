# ark-runner

Config-driven PID-1 runner for Agent Substrate actors. One image runs any framework —
the framework is chosen by config (`ARK_FRAMEWORK`, default `completions`), not by baking
a separate image per framework the way AX does.

`ark-substrate-executor` launches this image as a Substrate actor, passing the agent spec
via env. The runner honors the Substrate runner contract (serves `/healthz` and `/readyz`
on :80, stays up as PID-1 until terminated), runs the agent once through the selected
framework adapter, and writes the result to the workspace for the executor to collect.

## Contract

- `/healthz` → 200 once the process is alive.
- `/readyz` → 503 until the agent run finishes, then 200.
- Stays running after the run so the executor can collect the result and `ax ssh` works.

## Config (env)

| Var | Meaning | Default |
| --- | --- | --- |
| `ARK_AGENT_REQUEST` | JSON `ExecutionEngineRequest` (agent, model, userInput, mcpServers) | required |
| `ARK_FRAMEWORK` | adapter selector | `completions` |
| `ARK_RESULT_PATH` | where the result is written | `/workspace/.ark-result.json` |
| `ARK_WORKSPACE` | workspace root | `/workspace` |
| `PORT` | probe server port | `80` |

## Adapters

Selected by `ARK_FRAMEWORK` via `adapters.select()`. An unknown framework is an error — the
runner never silently falls back to a different one.

- `completions` (default) — prompt + provider-agnostic model client (`model_client.py`,
  mirrors Ark's Go dispatch: OpenAI/Azure/Anthropic) with an MCP tool-calling loop
  (`mcp_client.py`).
- `langchain` — a LangChain tool-calling loop (`ChatOpenAI` pointed at the model's
  OpenAI-compatible endpoint). Optional dependency: install the `langchain` extra.
- `claude` — the Claude Agent SDK driving its own reasoning + tool loop against the agent's
  (anthropic) model config. Optional dependency: install the `claude` extra.

All adapters share tool discovery and execution (`discover_tools` / `invoke_tool_by_name` in
`adapters.py`), so MCP + http tools behave identically regardless of framework — only the
model-reasoning loop differs. Intermediate output is emitted as `__ARK_EVENT__` stdout lines
that the executor relays to `ark-broker`; the final result is an `__ARK_RESULT__` line.

### Adding an adapter

1. Subclass `FrameworkAdapter` in `adapters.py` and set a unique `name`.
2. Implement `async def run(self, request) -> list[Message]`. Call `discover_tools(request)`
   for the OpenAI tool schema + dispatch map, drive your framework's loop, and execute any
   tool call with `invoke_tool_by_name(name, args, dispatch)`. Emit progress with `_emit_event`.
3. Register the class in `_ADAPTERS`.
4. If it needs a heavy library, import it lazily inside `run` (raise a clear error if missing)
   and add an optional-dependency extra in `pyproject.toml` so the base image stays lean.
5. Add it to the webhook's per-tier framework allowlist (`frameworksByTier` in
   `ark/internal/validation/agent.go`) so agents can select it.

## Develop

```bash
make init   # venv + runner with test + adapter extras
make test   # unit tests
make lint   # ruff
```

See `openspec/changes/runner-based-execution` (`specs/runner-execution-model`) and
`openspec/changes/substrate-execution-backend` (`specs/substrate-agent-runner`).
