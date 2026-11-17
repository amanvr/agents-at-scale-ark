"""Phase C delegation wiring in the substrate executor: the delegation gateway is only
reachable (egress) and only stamped into the runner env when the agent declares agent/team
tools, so a plain agent's sandbox is unchanged."""

from __future__ import annotations

from ark_sdk.executor import (
    AgentConfig,
    AgentDelegationTool,
    ExecutionEngineRequest,
    Message,
    Model,
)

from ark_substrate_executor import executor as ex


def _request(agent_tools=None, annotations=None):
    model = Model(name="m", type="openai", config={"openai": {"baseUrl": "https://api.model.local/v1"}})
    agent = AgentConfig(name="caller", namespace="ns1", prompt="p", model=model)
    return ExecutionEngineRequest(
        agent=agent,
        userInput=Message(role="user", content="hi"),
        agentTools=agent_tools or [],
        query_annotations=annotations or {},
    )


def test_egress_omits_gateway_without_agent_tools(monkeypatch):
    monkeypatch.setattr(ex, "DELEGATION_GATEWAY_URL", "https://ark-api.ark-system.svc:8080/x")
    _, https = ex._egress_hosts(_request())
    assert "ark-api.ark-system.svc" not in https


def test_egress_adds_gateway_with_agent_tools(monkeypatch):
    monkeypatch.setattr(ex, "DELEGATION_GATEWAY_URL", "https://ark-api.ark-system.svc:8080/x")
    tools = [AgentDelegationTool(name="t", targetType="agent", targetName="researcher")]
    _, https = ex._egress_hosts(_request(agent_tools=tools))
    assert "ark-api.ark-system.svc" in https


class _FakeSelf:
    def _framework(self, request):
        return "completions"


def test_runner_env_stamps_caller_and_chain(monkeypatch):
    monkeypatch.setattr(ex, "DELEGATION_GATEWAY_URL", "https://gw/delegate")
    tools = [AgentDelegationTool(name="t", targetType="agent", targetName="researcher")]
    req = _request(agent_tools=tools, annotations={ex.DELEGATION_CHAIN_ANNOTATION: '["ns1/root"]'})
    env = ex.SubstrateExecutor._runner_env(_FakeSelf(), req)
    assert env[ex.DELEGATION_GATEWAY_ENV] == "https://gw/delegate"
    assert env[ex.CALLER_AGENT_ENV] == "caller"
    assert env[ex.CALLER_NAMESPACE_ENV] == "ns1"
    assert env[ex.DELEGATION_CHAIN_ENV] == '["ns1/root"]'


def test_runner_env_omits_delegation_without_agent_tools(monkeypatch):
    monkeypatch.setattr(ex, "DELEGATION_GATEWAY_URL", "https://gw/delegate")
    env = ex.SubstrateExecutor._runner_env(_FakeSelf(), _request())
    assert ex.DELEGATION_GATEWAY_ENV not in env
    assert ex.CALLER_AGENT_ENV not in env
