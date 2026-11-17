#!/usr/bin/env bash
# Shared config + helpers for the substrate-control-plane scripts. Source; do not execute.
# The pin here is the single source of truth for which Agent Substrate the fork targets; keep
# it in sync with services/ark-substrate-executor/scripts/gen_ateapi.sh (ateapi stub parity).
SUBSTRATE_VERSION="${SUBSTRATE_VERSION:-v0.4.1-0.20261009152331-f6a1dc72a35d}"
# Commit encoded in the pseudo-version above (vX.Y.Z-0.<ts>-<commit>).
SUBSTRATE_COMMIT="${SUBSTRATE_COMMIT:-f6a1dc72a35d}"
SUBSTRATE_REPO="${SUBSTRATE_REPO:-https://github.com/agent-substrate/substrate}"

SCP_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUBSTRATE_SRC="${SUBSTRATE_SRC:-$SCP_HERE/.substrate-src}"
KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-kind}"
KUBECTL_CONTEXT="${KUBECTL_CONTEXT:-kind-${KIND_CLUSTER_NAME}}"

# Clone (or update) the Substrate repo and pin it to the commit the ateapi stubs match.
# install-ate.sh / create-kind-cluster.sh resolve the repo root via git, so a real checkout is
# required (the Go module cache is read-only and has no .git).
ensure_substrate_src() {
  command -v git >/dev/null 2>&1 || { echo "substrate-control-plane: missing 'git'." >&2; return 1; }
  if [ ! -d "$SUBSTRATE_SRC/.git" ]; then
    echo "substrate-control-plane: cloning $SUBSTRATE_REPO -> $SUBSTRATE_SRC"
    git clone "$SUBSTRATE_REPO" "$SUBSTRATE_SRC"
  fi
  git -C "$SUBSTRATE_SRC" fetch --depth 1 origin "$SUBSTRATE_COMMIT" 2>/dev/null || git -C "$SUBSTRATE_SRC" fetch origin
  git -C "$SUBSTRATE_SRC" checkout -q "$SUBSTRATE_COMMIT"
}
