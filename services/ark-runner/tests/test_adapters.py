"""Adapter tests: the framework registry, shared tool dispatch, and each adapter's loop.

Framework-specific paths are driven with fakes (an injected chat model / SDK query seam) so
they run without network or real provider credentials.
"""

from __future__ import annotations

import pytest
from ark_sdk.executor import (
    AgentConfig,
    AgentDelegationTool,
    ExecutionEngineRequest,
    HTTPTool,
    MCPServerConfig,
    Message,
    Model,
)

from ark_runner import adapters, config


def _request(**kwargs) -> ExecutionEngineRequest:
    model = Model(
        name="test-model",
        type="openai",
        config={"openai": {"apiKey": "k", "baseUrl": "http://model.local/v1"}},
    )
    agent = AgentConfig(name="agent", namespace="default", prompt="you are a test agent", model=model)
    return ExecutionEngineRequest(
        agent=agent,
        userInput=Message(role="user", content="hello"),
        **kwargs,
    )


# --- registry / selection (task 2.3) ---------------------------------------------------------


def test_registry_has_the_three_adapters():
    assert sorted(adapters._ADAPTERS) == ["claude", "completions", "langchain"]


def test_select_returns_the_named_adapter():
    assert adapters.select("completions").name == "completions"
    assert adapters.select("langchain").name == "langchain"
    assert adapters.select("claude").name == "claude"


def test_select_unknown_framework_errors_not_defaults():
    with pytest.raises(RuntimeError) as exc:
        adapters.select("bogus")
    assert "unknown framework adapter 'bogus'" in str(exc.value)


# --- shared tool dispatch --------------------------------------------------------------------


async def test_discover_tools_builds_schema_for_http_tools():
    req = _request(
        httpTools=[
            HTTPTool(name="weather", description="get weather", url="http://api/{city}"),
        ]
    )
    schema, dispatch = await adapters.discover_tools(req)
    assert schema[0]["function"]["name"] == "weather"
    assert dispatch["weather"][0] == "http"


async def test_invoke_tool_unknown_name_returns_error():
    result = await adapters.invoke_tool_by_name("missing", {}, {})
    assert result.startswith("error: no tool named")


# --- delegation (agent/team tools via the gateway) -------------------------------------------


async def test_discover_tools_builds_delegate_dispatch():
    req = _request(
        agentTools=[
            AgentDelegationTool(name="ask-researcher", targetType="agent", targetName="researcher"),
        ],
        conversationId="conv-1",
    )
    schema, dispatch = await adapters.discover_tools(req)
    fn = schema[0]["function"]
    assert fn["name"] == "ask-researcher"
    assert fn["parameters"]["required"] == ["input"]
    kind, (tool, conv) = dispatch["ask-researcher"]
    assert kind == "delegate" and tool.targetName == "researcher" and conv == "conv-1"


class _FakeResp:
    def __init__(self, status_code, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


def _fake_httpx(captured, resp):
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return resp

    return _FakeClient


async def test_delegation_posts_to_gateway(monkeypatch):
    captured = {}
    monkeypatch.setattr(config, "delegation_gateway_url", lambda: "http://gw/delegate")
    monkeypatch.setattr(config, "caller_agent", lambda: "caller")
    monkeypatch.setattr(config, "caller_namespace", lambda: "ns1")
    monkeypatch.setattr(config, "delegation_chain", lambda: '["ns1/root"]')
    client = _fake_httpx(captured, _FakeResp(200, {"result": "ANSWER"}))
    monkeypatch.setattr(adapters.httpx, "AsyncClient", client)

    tool = AgentDelegationTool(
        name="ask", targetType="agent", targetName="researcher", targetNamespace="ns1"
    )
    dispatch = {"ask": ("delegate", (tool, "conv-9"))}
    result = await adapters.invoke_tool_by_name("ask", {"input": "find X"}, dispatch)

    assert result == "ANSWER"
    assert captured["url"] == "http://gw/delegate"
    assert captured["headers"]["X-Ark-Caller"] == "ns1/caller"
    assert captured["json"]["targetName"] == "researcher"
    assert captured["json"]["input"] == "find X"
    assert captured["json"]["conversationId"] == "conv-9"
    assert captured["json"]["chain"] == '["ns1/root"]'


async def test_delegation_refused_returns_error(monkeypatch):
    monkeypatch.setattr(config, "delegation_gateway_url", lambda: "http://gw/delegate")
    monkeypatch.setattr(config, "caller_agent", lambda: "caller")
    monkeypatch.setattr(config, "caller_namespace", lambda: "ns1")
    monkeypatch.setattr(config, "delegation_chain", lambda: "")
    monkeypatch.setattr(adapters.httpx, "AsyncClient", _fake_httpx({}, _FakeResp(403, text="forbidden")))

    tool = AgentDelegationTool(name="ask", targetType="agent", targetName="secret")
    dispatch = {"ask": ("delegate", (tool, ""))}
    result = await adapters.invoke_tool_by_name("ask", {"input": "x"}, dispatch)
    assert result.startswith("error: delegation to agent 'secret' failed: HTTP 403")


async def test_delegation_without_gateway_configured_errors(monkeypatch):
    monkeypatch.setattr(config, "delegation_gateway_url", lambda: "")
    tool = AgentDelegationTool(name="ask", targetType="agent", targetName="researcher")
    dispatch = {"ask": ("delegate", (tool, ""))}
    result = await adapters.invoke_tool_by_name("ask", {"input": "x"}, dispatch)
    assert result == "error: delegation gateway not configured"


# --- completions adapter (regression: no-tool path) ------------------------------------------


async def test_completions_returns_assistant_message(monkeypatch):
    async def fake_complete(model, messages, tools=None):
        return {"role": "assistant", "content": "final answer", "tool_calls": []}

    monkeypatch.setattr(adapters.model_client, "complete", fake_complete)
    out = await adapters.CompletionsAdapter().run(_request())
    assert out == [Message(role="assistant", content="final answer")]


# --- langchain adapter (fake chat model) -----------------------------------------------------


class _FakeChat:
    """Minimal stand-in for a LangChain chat model: scripted ainvoke responses."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        return self._scripted.pop(0)


async def test_langchain_no_tool_returns_final_text(monkeypatch):
    from langchain_core.messages import AIMessage

    fake = _FakeChat([AIMessage(content="hi from langchain")])
    monkeypatch.setattr(adapters.LangChainAdapter, "_build_chat_model", lambda self, model: fake)

    out = await adapters.LangChainAdapter().run(_request())
    assert out == [Message(role="assistant", content="hi from langchain")]


async def test_langchain_runs_tool_then_finishes(monkeypatch):
    from langchain_core.messages import AIMessage

    calls = []

    async def fake_invoke(name, args, dispatch):
        calls.append((name, args))
        return "TOOL_RESULT"

    monkeypatch.setattr(adapters, "invoke_tool_by_name", fake_invoke)

    scripted = [
        AIMessage(
            content="",
            tool_calls=[{"name": "weather", "args": {"city": "NYC"}, "id": "c1", "type": "tool_call"}],
        ),
        AIMessage(content="done"),
    ]
    fake = _FakeChat(scripted)
    monkeypatch.setattr(adapters.LangChainAdapter, "_build_chat_model", lambda self, model: fake)

    req = _request(httpTools=[HTTPTool(name="weather", description="w", url="http://api/{city}")])
    out = await adapters.LangChainAdapter().run(req)

    assert calls == [("weather", {"city": "NYC"})]
    assert out == [Message(role="assistant", content="done")]
    # The real tool schema (with parameters) was bound to the model.
    assert fake.bound_tools[0]["function"]["name"] == "weather"


# --- claude agent sdk adapter (fake query seam) ----------------------------------------------


class _FakeClaude(adapters.ClaudeAgentSDKAdapter):
    async def _query(self, prompt, options):
        self.seen_prompt = prompt
        self.seen_options = options
        for chunk in ("Hello ", "world"):
            yield chunk


async def test_claude_collects_text_blocks():
    adapter = _FakeClaude()
    out = await adapter.run(_request())
    assert out == [Message(role="assistant", content="Hello world")]


def test_claude_build_options_maps_model_and_mcp():
    model = Model(
        name="claude-sonnet",
        type="anthropic",
        config={"anthropic": {"apiKey": "secret", "baseUrl": "http://anthropic.local"}},
    )
    agent = AgentConfig(name="agent", namespace="default", prompt="sys", model=model)
    req = ExecutionEngineRequest(
        agent=agent,
        userInput=Message(role="user", content="hi"),
        mcpServers=[MCPServerConfig(name="files", url="http://mcp.local/mcp")],
    )
    options = adapters.ClaudeAgentSDKAdapter()._build_options(req)
    assert options.system_prompt == "sys"
    assert options.model == "claude-sonnet"
    assert options.env["ANTHROPIC_API_KEY"] == "secret"
    assert options.env["ANTHROPIC_BASE_URL"] == "http://anthropic.local"
    assert options.mcp_servers["files"]["url"] == "http://mcp.local/mcp"


def test_claude_build_prompt_prepends_history():
    req = _request(history=[{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}])
    prompt = adapters.ClaudeAgentSDKAdapter()._build_prompt(req)
    assert prompt == "user: earlier\nassistant: ok\nhello"
