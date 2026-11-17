#!/usr/bin/env bash
# Delete the kind cluster + the local registry container created for the Substrate flow.
# Self-contained: plain `kind delete` (version-agnostic) + removes the registry only if it was
# created by the Substrate tooling. Mirrors Substrate's hack/delete-kind-cluster.sh.
set -o errexit -o nounset -o pipefail

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

command -v kind >/dev/null 2>&1 || { echo "delete-cluster: missing 'kind'." >&2; exit 1; }

echo "Deleting kind cluster '${KIND_CLUSTER_NAME}'..."
kind delete cluster --name "${KIND_CLUSTER_NAME}" || true

reg_name="kind-registry"
if docker inspect "${reg_name}" >/dev/null 2>&1; then
  created_by="$(docker inspect --format '{{index .Config.Labels "created-by"}}' "${reg_name}" 2>/dev/null || true)"
  if [ "${created_by}" = "agent-substrate" ]; then
    echo "Removing registry container '${reg_name}'..."
    docker rm -f "${reg_name}" >/dev/null 2>&1 || true
  else
    echo "Leaving '${reg_name}' (created-by='${created_by}', not agent-substrate)."
  fi
fi

echo "Done."
