#!/usr/bin/env bash
# Install the Agent Substrate control plane into a local kind cluster.
#
# KIND ONLY. Runs as a devspace dependency of ark-substrate-executor, so
# `ENABLE_SUBSTRATE=true devspace dev` brings the control plane up before the executor deploys.
# It uses the pinned Substrate checkout and runs Substrate's kind installer. Idempotent;
# refuses to run on a non-kind context.
#
# The kind cluster must already exist with the right registry + feature gates — create it with
# ./create-cluster.sh first. Prerequisites on the host: go, ko, docker, kind, git.
set -o errexit -o nounset -o pipefail

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

# Guard: kind only. Refuse any non-kind context so this never lands on minikube/prod.
cur="$(kubectl config current-context 2>/dev/null || true)"
case "$cur" in
  kind-*) : ;;
  *)
    echo "substrate-control-plane: current context '$cur' is not a kind cluster — refusing." >&2
    echo "Agent Substrate is kind-only here. Run ./create-cluster.sh first, or set" >&2
    echo "KIND_CLUSTER_NAME / KUBECTL_CONTEXT to your kind cluster." >&2
    exit 1
    ;;
esac

# Idempotent: skip only when a *fully* installed control plane is present. The install has two
# phases (--deploy-ate-system then --deploy-demo-counter); keying on the ate-system namespace
# would wrongly skip a run that timed out before the demo phase. A WorkerPool only exists once
# --deploy-demo-counter has run, so it is the right "fully installed" signal (and the get fails
# cleanly on a fresh cluster where the CRD is absent).
if [ -n "$(kubectl --context "$KUBECTL_CONTEXT" get workerpools -A -o name 2>/dev/null)" ]; then
  echo "substrate-control-plane: WorkerPool present on $KUBECTL_CONTEXT; control plane already installed, skipping."
  exit 0
fi

for bin in go ko docker kind git; do
  command -v "$bin" >/dev/null 2>&1 || { echo "substrate-control-plane: missing prerequisite '$bin'." >&2; exit 1; }
done

ensure_substrate_src

# Default deploy flags (override by passing args to this script):
#   --deploy-ate-system                      control plane: CRDs, atelet, apiserver
#   --credential-provider='{"name":"k8s.io"}' bundled k8s-secrets egress credential provider
#                                            (matches the executor's ate-secret://k8s.io/... URI)
#   --deploy-demo-counter                    provides the `ate-demo-counter` atespace + a gVisor
#                                            WorkerPool + snapshots — what the executor chart
#                                            targets by default (atespace/gvisor-default).
#   --rollout-timeout                        per-workload readiness wait. The 60s default is too
#                                            short for the first install (envoy/atenet images are
#                                            built + pulled on the fly), so bump it.
# Mirrors Substrate's own kind bring-up (hack/verify-atenet-drain.sh). Without an action flag
# install-ate.sh only prints usage and exits non-zero.
if [ "$#" -eq 0 ]; then
  set -- --deploy-ate-system --credential-provider='{"name":"k8s.io"}' --deploy-demo-counter \
    --rollout-timeout="${ATE_ROLLOUT_TIMEOUT:-300s}"
fi

echo "substrate-control-plane: installing Agent Substrate ($SUBSTRATE_VERSION) on $KUBECTL_CONTEXT ..."
echo "substrate-control-plane: flags: $*"
cd "$SUBSTRATE_SRC"
KIND_CLUSTER_NAME="$KIND_CLUSTER_NAME" KUBECTL_CONTEXT="$KUBECTL_CONTEXT" hack/install-ate-kind.sh "$@"
echo "substrate-control-plane: done."
