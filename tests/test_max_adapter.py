"""Тесты MAX-адаптера: конвертации и REST-вызовы через MockTransport."""

import json

import httpx
import pytest

from bot_game_book.adapters.max_adapter import (
    MaxClient,
    MaxGateway,
    convert_max_update,
    keyboard_to_attachments,
)
from bot_game_book.transport.types import Button


class TestKeyboardConversion:
    def test_none(self):
        assert keyboard_to_attachments(None) is None

    def test_rows_and_buttons(self):
        kb = [[Button("Один", "a:1"), Button("Два", "b:2")], [Button("Три", "c:3")]]
        attachments = keyboard_to_attachments(kb)
        assert attachments == [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [
                            {"type": "callback", "text": "Один", "payload": "a:1"},
                            {"type": "callback", "text": "Два", "payload": "b:2"},
                        ],
                        [{"type": "callback", "text": "Три", "payload": "c:3"}],
                    ]
                },
            }
        ]


class TestUpdateConversion:
    def test_message_created(self):
        raw = {
            "update_type": "message_created",
            "message": {
                "message_id": "mid.1",
                "text": "/start",
                "sender": {"user_id": 42, "name": "Anna", "username": "anna"},
                "recipient": {"chat_id": 4200, "user_id": 42},
            },
        }
        (update,) = convert_max_update(raw)
        assert update.platform == "max"
        assert update.user.user_id == 42
        assert update.user.username == "anna"
        assert update.chat_id == 4200
        assert update.message_id == "mid.1"
        assert update.text == "/start"

    def test_message_callback(self):
        raw = {
            "update_type": "message_callback",
            "callback": {
                "callback_id": "cb.9",
                "payload": "turn:3",
                "user": {"user_id": 42, "name": "Anna"},
            },
            "message": {
                "message_id": "mid.2",
                "recipient": {"chat_id": 4200},
            },
        }
        (update,) = convert_max_update(raw)
        assert update.data == "turn:3"
        assert update.callback_id == "cb.9"
        assert update.chat_id == 4200
        assert update.message_id == "mid.2"

    def test_unknown_type(self):
        assert convert_max_update({"update_type": "message_removed"}) is None

    def test_chat_id_falls_back_to_user(self):
        raw = {
            "update_type": "message_created",
            "message": {
                "message_id": "m",
                "text": "hi",
                "sender": {"user_id": 7},
            },
        }
        (update,) = convert_max_update(raw)
        assert update.chat_id == 7


class TestMaxClient:
    def _client(self, handler) -> MaxClient:
        transport = httpx.MockTransport(handler)
        client = MaxClient("test-token")
        client._client = httpx.AsyncClient(
            base_url="https://example.test",
            headers={"Authorization": "test-token"},
            transport=transport,
            timeout=10,
        )
        return client

    async def test_send_message_payload(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"message": {"message_id": "abc"}})

        client = self._client(handler)
        message_id = await client.send_message(
            42, "текст", [[Button("ок", "ok:1")]]
        )
        assert message_id == "abc"
        request = requests[0]
        assert request.method == "POST"
        assert request.url.path == "/messages"
        body = json.loads(request.content)
        assert body["user_id"] == 42
        assert body["text"] == "текст"
        assert body["attachments"][0]["type"] == "inline_keyboard"
        assert request.headers["Authorization"] == "test-token"

    async def test_get_updates_marker(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200, json={"updates": [], "marker": 12}
            )

        client = self._client(handler)
        result = await client.get_updates(marker=5, timeout=1)
        assert result["marker"] == 12
        assert "marker=5" in str(calls[0].url)
        assert "message_created" in str(calls[0].url)

    async def test_edit_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"message": {}})

        client = self._client(handler)
        result = await client.edit_message(7, "mid.1", "новый текст", None)
        assert result == {"message": {}}

    async def test_answer_callback(self):
        bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={})

        client = self._client(handler)
        await client.answer_callback("cb.1", "готово")
        assert bodies == [{"callback_id": "cb.1", "notification": "готово"}]


class TestMaxGateway:
    async def test_send_failure_returns_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        transport = httpx.MockTransport(handler)
        client = MaxClient("t")
        client._client = httpx.AsyncClient(
            base_url="https://example.test", transport=transport, timeout=5
        )
        gateway = MaxGateway(client)
        assert await gateway.send_message(1, "x") is None

    async def test_send_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"message": {"message_id": "m1"}})

        transport = httpx.MockTransport(handler)
        client = MaxClient("t")
        client._client = httpx.AsyncClient(
            base_url="https://example.test", transport=transport, timeout=5
        )
        gateway = MaxGateway(client)
        assert await gateway.send_message(1, "x") == "m1"
