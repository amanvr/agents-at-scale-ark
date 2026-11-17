"""Tests for the /v1/delegation gateway: default-deny authz, cycle, and depth limits."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ["AUTH_MODE"] = "open"


def _agent_with_tools(tool_names):
    return SimpleNamespace(spec=SimpleNamespace(tools=[SimpleNamespace(name=n) for n in tool_names]))


def _agent_tool_crd(target_name, ttype="agent"):
    spec = SimpleNamespace(type=ttype)
    setattr(spec, ttype, SimpleNamespace(name=target_name))
    return SimpleNamespace(spec=spec)


class TestDelegation(unittest.TestCase):
    def setUp(self):
        from ark_api.main import app
        self.client = TestClient(app)

    def _patch(self, agent, tool_crds, post_mock):
        """Patch with_ark_client (agents/tools lookups) and post_query_and_wait."""
        ark = AsyncMock()
        ark.agents.a_get = AsyncMock(return_value=agent)
        ark.tools.a_get = AsyncMock(side_effect=lambda name: tool_crds[name])
        ctx = AsyncMock()
        ctx.__aenter__.return_value = ark
        ctx.__aexit__.return_value = None
        return (
            patch("ark_api.api.v1.delegation.with_ark_client", return_value=ctx),
            patch("ark_api.api.v1.delegation.post_query_and_wait", post_mock),
        )

    def _body(self, **over):
        body = {
            "callerAgent": "coordinator",
            "callerNamespace": "default",
            "targetType": "agent",
            "targetName": "researcher",
            "targetNamespace": "default",
            "input": "find X",
            "conversationId": "conv-1",
            "chain": "[]",
        }
        body.update(over)
        return body

    def test_declared_target_is_dispatched(self):
        agent = _agent_with_tools(["researcher-tool"])
        tools = {"researcher-tool": _agent_tool_crd("researcher")}
        post = AsyncMock(return_value="RESEARCH RESULT")
        p1, p2 = self._patch(agent, tools, post)
        with p1, p2:
            r = self.client.post("/v1/delegation/delegate", json=self._body())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["result"], "RESEARCH RESULT")
        # Child query shares the conversation and carries the extended chain.
        _, kwargs = post.call_args
        self.assertEqual(kwargs["conversation_id"], "conv-1")
        chain = json.loads(kwargs["annotations"]["ark.mckinsey.com/delegation-chain"])
        self.assertEqual(chain, ["default/coordinator"])

    def test_undeclared_target_refused(self):
        agent = _agent_with_tools(["researcher-tool"])
        tools = {"researcher-tool": _agent_tool_crd("researcher")}
        post = AsyncMock(return_value="x")
        p1, p2 = self._patch(agent, tools, post)
        with p1, p2:
            r = self.client.post("/v1/delegation/delegate", json=self._body(targetName="secret"))
        self.assertEqual(r.status_code, 403)
        post.assert_not_called()

    def test_cycle_is_halted(self):
        agent = _agent_with_tools(["researcher-tool"])
        tools = {"researcher-tool": _agent_tool_crd("researcher")}
        post = AsyncMock(return_value="x")
        p1, p2 = self._patch(agent, tools, post)
        with p1, p2:
            # researcher already appears in the ancestor chain -> cycle
            r = self.client.post(
                "/v1/delegation/delegate",
                json=self._body(chain=json.dumps(["default/researcher"])),
            )
        self.assertEqual(r.status_code, 409)
        post.assert_not_called()

    def test_depth_limit_exceeded(self):
        agent = _agent_with_tools(["researcher-tool"])
        tools = {"researcher-tool": _agent_tool_crd("researcher")}
        post = AsyncMock(return_value="x")
        deep_chain = [f"default/a{i}" for i in range(8)]
        p1, p2 = self._patch(agent, tools, post)
        with p1, p2:
            r = self.client.post(
                "/v1/delegation/delegate",
                json=self._body(chain=json.dumps(deep_chain)),
            )
        self.assertEqual(r.status_code, 409)
        post.assert_not_called()

    def test_header_identity_overrides_body(self):
        agent = _agent_with_tools(["researcher-tool"])
        tools = {"researcher-tool": _agent_tool_crd("researcher")}
        post = AsyncMock(return_value="ok")
        p1, p2 = self._patch(agent, tools, post)
        with p1, p2:
            r = self.client.post(
                "/v1/delegation/delegate",
                json=self._body(callerAgent="spoofed"),
                headers={"X-Ark-Caller": "default/coordinator"},
            )
        self.assertEqual(r.status_code, 200)
        chain = json.loads(post.call_args.kwargs["annotations"]["ark.mckinsey.com/delegation-chain"])
        self.assertEqual(chain, ["default/coordinator"])


if __name__ == "__main__":
    unittest.main()
