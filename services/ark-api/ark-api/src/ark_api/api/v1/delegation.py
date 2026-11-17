"""Delegation gateway: mediates a sandboxed agent delegating to another agent/team.

A sandboxed agent cannot address peer actors, so its agent/team tool calls come here. The
gateway authenticates the caller (by its stamped identity), enforces default-deny against the
caller's declared agent/team tools, halts delegation cycles and bounds depth, then dispatches
the target as a child Query (sharing the parent conversation) and returns its result.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from ark_sdk.client import with_ark_client

from ...models.delegation import DelegateRequest, DelegateResponse
from .a2agw.query import post_query_and_wait

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/delegation", tags=["delegation"])

VERSION = "v1alpha1"
MAX_DELEGATION_DEPTH = 8
DELEGATION_CHAIN_ANNOTATION = "ark.mckinsey.com/delegation-chain"
DELEGATION_TIMEOUT_SECONDS = 300


def _parse_chain(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        chain = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(x) for x in chain] if isinstance(chain, list) else []


async def _declared_targets(ark_client, caller_agent: str) -> set[tuple[str, str]]:
    """The (type, name) agent/team targets the caller declares as tools — its allowed graph.

    Mirrors the ark-sdk tool resolution: each declared tool references a Tool CRD whose
    spec.type is agent/team and whose spec.agent/spec.team names the target.
    """
    agent = await ark_client.agents.a_get(caller_agent)
    allowed: set[tuple[str, str]] = set()
    for tool in (getattr(agent.spec, "tools", None) or []):
        tool_name = getattr(tool, "name", None)
        if not tool_name:
            continue
        try:
            tool_crd = await ark_client.tools.a_get(tool_name)
        except Exception:
            logger.warning("delegation: caller %s tool %s not resolvable", caller_agent, tool_name)
            continue
        spec = tool_crd.spec
        ttype = getattr(spec, "type", None)
        if ttype not in ("agent", "team"):
            continue
        ref = getattr(spec, ttype, None)
        target_name = getattr(ref, "name", None) if ref else None
        if target_name:
            allowed.add((ttype, target_name))
    return allowed


@router.post("/delegate", response_model=DelegateResponse)
async def delegate(
    body: DelegateRequest,
    x_ark_caller: Optional[str] = Header(None),
) -> DelegateResponse:
    """Authorize and dispatch a delegated agent/team call, returning its result."""
    # The stamped identity header is authoritative when present (body is a convenience).
    caller_namespace = body.callerNamespace
    caller_agent = body.callerAgent
    if x_ark_caller and "/" in x_ark_caller:
        caller_namespace, caller_agent = x_ark_caller.split("/", 1)
    if not caller_agent or not caller_namespace:
        raise HTTPException(status_code=401, detail="missing caller identity")

    target_namespace = body.targetNamespace or caller_namespace
    caller_id = f"{caller_namespace}/{caller_agent}"
    target_id = f"{target_namespace}/{body.targetName}"

    # Cycle + depth limits (the chain is the ancestors that led here).
    chain = _parse_chain(body.chain)
    if target_id in chain or target_id == caller_id:
        raise HTTPException(status_code=409, detail=f"delegation cycle detected: {target_id} already active")
    if len(chain) >= MAX_DELEGATION_DEPTH:
        raise HTTPException(status_code=409, detail=f"delegation depth limit ({MAX_DELEGATION_DEPTH}) exceeded")

    # Default-deny: the caller may only reach targets it declares as agent/team tools.
    async with with_ark_client(caller_namespace, VERSION) as ark_client:
        allowed = await _declared_targets(ark_client, caller_agent)
    if (body.targetType, body.targetName) not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"caller {caller_id} may not delegate to {body.targetType}/{body.targetName}",
        )

    child_chain = chain + [caller_id]
    annotations = {DELEGATION_CHAIN_ANNOTATION: json.dumps(child_chain)}
    result = await post_query_and_wait(
        namespace=target_namespace,
        target_type=body.targetType,
        target=body.targetName,
        query=body.input,
        timeout=DELEGATION_TIMEOUT_SECONDS,
        conversation_id=body.conversationId,
        annotations=annotations,
    )
    return DelegateResponse(result=result)
