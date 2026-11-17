"""Ark broker client for streaming OpenAI-format chunks to the ark-broker service."""

import json
import logging
import time
from typing import Optional
from urllib.parse import quote

import httpx

from .streaming_config import get_streaming_config, get_streaming_base_url

try:
    from .k8s import init_k8s, create_api_client
except ImportError:
    init_k8s = None  # type: ignore[assignment]
    create_api_client = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_STREAM_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=None, pool=5.0)
_COMPLETE_TIMEOUT = httpx.Timeout(10.0)
_MESSAGES_TIMEOUT = httpx.Timeout(10.0)

# Pagination bounds for loading conversation history (match the broker MAX_LIMIT and the Go
# completions executor's MessagesPageLimit / MessagesMaxPages).
_MESSAGES_PAGE_LIMIT = 1000
_MESSAGES_MAX_PAGES = 1000

_cached_broker_url: Optional[str] = None
_broker_url_cached = False


async def discover_broker_url(namespace: str) -> Optional[str]:
    """Discover the ark-broker streaming base URL from the ark-config-streaming ConfigMap.

    Returns the base URL or None if the ConfigMap is absent or streaming is disabled.
    Result is cached for the lifetime of the process.
    """
    global _cached_broker_url, _broker_url_cached
    if _broker_url_cached:
        return _cached_broker_url

    try:
        from kubernetes_asyncio import client
        await init_k8s()
        async with create_api_client() as api:
            v1 = client.CoreV1Api(api)
            config = await get_streaming_config(v1, namespace)
            if config and config.enabled:
                _cached_broker_url = await get_streaming_base_url(config, namespace, v1)
            else:
                _cached_broker_url = None
    except Exception as e:
        logger.warning(f"Broker discovery failed: {e}")
        _cached_broker_url = None

    _broker_url_cached = True
    return _cached_broker_url


class BrokerClient:
    """Sends OpenAI-format completion chunks to the ark-broker streaming endpoint."""

    def __init__(self, base_url: str, query_name: str, session_id: str = "", agent_name: str = "", message_ttl_seconds: Optional[int] = None):
        self.base_url = base_url
        self.query_name = query_name
        self.session_id = session_id
        self.agent_name = agent_name
        self.message_ttl_seconds = message_ttl_seconds

    def _build_chunk(
        self,
        content: str,
        finish_reason: Optional[str] = None,
        tool_calls: Optional[list[dict]] = None,
    ) -> bytes:
        delta: dict = {
            "role": "assistant",
            "content": content,
        }
        if tool_calls:
            delta["tool_calls"] = tool_calls
        chunk = {
            "id": self.query_name,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": f"agent/{self.agent_name}" if self.agent_name else "unknown",
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }],
            "ark": {
                "query": self.query_name,
                "session": self.session_id,
                "agent": self.agent_name,
            },
        }
        return (json.dumps(chunk) + "\n").encode()

    async def send_chunk(
        self,
        content: str,
        finish_reason: Optional[str] = None,
        tool_calls: Optional[list[dict]] = None,
    ) -> None:
        url = f"{self.base_url}/stream/{quote(self.query_name)}"
        try:
            async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as http:
                resp = await http.post(
                    url,
                    content=self._build_chunk(content, finish_reason, tool_calls),
                    headers={"Content-Type": "application/x-ndjson"},
                )
                if resp.status_code not in (200, 202):
                    logger.warning(f"Broker stream returned {resp.status_code} for query {self.query_name}")
        except Exception as e:
            logger.warning(f"Failed to send chunk to broker for query {self.query_name}: {e}")

    async def send_event(self, event: dict) -> None:
        """Post a raw event object to the stream as one NDJSON line.

        Unlike send_chunk (which wraps content in an OpenAI chat.completion.chunk), this
        sends the event verbatim — used for control events like tool_approval_request that
        the dashboard matches on their top-level `type` field.
        """
        url = f"{self.base_url}/stream/{quote(self.query_name)}"
        try:
            async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as http:
                resp = await http.post(
                    url,
                    content=(json.dumps(event) + "\n").encode(),
                    headers={"Content-Type": "application/x-ndjson"},
                )
                if resp.status_code not in (200, 202):
                    logger.warning(f"Broker event returned {resp.status_code} for query {self.query_name}")
        except Exception as e:
            logger.warning(f"Failed to send event to broker for query {self.query_name}: {e}")

    async def complete(self) -> None:
        url = f"{self.base_url}/stream/{quote(self.query_name)}/complete"
        try:
            async with httpx.AsyncClient(timeout=_COMPLETE_TIMEOUT) as http:
                resp = await http.post(url, json={})
                if resp.status_code not in (200, 202):
                    logger.warning(f"Broker complete returned {resp.status_code} for query {self.query_name}")
        except Exception as e:
            logger.warning(f"Failed to notify broker completion for query {self.query_name}: {e}")

    async def send_messages(self, conversation_id: str, messages: list[dict]) -> None:
        url = f"{self.base_url}/messages"
        payload: dict = {
            "conversation_id": conversation_id,
            "query_id": self.query_name,
            "messages": messages,
        }
        if self.message_ttl_seconds is not None:
            payload["ttl_seconds"] = self.message_ttl_seconds
        try:
            async with httpx.AsyncClient(timeout=_MESSAGES_TIMEOUT) as http:
                resp = await http.post(url, json=payload)
                if resp.status_code not in (200, 202):
                    logger.warning(f"Broker /messages returned {resp.status_code} for query {self.query_name}")
        except Exception as e:
            logger.warning(f"Failed to send messages to broker for query {self.query_name}: {e}")

    async def create_conversation(self) -> Optional[str]:
        """Mint a new conversation id (POST /conversations). Returns the id or None on failure.

        Mirrors the completions executor, which creates a conversation when a query carries none,
        so the id can be returned to the controller (as the A2A contextId) for follow-up turns."""
        url = f"{self.base_url}/conversations"
        try:
            async with httpx.AsyncClient(timeout=_MESSAGES_TIMEOUT) as http:
                resp = await http.post(url, json={})
                if resp.status_code not in (200, 201):
                    logger.warning(f"Broker /conversations returned {resp.status_code}")
                    return None
                return resp.json().get("conversation_id")
        except Exception as e:
            logger.warning(f"Failed to create conversation on broker: {e}")
            return None

    async def get_messages(self, conversation_id: str) -> list[dict]:
        """Load the full conversation history (oldest-first, OpenAI-format) from the broker,
        paginating on hasMore/nextCursor. Warn-and-return-partial on any error; never raises.

        This is the read half that brings ark-sdk executors to parity with the Go completions
        executor (which loads history via GET /messages before each turn)."""
        if not conversation_id:
            return []
        url = f"{self.base_url}/messages"
        messages: list[dict] = []
        cursor: Optional[int] = None
        try:
            async with httpx.AsyncClient(timeout=_MESSAGES_TIMEOUT) as http:
                for _ in range(_MESSAGES_MAX_PAGES):
                    params: dict = {
                        "conversation_id": conversation_id,
                        "limit": _MESSAGES_PAGE_LIMIT,
                    }
                    if cursor is not None:
                        params["cursor"] = cursor
                    resp = await http.get(url, params=params)
                    if resp.status_code != 200:
                        logger.warning(
                            f"Broker GET /messages returned {resp.status_code} for conversation {conversation_id}"
                        )
                        break
                    body = resp.json()
                    for item in body.get("items") or []:
                        msg = item.get("message")
                        if isinstance(msg, str):
                            try:
                                msg = json.loads(msg)
                            except json.JSONDecodeError:
                                continue
                        if isinstance(msg, dict):
                            messages.append(msg)
                    if not body.get("hasMore"):
                        break
                    next_cursor = body.get("nextCursor")
                    # Guard against a missing / non-advancing cursor to avoid an infinite loop.
                    if next_cursor is None or (cursor is not None and next_cursor <= cursor):
                        logger.warning("Broker pagination cursor did not advance; stopping")
                        break
                    cursor = next_cursor
        except Exception as e:
            logger.warning(f"Failed to load messages from broker for conversation {conversation_id}: {e}")
        return messages

    def _build_final_chunk(
        self,
        response_text: str,
        response_messages: Optional[list[dict]] = None,
        token_usage: Optional[dict] = None,
    ) -> bytes:
        completed_query: dict = {
            "metadata": {"name": self.query_name},
            "status": {
                "phase": "done",
                "conversationId": self.session_id,
                "response": {
                    "content": response_text,
                    "phase": "done",
                },
            },
        }
        if response_messages:
            completed_query["status"]["response"]["raw"] = json.dumps(response_messages)
        if token_usage:
            completed_query["status"]["tokenUsage"] = token_usage

        chunk = {
            "id": "chatcmpl-final",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": f"agent/{self.agent_name}" if self.agent_name else "unknown",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": ""},
                "finish_reason": "stop",
            }],
            "ark": {
                "query": self.query_name,
                "session": self.session_id,
                "agent": self.agent_name,
                "completedQuery": completed_query,
            },
        }
        return (json.dumps(chunk) + "\n").encode()

    async def send_final_chunk(
        self,
        response_text: str,
        response_messages: Optional[list[dict]] = None,
        token_usage: Optional[dict] = None,
    ) -> None:
        url = f"{self.base_url}/stream/{quote(self.query_name)}"
        payload = self._build_final_chunk(response_text, response_messages, token_usage)
        try:
            async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as http:
                resp = await http.post(
                    url,
                    content=payload,
                    headers={"Content-Type": "application/x-ndjson"},
                )
                if resp.status_code not in (200, 202):
                    logger.warning(f"Broker final chunk returned {resp.status_code} for query {self.query_name}")
        except Exception as e:
            logger.warning(f"Failed to send final chunk to broker for query {self.query_name}: {e}")
