## 1. Phase 0 — Prove the seam (AX behind A2A)

- [x] 1.1 Stand up Agent Substrate (control plane, a WorkerPool, egress gateway) in a test cluster, version-pinned
- [x] 1.2 Put an A2A front door on AX (or a minimal Substrate harness) and register it as an Ark `ExecutionEngine` (SUPERSEDED — skipped the AX A2A stepping stone and built the real Phase-1 executor directly; proven by 1.3/2.10)
- [x] 1.3 Bind a test `Agent` via `spec.executionEngine` and run a `Query` end-to-end; confirm it executes as a sandboxed actor and returns a result

## 2. Phase 1 — Bridge + generic runner (completions)

- [x] 2.1 Scaffold the `ark-substrate-executor` service (A2A server speaking Ark's executor protocol)
- [x] 2.2 Implement the `ateapi` client: ensure `ActorTemplate`, create/resume/suspend `Actor`, stream, terminate
- [x] 2.3 Map a `Query` to an actor: provision, run, stream output over A2A, and set the `Query` result on completion
- [x] 2.4 Surface failures (no capacity, agent error, backend unavailable) as a terminal failed `Query` status, not silent success
- [x] 2.5 Scaffold the `ark-runner` image honoring the runner contract (`/healthz`, `/readyz`, prepare workspace, run, SIGTERM, guest services)
- [x] 2.6 Deliver the `Agent`/`Model`/`Tool` spec to the runner and parse it at startup
- [x] 2.7 Implement the completions adapter, reusing Ark's provider-agnostic model client
- [x] 2.8 Wire tool/MCP invocation and stream intermediate output to `ark-broker`
- [x] 2.9 Inject model/tool credentials via env as a Phase-1 stopgap
- [x] 2.10 Register as an `ExecutionEngine`; e2e test: an opt-in agent runs sandboxed via the completions adapter

## 3. Phase 2 — Config-driven adapters + spec-derived egress

- [x] 3.1 Define the framework-adapter interface; select the adapter from the agent spec (completions default)
- [x] 3.2 Add LangChain and Claude Agent SDK adapters (or the adapter contract + stubs)
- [x] 3.3 Derive an `EgressPolicy` from `modelRef` + `tools`/`mcpServers` and apply it per actor (default-deny otherwise)
- [x] 3.4 Move credential delivery to Substrate egress-gateway injection (zero-creds-in-sandbox)
- [x] 3.5 Add a non-default development allow-all egress toggle
- [x] 3.6 e2e: undeclared host denied, declared model/tool reachable, credentials absent from the sandbox (chainsaw `tests/substrate-executor-egress`, verified on minikube: declared model reachable + an undeclared `http` fetch denied under default-deny. Fetcher-tool hosts are deliberately not auto-allowlisted — a fetcher reaches arbitrary hosts, so they stay subject to default-deny. Credentials-absent documented + manually verified, see the test README)

## 4. Phase 3 — Density + stateful sessions

- [ ] 4.1 Reuse one actor per `(agent, conversationId)`; suspend when idle, resume per query (DEFERRED — ephemeral-per-query kept. Resuming a mid-flight golden snapshot proved unreliable, and continuity is now achieved WITHOUT warm reuse via Ark Memory (4.2), so warm reuse is a pure latency/density optimization that would also need a runner work-delivery redesign — the request is baked into the actor env at boot)
- [x] 4.2 Snapshot-backed session state; decide how it reconciles with Ark `Memory` (RESOLVED in favor of Ark Memory as the single source of truth — NOT actor snapshots. The ExecutorApp loads prior turns from the broker (`GET /messages` by `conversationId`, minting one via `POST /conversations` when absent) and the runner prepends them, bringing the ark-sdk executor path to parity with completions. Actors stay stateless/ephemeral)
- [ ] 4.3 Idle auto-suspension for density (DEFERRED with 4.1 — only relevant to warm actor reuse, which is not pursued)
- [x] 4.4 e2e: a follow-up query continues the conversation; a fresh conversationId starts clean (reinterpreted from "resumes a warm actor" → "continues via broker-backed history on an ephemeral actor", since state lives in Ark Memory. See `tests/substrate-executor-sessions`: turn 2 recalls a fact from turn 1 on a shared conversationId; a different conversationId does not. Verified on minikube)

## 5. Compatibility, retirement, and docs

- [x] 5.1 Version-pin Substrate and add a pre-flight API/protobuf compatibility check
- [x] 5.2 Keep the `completions` executor as the non-sandboxed tier; document the routing rule
- [ ] 5.3 Deprecate and retire `ark-sandbox` and per-framework executor Deployments (announce BREAKING for dependents)
- [x] 5.4 Documentation: the executor and runner contract, egress derivation, and the per-agent opt-in guide
- [x] 5.5 Add e2e/chainsaw coverage for the Substrate engine path (success, failure, egress-denied) (`tests/substrate-executor` success+failure and `tests/substrate-executor-egress` reachable+denied, both green on minikube; failure now surfaces promptly via a runner error sentinel instead of the result-collection timeout)
