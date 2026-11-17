#!/usr/bin/env bash
# Create the local kind cluster + registry that Agent Substrate needs, using Substrate's own
# hack/create-kind-cluster.sh. This sets up the local registry on :5001 and the feature gates
# the control plane requires (ClusterTrustBundle, ClusterTrustBundleProjection,
# PodCertificateRequest) — which a default kind/minikube cluster does NOT have.
#
# Run this ONCE before `ENABLE_SUBSTRATE=true devspace dev`. KIND ONLY.
set -o errexit -o nounset -o pipefail

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

for bin in docker kind git; do
  command -v "$bin" >/dev/null 2>&1 || { echo "substrate-control-plane: missing prerequisite '$bin'." >&2; exit 1; }
done

ensure_substrate_src

# Substrate's create-kind-cluster.sh only recreates the registry when it is *running* on the
# wrong port; a leftover stopped/created `kind-registry` from an aborted run makes its
# `docker run --name kind-registry` fail with a name conflict. Clear that stale state first.
reg_name="kind-registry"
reg_port="${KIND_REGISTRY_PORT:-5001}"
if docker inspect "$reg_name" >/dev/null 2>&1 && \
   [ "$(docker inspect -f '{{.State.Running}}' "$reg_name" 2>/dev/null)" != "true" ]; then
  echo "Removing stale (non-running) '$reg_name' container from a previous run..."
  docker rm -f "$reg_name" >/dev/null 2>&1 || true
fi

# A *different* container already publishing the registry port (e.g. an `ate-registry` from a
# prior minikube-based Substrate setup) makes Substrate's `docker run` fail with a cryptic
# "port is already allocated". Surface the offender and how to free it.
holder="$(docker ps --format '{{.Names}} {{.Ports}}' | awk -v p=":${reg_port}->" 'index($0, p){print $1; exit}')"
if [ -n "${holder:-}" ] && [ "$holder" != "$reg_name" ]; then
  echo "error: port ${reg_port} is already published by container '${holder}', which the kind" >&2
  echo "       registry needs. Free it and re-run:  docker rm -f ${holder}" >&2
  exit 1
fi

echo "Creating kind cluster '${KIND_CLUSTER_NAME}' + local registry (Agent Substrate config)..."
cd "$SUBSTRATE_SRC"
KIND_CLUSTER_NAME="$KIND_CLUSTER_NAME" hack/create-kind-cluster.sh "$@"

# devspace loads images with the host `kind` (from PATH), but the cluster's node image is built
# by the kind version Substrate pins. If the host kind is older, `kind load` fails with
# "unknown containerd config version". Warn so it's fixed before the long devspace build.
pinned="$(awk '/sigs.k8s.io\/kind v/{print $2; exit}' "$SUBSTRATE_SRC/hack/tools/kind/go.mod" 2>/dev/null || true)"
host="$(kind version 2>/dev/null | awk '{print $2}' || true)"
if [ -n "$pinned" ] && [ -n "$host" ] && [ "$host" != "$pinned" ]; then
  echo
  echo "WARNING: your PATH 'kind' is ${host}, but Substrate builds the node image with ${pinned}." >&2
  echo "         devspace uses the PATH kind to load images; an older one fails with" >&2
  echo "         'unknown containerd config version'. Match it before 'devspace dev':" >&2
  echo "           go install sigs.k8s.io/kind@${pinned}   # ensure it is first on PATH" >&2
fi

echo
echo "Kind cluster ready. Context: ${KUBECTL_CONTEXT}"
echo "Next: install Ark + Substrate with  ENABLE_SUBSTRATE=true devspace dev"
