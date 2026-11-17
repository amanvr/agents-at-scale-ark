# Observability helpers for the Substrate execution path. Run from anywhere:
#   make -C services/ark-substrate-executor <target>
# Override defaults inline, e.g.:  make -C services/ark-substrate-executor trace AGENT=my-agent INPUT="hi"
.DEFAULT_GOAL := help
SHELL := bash

# where the controller + executor run
SYSNS ?= ark-system
# where queries/agents live
NS ?= default
# Substrate atespace the executor uses
ATESPACE ?= ate-demo-counter
# default agent for `trace`
AGENT ?= assistant-sandboxed
# default query input for `trace`
INPUT ?= Say hello
# query name for `query`/`broker`; actor name for `actor-logs`/`egress`
Q ?=
ACTOR ?=

HERE := $(dir $(lastword $(MAKEFILE_LIST)))

help: # show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*#' $(MAKEFILE_LIST) | sort | \
	  while read -r l; do printf "\033[1;32m%-16s\033[0m%s\n" "$$(echo $$l | cut -f1 -d:)" "$$(echo $$l | sed 's/^[^#]*# //')"; done

status: # overall health: executor pod, engine, workerpool, model
	@echo "## executor";      kubectl get pods -n $(SYSNS) -l app=ark-substrate-executor
	@echo "## engine";        kubectl get executionengine substrate -n $(SYSNS) -o jsonpath='{.metadata.name}  addr={.status.lastResolvedAddress}{"\n"}'
	@echo "## workerpools";   kubectl get workerpools -A
	@echo "## default model"; kubectl get model default -n $(NS) -o jsonpath='{.spec.provider} {.spec.model.value}  available={.status.conditions[?(@.type=="ModelAvailable")].status}{"\n"}'

runner-image: # the digest-pinned ark-runner image the executor launches
	@kubectl get deploy ark-substrate-executor -n $(SYSNS) -o jsonpath='{range .spec.template.spec.containers[0].env[?(@.name=="ARK_RUNNER_IMAGE")]}{.value}{"\n"}{end}'

actors: # live actors in the atespace (empty unless a query is mid-flight)
	@kubectl ate get actors -a $(ATESPACE)

watch-actors: # continuously watch actors (run this, then fire a query)
	@watch -n0.4 'kubectl ate get actors -a $(ATESPACE)'

actor-logs: # runner stdout for an actor (ACTOR=...); only while it's RUNNING
	@test -n "$(ACTOR)" || { echo "usage: make actor-logs ACTOR=<name>  (from 'make actors')"; exit 1; }
	@kubectl ate logs actors $(ACTOR) -a $(ATESPACE)

egress: # derived egress allowlist for an actor (ACTOR=...)
	@test -n "$(ACTOR)" || { echo "usage: make egress ACTOR=<name>"; exit 1; }
	@kubectl ate get egress-policy $(ACTOR) -a $(ATESPACE)

executor-logs: # follow the Ark->Substrate handoff (executor)
	@kubectl logs deploy/ark-substrate-executor -n $(SYSNS) -f --tail=20 | grep --line-buffered -iE "SubstrateActor|actor|adapter|__ARK_|error"

controller-route: # controller dispatch/routing decisions
	@kubectl logs deploy/ark-controller -n $(SYSNS) --tail=500 | grep -iE "resolvedAddress|resolve-dispatch|ExecutionEngine processed" | tail -8

query: # a query's phase + response + full message trace (Q=...)
	@test -n "$(Q)" || { echo "usage: make query Q=<query-name>"; exit 1; }
	@echo "phase:    $$(kubectl get query $(Q) -n $(NS) -o jsonpath='{.status.phase}')"
	@echo "response: $$(kubectl get query $(Q) -n $(NS) -o jsonpath='{.status.response.content}')"
	@echo "--- message trace ---"; kubectl get query $(Q) -n $(NS) -o jsonpath='{.status.response.raw}' 2>/dev/null | \
	  python3 -c "import sys,json;[print(f\"[{m.get('name','?')}/{m.get('role')}] {m.get('content','')[:200]}\") for m in json.loads(sys.stdin.read() or '[]')]"

broker: # broker stream activity for a query (Q=...)
	@test -n "$(Q)" || { echo "usage: make broker Q=<query-name>"; exit 1; }
	@kubectl logs deploy/ark-broker -n $(NS) --tail=500 | grep "$(Q)" | tail

trace: # fire a sandboxed query and trace it across every layer end-to-end
	@bash $(HERE)observe-trace.sh "$(AGENT)" "$(INPUT)" "$(NS)" "$(SYSNS)" "$(ATESPACE)"
