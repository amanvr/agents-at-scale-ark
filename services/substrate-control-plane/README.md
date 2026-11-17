# substrate-control-plane

A DevSpace dependency that installs the [Agent Substrate](https://github.com/agent-substrate/substrate)
control plane (ateapi, a WorkerPool, the egress gateway) into a local **kind** cluster, so the
sandboxed runtime tier works end-to-end with `devspace`.

**Kind only.** Agent Substrate's installer is kind-oriented (local registry at `localhost:5001`,
`ko` image builds, cluster feature gates). `install.sh` refuses to run on any non-kind context.

## How it works

`install.sh` clones the Substrate repo at the pinned commit (matching the ateapi stubs in
`services/ark-substrate-executor`), then runs Substrate's `hack/install-ate-kind.sh` with:

```
--deploy-ate-system --credential-provider='{"name":"k8s.io"}' --deploy-demo-counter
```

i.e. the control plane, the bundled k8s-secrets egress credential provider, and the
`ate-demo-counter` atespace + gVisor WorkerPool the executor chart targets by default. (Pass
your own flags to `./install.sh` to override.) It is a dependency of `ark-substrate-executor`,
which the root `enable-substrate` profile adds when `ENABLE_SUBSTRATE=true` — so the control
plane comes up before the executor deploys. Idempotent (skips if `ate-system` already exists).

## Prerequisites

- Host tools: `go`, `ko`, `docker`, `kind`, `git`.
- Your PATH `kind` must match the version Substrate pins (currently **v0.33.0** —
  `hack/tools/kind/go.mod`). devspace uses the host `kind` to load images, and an older one
  fails with `unknown containerd config version` against the newer node image. `create-cluster.sh`
  warns if yours is older; fix with `go install sigs.k8s.io/kind@v0.33.0` (first on PATH).
- A kind cluster with a local registry on `:5001` and Substrate's required feature gates
  (`ClusterTrustBundle`, `ClusterTrustBundleProjection`, `PodCertificateRequest`). A default
  kind cluster does **not** have these — create it with `make create-cluster` (below).

## Use

```bash
# From the repo root (or add `-C services/substrate-control-plane` to each):

# 1. Create the kind cluster + registry + feature gates (once, before devspace):
make -C services/substrate-control-plane create-cluster

# 2. Install Ark + the control plane + the sandboxed executor:
ENABLE_SUBSTRATE=true devspace dev          # or: devspace deploy

# Tear it all down:
make -C services/substrate-control-plane delete-cluster
```

`make help` lists the targets (`create-cluster`, `delete-cluster`, `install`). The control-plane
`install` runs automatically as a devspace dependency during step 2; `make install` runs just it
against the current kind context. Override via env, e.g.
`make create-cluster KIND_CLUSTER_NAME=ark`.

Both scripts share the pin in `_lib.sh`. Override via env: `SUBSTRATE_VERSION`,
`SUBSTRATE_COMMIT`, `SUBSTRATE_REPO`, `KIND_CLUSTER_NAME`, `KUBECTL_CONTEXT`.

## Notes & caveats (validated end-to-end on a fresh kind cluster)

- **Runner image is digest-pinned.** Substrate requires the ActorTemplate image to be pinned by
  digest (snapshots are keyed to it). `ark-substrate-executor`'s devspace config pushes
  `ark-runner` to the kind registry and a `runner-digest` hook injects
  `localhost:5001/ark-runner@sha256:…` as `ARK_RUNNER_IMAGE`; a bare tag is rejected by ateapi.
- **Recreating the cluster with a warm docker cache:** devspace prints `Skip building image …`
  for images already in your host docker cache and then does **not** load them onto the freshly
  created node → base-stack pods `ImagePullBackOff`. A net-new machine (empty cache) is
  unaffected (everything builds → loads). If you recreate the cluster, clear the cached `ark-*`
  images (`docker image prune`) so devspace rebuilds+loads, or `kind load` them manually.
- **One devspace session per namespace:** a hung `devspace deploy` holds a session lock; kill it
  before starting another, or devspace reports "another DevSpace session … already running".
