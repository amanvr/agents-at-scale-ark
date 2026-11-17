"""Framework adapters: how the runner actually executes an agent.

The adapter is selected from config (default: completions), so one runner image serves
many frameworks — the config-driven improvement over AX's framework-per-image.
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

import httpx
from ark_sdk.executor import (
    AgentDelegationTool,
    ApprovalRequiredError,
    ExecutionContext,
    ExecutionEngineRequest,
    HTTPTool,
    Message,
    ToolApprovalConfig,
)

from . import config, model_client
from .mcp_client import MCPClient

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10
HTTP_TOOL_TIMEOUT_SECONDS = 30
# A delegated agent/team may itself run a full agent loop, so allow longer than a plain http tool.
DELEGATION_TIMEOUT_SECONDS = 300
# The egress gateway re-signs outbound TLS with its own CA; the sandbox may not trust it.
# Mirror model_client: ARK_RUNNER_TLS_INSECURE=true skips verification.
_TLS_VERIFY = os.environ.get("ARK_RUNNER_TLS_INSECURE", "").lower() not in ("1", "true", "yes")

_URL_PARAM = re.compile(r"\{([^}]+)\}")


def _substitute_url(url_template: str, args: dict[str, Any]) -> str:
    """Fill {param} placeholders from the model's call arguments, URL-encoding each value
    (mirrors the Go HTTPExecutor.substituteURLParameters)."""
    def repl(m: re.Match) -> str:
        key = m.group(1)
        return quote(str(args[key]), safe="") if key in args else m.group(0)
    return _URL_PARAM.sub(repl, url_template)


def _go_fmt(value: Any) -> str:
    """Render a JSON value the way Go's fmt.Sprintf("%v", ...) does, so argument-match
    regexes written against the Go executor behave the same here (notably bool casing)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _matches_approval_arguments(config_: ToolApprovalConfig, arguments: str) -> bool:
    """Port of the Go matchesApprovalArguments: no matchers → gate every call; otherwise
    gate when any matcher's regex matches the named argument's value. A call whose arguments
    fail to parse is gated rather than waved through."""
    if not config_.argumentMatches:
        return True
    try:
        parsed = json.loads(arguments or "{}")
    except (json.JSONDecodeError, TypeError):
        return True
    if not isinstance(parsed, dict):
        return True
    for matcher in config_.argumentMatches:
        if matcher.argument not in parsed:
            continue
        try:
            if re.search(matcher.pattern, _go_fmt(parsed[matcher.argument])):
                return True
        except re.error:
            continue
    return False


def _emit_event(text: str) -> None:
    """Emit intermediate output as a stdout sentinel the executor relays to ark-broker.
    Tagged with the per-query nonce (shared worker-pod log disambiguation)."""
    if text:
        print(f"{config.EVENT_SENTINEL} {config.nonce()} {text}", flush=True)


async def discover_tools(
    request: ExecutionEngineRequest,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the OpenAI tool schema for every available tool and a name->dispatch map.

    Shared by every adapter so tool discovery (MCP + http) is defined once.
    dispatch[name] = ("mcp", server) for MCP tools, ("http", HTTPTool) for fetcher tools.
    """
    tools: list[dict[str, Any]] = []
    dispatch: dict[str, Any] = {}
    for server in getattr(request, "mcpServers", None) or []:
        try:
            async with MCPClient(server.url, headers=server.headers) as mcp:
                for tool in await mcp.list_tools():
                    name = tool["name"]
                    dispatch[name] = ("mcp", server)
                    tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": name,
                                "description": tool.get("description", ""),
                                "parameters": tool.get("inputSchema", {}),
                            },
                        }
                    )
        except Exception:
            logger.exception("failed to list tools from MCP server %s", server.name)

    for http_tool in getattr(request, "httpTools", None) or []:
        dispatch[http_tool.name] = ("http", http_tool)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": http_tool.name,
                    "description": http_tool.description,
                    "parameters": http_tool.inputSchema or {"type": "object", "properties": {}},
                },
            }
        )

    # agent/team tools: delegated via the gateway. A single string `input` (mirrors the Go
    # AgentToolExecutor contract) carrying the task for the target agent/team.
    conversation_id = getattr(request, "conversationId", "") or ""
    for agent_tool in getattr(request, "agentTools", None) or []:
        dispatch[agent_tool.name] = ("delegate", (agent_tool, conversation_id))
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": agent_tool.name,
                    "description": agent_tool.description
                    or f"Delegate to the {agent_tool.targetType} '{agent_tool.targetName}'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input": {
                                "type": "string",
                                "description": f"The task to send to the {agent_tool.targetType}.",
                            }
                        },
                        "required": ["input"],
                    },
                },
            }
        )
    return tools, dispatch


async def invoke_tool_by_name(name: str, args: dict[str, Any], dispatch: dict[str, Any]) -> str:
    """Run one named tool call (MCP or http) via the dispatch map and return its result text.

    Shared by every adapter so tool execution is defined once, regardless of which framework
    decided to make the call. An unknown name or a failing tool is returned as an error string
    so the model sees the failure rather than the query silently succeeding.
    """
    _emit_event(f"calling tool {name}({args})")
    entry = dispatch.get(name)
    if entry is None:
        return f"error: no tool named {name!r}"
    kind, target = entry
    try:
        if kind == "http":
            return await _invoke_http_tool(target, args)
        if kind == "delegate":
            agent_tool, conversation_id = target
            return await _invoke_delegation(agent_tool, args, conversation_id)
        async with MCPClient(target.url, headers=target.headers) as mcp:
            return await mcp.call_tool(name, args)
    except Exception as e:
        logger.exception("tool %s failed", name)
        return f"error: {e}"


async def _invoke_delegation(tool: AgentDelegationTool, args: dict[str, Any], conversation_id: str) -> str:
    """Delegate to an agent/team via the gateway (a sandbox cannot address peer actors).

    Presents the runner's caller identity so the gateway can authorize the call against the
    caller's declared agent/team tools and halt cycles via the ancestor chain. Reuses the
    egress TLS pattern; a refused/failed delegation is returned as an error string so the
    model sees it rather than the query silently succeeding.
    """
    gateway = config.delegation_gateway_url()
    if not gateway:
        return "error: delegation gateway not configured"
    payload = {
        "callerAgent": config.caller_agent(),
        "callerNamespace": config.caller_namespace(),
        "targetType": tool.targetType,
        "targetName": tool.targetName,
        "targetNamespace": tool.targetNamespace,
        "input": str(args.get("input", "")),
        "conversationId": conversation_id,
        "chain": config.delegation_chain(),
    }
    headers = {
        "X-Ark-Caller": f"{config.caller_namespace()}/{config.caller_agent()}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=DELEGATION_TIMEOUT_SECONDS, verify=_TLS_VERIFY) as http:
        resp = await http.post(gateway, headers=headers, json=payload)
        if resp.status_code >= 400:
            return (
                f"error: delegation to {tool.targetType} '{tool.targetName}' failed: "
                f"HTTP {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        return data.get("result", "")


async def _invoke_http_tool(tool: HTTPTool, args: dict[str, Any]) -> str:
    """Call a built-in http (fetcher) tool. Mirrors the Go HTTPExecutor: {param} URL
    substitution, method/headers/body, 10MB response cap, non-2xx surfaced as an error.
    An egress-blocked host raises in httpx and is returned as an error string so the model
    sees the failure (and the query does not silently succeed)."""
    url = _substitute_url(tool.url, args)
    method = (tool.method or "GET").upper()
    body = None
    if tool.body and method in ("POST", "PUT", "PATCH"):
        body = _substitute_url(tool.body, args)
    async with httpx.AsyncClient(timeout=HTTP_TOOL_TIMEOUT_SECONDS, verify=_TLS_VERIFY) as http:
        resp = await http.request(method, url, headers=tool.headers or None, content=body)
        text = resp.text[: 10 << 20]
        if resp.status_code >= 400:
            return f"error: HTTP {resp.status_code}: {text} (URL: {url})"
        return text


class FrameworkAdapter(ABC):
    name: str

    @abstractmethod
    async def run(self, request: ExecutionEngineRequest) -> list[Message]:
        """Execute the agent and return the resulting messages."""


class CompletionsAdapter(FrameworkAdapter):
    """Ark's native agent semantics: a prompt + model + tool/MCP completion loop.

    Uses the runner's provider-agnostic model client (model_client.py), which mirrors
    Ark's Go completions executor dispatch (OpenSpec task 2.7, Option C). MCP servers on the
    request are exposed to the model as tools and invoked in the loop (task 2.8).
    """

    name = "completions"

    async def run(self, request: ExecutionEngineRequest) -> list[Message]:
        agent = request.agent

        tools, dispatch = await discover_tools(request)
        logger.info(
            "discovered %d tools from %d MCP server(s) and %d http tool(s)",
            len(tools),
            len(getattr(request, "mcpServers", None) or []),
            len(getattr(request, "httpTools", None) or []),
        )

        # HITL approval gates, keyed by the tool name the model calls.
        approvals = self._build_approvals(request)

        if request.resume is not None:
            messages = await self._rebuild_for_resume(request, dispatch)
        else:
            # Prepend prior conversation history (loaded by the ExecutorApp from Ark Memory)
            # between the system prompt and the current input — parity with the completions
            # executor's PrepareModelMessages (memory ++ input).
            messages = [{"role": "system", "content": agent.prompt}]
            messages.extend(getattr(request, "history", None) or [])
            messages.append(
                {"role": request.userInput.role or "user", "content": request.userInput.content}
            )

        for _ in range(MAX_TOOL_ITERATIONS):
            assistant = await model_client.complete(agent.model, messages, tools=tools or None)
            messages.append(assistant)
            if assistant.get("content"):
                _emit_event(assistant["content"])
            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                return [Message(role="assistant", content=assistant.get("content") or "")]
            # Raises ApprovalRequiredError if any call is gated (pausing the whole turn),
            # otherwise appends each tool result message.
            self._gate_or_run_prep(tool_calls, approvals, agent, request, messages)
            for call in tool_calls:
                messages.append(await self._invoke_tool(call, dispatch))

        logger.warning("tool loop hit MAX_TOOL_ITERATIONS=%d", MAX_TOOL_ITERATIONS)
        return [Message(role="assistant", content=messages[-1].get("content") or "")]

    def _build_approvals(self, request: ExecutionEngineRequest) -> dict[str, ToolApprovalConfig]:
        approvals: dict[str, ToolApprovalConfig] = {}
        for server in getattr(request, "mcpServers", None) or []:
            for entry in getattr(server, "approvals", None) or []:
                approvals[entry.tool] = entry.approval
        return approvals

    def _gate_or_run_prep(
        self,
        tool_calls: list[dict[str, Any]],
        approvals: dict[str, ToolApprovalConfig],
        agent: Any,
        request: ExecutionEngineRequest,
        messages: list[dict[str, Any]],
    ) -> None:
        """Mirror the Go executeToolCalls first pass: if any call in this turn is gated,
        pause the entire turn (no tools run) by raising ApprovalRequiredError. The pending
        tool calls + the conversation BEFORE this assistant message ride in the context so a
        fresh actor can resume after the human decides."""
        pending: list[dict[str, Any]] = []
        gate_config: ToolApprovalConfig | None = None
        for call in tool_calls:
            name = call.get("function", {}).get("name", "")
            config_ = approvals.get(name)
            if config_ is None:
                continue
            if _matches_approval_arguments(config_, call.get("function", {}).get("arguments", "")):
                pending.append(call)
                if gate_config is None:
                    gate_config = config_
        if not pending:
            return
        # messages currently ends with the assistant message that holds these tool_calls;
        # the resume path reconstructs that assistant message from `pending`, so drop it here.
        context = ExecutionContext(
            conversationId=request.conversationId,
            pendingToolCallIndex=0,
            completedToolResults=[],
            agentName=agent.name,
            agentNamespace=agent.namespace,
            messages=messages[:-1],
        )
        raise ApprovalRequiredError(pending, gate_config, context)

    async def _rebuild_for_resume(
        self, request: ExecutionEngineRequest, dispatch: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Rebuild the paused conversation from resume context and apply the human decision.

        Reconstructs the assistant message that triggered approval (its tool_calls are the
        gated set), then for each gated call either runs it (approved) or injects a rejection
        tool result. Returns the message list positioned to continue the normal loop (so a
        further gated call pauses again — cascading approval)."""
        resume = request.resume
        messages: list[dict[str, Any]] = list(resume.context.messages)
        messages.append({"role": "assistant", "content": None, "tool_calls": resume.toolCalls})
        for res in resume.context.completedToolResults:
            messages.append({
                "role": "tool",
                "tool_call_id": res.id,
                "content": res.error or res.content,
            })
        rejection = resume.rejectionReason or "Tool execution rejected by user"
        for call in resume.toolCalls:
            if resume.decision == "approved":
                _emit_event(f"approved tool {call.get('function', {}).get('name', '')}")
                messages.append(await self._invoke_tool(call, dispatch))
            else:
                _emit_event(f"rejected tool {call.get('function', {}).get('name', '')}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": rejection,
                })
        return messages

    async def _invoke_tool(self, call: dict[str, Any], dispatch: dict[str, Any]) -> dict[str, Any]:
        """Run one tool call (MCP or http) and return the OpenAI tool-result message."""
        fn = call.get("function", {})
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        result = await invoke_tool_by_name(name, args, dispatch)
        return {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}


class LangChainAdapter(FrameworkAdapter):
    """Run the agent as a LangChain tool-calling loop.

    Reuses the request's model config (via a LangChain `ChatOpenAI` pointed at the model's
    OpenAI-compatible endpoint) and the runner's shared tool dispatch (MCP + http), so tool
    discovery and execution behave identically across adapters — only the model-reasoning loop
    is LangChain's. LangChain is an optional dependency; install the `langchain` extra.
    """

    name = "langchain"

    async def run(self, request: ExecutionEngineRequest) -> list[Message]:
        try:
            from langchain_core.messages import (
                AIMessage,
                HumanMessage,
                SystemMessage,
                ToolMessage,
            )
        except ImportError as e:  # pragma: no cover - exercised only without the extra installed
            raise RuntimeError(
                "langchain framework selected but LangChain is not installed; "
                "install the ark-runner 'langchain' extra"
            ) from e

        agent = request.agent
        tool_schema, dispatch = await discover_tools(request)

        chat = self._build_chat_model(agent.model)
        if tool_schema:
            # Bind the OpenAI tool schemas so the model sees each tool's real parameters; the
            # runner's shared dispatch (not LangChain) executes the calls the model elects.
            chat = chat.bind_tools(tool_schema)

        messages: list[Any] = [SystemMessage(content=agent.prompt)]
        for prior in getattr(request, "history", None) or []:
            role = prior.get("role")
            content = prior.get("content") or ""
            if role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))
        messages.append(HumanMessage(content=request.userInput.content))

        for _ in range(MAX_TOOL_ITERATIONS):
            ai = await chat.ainvoke(messages)
            messages.append(ai)
            if getattr(ai, "content", None):
                _emit_event(ai.content if isinstance(ai.content, str) else str(ai.content))
            tool_calls = getattr(ai, "tool_calls", None) or []
            if not tool_calls:
                content = ai.content if isinstance(ai.content, str) else str(ai.content or "")
                return [Message(role="assistant", content=content)]
            for call in tool_calls:
                result = await invoke_tool_by_name(call["name"], call.get("args") or {}, dispatch)
                messages.append(ToolMessage(content=result, tool_call_id=call.get("id", "")))

        logger.warning("langchain tool loop hit MAX_TOOL_ITERATIONS=%d", MAX_TOOL_ITERATIONS)
        last = messages[-1]
        content = getattr(last, "content", "") or ""
        return [Message(role="assistant", content=content if isinstance(content, str) else str(content))]

    def _build_chat_model(self, model: Any) -> Any:
        """Construct a LangChain chat model from Ark's model config. Overridable in tests.

        Uses the OpenAI-compatible endpoint (openai/azure providers expose one); the model's
        baseUrl/apiKey come from the same config block the runner's model_client reads.
        """
        from langchain_openai import ChatOpenAI

        cfg = getattr(model, "config", None) or {}
        pc = cfg.get(model.type, {}) if isinstance(cfg, dict) else {}
        base_url = str(pc.get("baseUrl") or "https://api.openai.com/v1").rstrip("/")
        api_key = str(pc.get("apiKey") or "placeholder")
        return ChatOpenAI(model=model.name, base_url=base_url, api_key=api_key, temperature=0)


class ClaudeAgentSDKAdapter(FrameworkAdapter):
    """Run the agent via the Claude Agent SDK.

    The SDK owns its own reasoning + tool loop, so this adapter maps the request onto SDK
    options (system prompt, model, and the request's MCP servers) and collects the SDK's text
    output. The model's apiKey/baseUrl come from the agent's (anthropic) model config. The
    Claude Agent SDK is an optional dependency; install the `claude` extra.
    """

    name = "claude"

    async def run(self, request: ExecutionEngineRequest) -> list[Message]:
        options = self._build_options(request)
        prompt = self._build_prompt(request)

        chunks: list[str] = []
        async for text in self._query(prompt, options):
            if text:
                _emit_event(text)
                chunks.append(text)
        return [Message(role="assistant", content="".join(chunks))]

    def _build_prompt(self, request: ExecutionEngineRequest) -> str:
        """The current user input, prepended with prior conversation history if any."""
        lines: list[str] = []
        for prior in getattr(request, "history", None) or []:
            role = prior.get("role") or "user"
            content = prior.get("content") or ""
            if content:
                lines.append(f"{role}: {content}")
        lines.append(request.userInput.content)
        return "\n".join(lines)

    def _build_options(self, request: ExecutionEngineRequest) -> Any:
        """Map the request onto Claude Agent SDK options: system prompt, model, MCP servers."""
        from claude_agent_sdk import ClaudeAgentOptions

        agent = request.agent
        model = agent.model
        cfg = getattr(model, "config", None) or {}
        pc = cfg.get(model.type, {}) if isinstance(cfg, dict) else {}
        api_key = str(pc.get("apiKey") or "")
        base_url = pc.get("baseUrl")

        env: dict[str, str] = {}
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            env["ANTHROPIC_BASE_URL"] = str(base_url)

        mcp_servers = {
            server.name: {"type": "http", "url": server.url, "headers": server.headers or {}}
            for server in getattr(request, "mcpServers", None) or []
        }

        return ClaudeAgentOptions(
            system_prompt=agent.prompt,
            model=model.name,
            mcp_servers=mcp_servers,
            env=env,
        )

    async def _query(self, prompt: str, options: Any):
        """Yield assistant text blocks from the SDK. A thin seam so tests can inject a fake."""
        from claude_agent_sdk import AssistantMessage, TextBlock, query

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield block.text


_ADAPTERS: dict[str, type[FrameworkAdapter]] = {
    CompletionsAdapter.name: CompletionsAdapter,
    LangChainAdapter.name: LangChainAdapter,
    ClaudeAgentSDKAdapter.name: ClaudeAgentSDKAdapter,
}


def select(framework: str) -> FrameworkAdapter:
    cls = _ADAPTERS.get(framework)
    if cls is None:
        raise RuntimeError(f"unknown framework adapter {framework!r}; have {sorted(_ADAPTERS)}")
    return cls()
