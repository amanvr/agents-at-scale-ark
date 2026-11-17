#!/usr/bin/env bash
# Fire a query at an agent and trace it across every layer (controller routing is implicit in
# which backend logs it; executor handoff; live actor + egress; result). Called by `make trace`.
# Args: AGENT INPUT NS SYSNS ATESPACE
set -o pipefail
AGENT="${1:-assistant-sandboxed}"; INPUT="${2:-Say hello}"
NS="${3:-default}"; SYSNS="${4:-ark-system}"; ATESPACE="${5:-ate-demo-counter}"

q="trace-$(date +%s)"
echo "### firing query '$q' -> agent '$AGENT' (input: $INPUT)"
printf 'apiVersion: ark.mckinsey.com/v1alpha1\nkind: Query\nmetadata: { name: %s, namespace: %s }\nspec: { input: "%s", target: { type: agent, name: %s }, ttl: 10m }\n' \
  "$q" "$NS" "$INPUT" "$AGENT" | kubectl apply -f - >/dev/null

echo "### catching the live actor (ephemeral — only exists while the query runs)..."
for _ in $(seq 1 60); do
  a="$(kubectl ate get actors -a "$ATESPACE" 2>/dev/null | awk 'NR==2{print $2}')"
  if [ -n "$a" ]; then
    kubectl ate get actors -a "$ATESPACE" 2>/dev/null | sed -n '1p;2p'
    echo "--- egress policy (derived allowlist) ---"
    kubectl ate get egress-policy "$a" -a "$ATESPACE" 2>&1 | sed -n '1p;2p'
    break
  fi
  kubectl get query "$q" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null | grep -q done && break
  sleep 0.3
done

until kubectl get query "$q" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null | grep -qE 'done|error'; do sleep 1; done

echo "### [executor] Ark -> Substrate handoff"
kubectl logs deploy/ark-substrate-executor -n "$SYSNS" --tail=200 2>/dev/null | grep -iE "$q|SubstrateActor" | tail -4
echo "### runner image (digest-pinned):"
kubectl get deploy ark-substrate-executor -n "$SYSNS" -o jsonpath='{range .spec.template.spec.containers[0].env[?(@.name=="ARK_RUNNER_IMAGE")]}{.value}{"\n"}{end}'
echo "### result:"
kubectl get query "$q" -n "$NS" -o jsonpath='{.status.phase}{" | "}{.status.response.content}{"\n"}'
kubectl delete query "$q" -n "$NS" >/dev/null 2>&1 || true
