"""Tests for the BrokerClient conversation-history read half (get_messages / create_conversation).

Placed under test_overlay/ so the `make ark-sdk-test` target (pytest test test_overlay) collects
them — the sibling ark_sdk/test_broker.py is not on that target's path.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ark_sdk.broker import BrokerClient


def _mock_http(**methods):
    """Build a mocked httpx.AsyncClient context manager with the given async methods.

    A list value is used as side_effect (successive responses); a scalar as return_value.
    """
    http = AsyncMock()
    for name, val in methods.items():
        setattr(
            http,
            name,
            AsyncMock(side_effect=val) if isinstance(val, list) else AsyncMock(return_value=val),
        )
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    return http


def _resp(status, body=None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body or {})
    return r


class TestBrokerClientCreateConversation:
    @pytest.mark.anyio
    async def test_returns_conversation_id(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        http = _mock_http(post=_resp(201, {"conversation_id": "conv-xyz"}))
        with patch("httpx.AsyncClient", return_value=http):
            cid = await client.create_conversation()
        assert cid == "conv-xyz"
        assert http.post.call_args[0][0] == "http://broker:3000/conversations"

    @pytest.mark.anyio
    async def test_accepts_200(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        http = _mock_http(post=_resp(200, {"conversation_id": "c1"}))
        with patch("httpx.AsyncClient", return_value=http):
            assert await client.create_conversation() == "c1"

    @pytest.mark.anyio
    async def test_returns_none_on_failure(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        http = _mock_http(post=_resp(500))
        with patch("httpx.AsyncClient", return_value=http):
            assert await client.create_conversation() is None


class TestBrokerClientGetMessages:
    @pytest.mark.anyio
    async def test_empty_id_returns_empty_without_call(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        http = _mock_http(get=_resp(200, {}))
        with patch("httpx.AsyncClient", return_value=http):
            assert await client.get_messages("") == []
        http.get.assert_not_called()

    @pytest.mark.anyio
    async def test_single_page_ordered(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        body = {"items": [
            {"message": {"role": "user", "content": "hi"}},
            {"message": {"role": "assistant", "content": "hello"}},
        ], "hasMore": False}
        http = _mock_http(get=_resp(200, body))
        with patch("httpx.AsyncClient", return_value=http):
            msgs = await client.get_messages("conv-1")
        assert msgs == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert http.get.call_args[0][0] == "http://broker:3000/messages"
        assert http.get.call_args[1]["params"]["conversation_id"] == "conv-1"
        assert http.get.call_args[1]["params"]["limit"] == 1000

    @pytest.mark.anyio
    async def test_paginates_on_has_more(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        p1 = _resp(200, {"items": [{"message": {"role": "user", "content": "1"}}], "hasMore": True, "nextCursor": 5})
        p2 = _resp(200, {"items": [{"message": {"role": "assistant", "content": "2"}}], "hasMore": False})
        http = _mock_http(get=[p1, p2])
        with patch("httpx.AsyncClient", return_value=http):
            msgs = await client.get_messages("conv-1")
        assert [m["content"] for m in msgs] == ["1", "2"]
        assert http.get.call_count == 2
        assert http.get.call_args_list[1][1]["params"]["cursor"] == 5

    @pytest.mark.anyio
    async def test_stops_on_non_advancing_cursor(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        page = _resp(200, {"items": [{"message": {"role": "user", "content": "x"}}], "hasMore": True, "nextCursor": None})
        http = _mock_http(get=page)
        with patch("httpx.AsyncClient", return_value=http):
            msgs = await client.get_messages("conv-1")
        assert [m["content"] for m in msgs] == ["x"]
        assert http.get.call_count == 1

    @pytest.mark.anyio
    async def test_non_200_returns_partial(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        http = _mock_http(get=_resp(404))
        with patch("httpx.AsyncClient", return_value=http):
            assert await client.get_messages("conv-1") == []

    @pytest.mark.anyio
    async def test_message_as_json_string(self):
        client = BrokerClient("http://broker:3000", "q", "", "a")
        body = {"items": [{"message": json.dumps({"role": "user", "content": "hi"})}], "hasMore": False}
        http = _mock_http(get=_resp(200, body))
        with patch("httpx.AsyncClient", return_value=http):
            assert await client.get_messages("conv-1") == [{"role": "user", "content": "hi"}]
