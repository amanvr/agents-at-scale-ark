# Agent Substrate control-plane lifecycle for local kind clusters. Run from anywhere:
#   make -C services/substrate-control-plane <target>
# Override via env, e.g.:  make -C services/substrate-control-plane create-cluster KIND_CLUSTER_NAME=ark
.DEFAULT_GOAL := help
SHELL := bash
HERE := $(dir $(lastword $(MAKEFILE_LIST)))

help: # show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*#' $(MAKEFILE_LIST) | sort | \
	  while read -r l; do printf "\033[1;32m%-16s\033[0m%s\n" "$$(echo $$l | cut -f1 -d:)" "$$(echo $$l | sed 's/^[^#]*# //')"; done

create-cluster: # create the kind cluster + local registry + feature gates Substrate needs
	@bash $(HERE)create-cluster.sh

delete-cluster: # delete the kind cluster + its local registry
	@bash $(HERE)delete-cluster.sh

install: # install the control plane into the CURRENT kind context (devspace does this for you)
	@bash $(HERE)install.sh
