"""Адаптер MAX (platform-api2.max.ru): REST-клиент + long polling."""

import asyncio
import logging

import httpx

from bot_game_book.transport.gateway import BotGateway
from bot_game_book.transport.router import Deps, Router
from bot_game_book.transport.types import (
    MAX,
    Button,
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    PlatformUser,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://platform-api2.max.ru"


def keyboard_to_attachments(keyboard: Keyboard | None) -> list[dict] | None:
    if keyboard is None:
        return None
    rows = [
        [{"type": "callback", "text": b.text, "payload": b.data} for b in row]
        for row in keyboard
    ]
    return [{"type": "inline_keyboard", "payload": {"buttons": rows}}]


class MaxAPIError(Exception):
    pass


class MaxClient:
    def __init__(self, access_token: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": access_token},
            timeout=httpx.Timeout(90.0, connect=15.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        response = await self._client.request(method, path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    async def get_updates(
        self,
        marker: int | None = None,
        types: str = "message_created,message_callback",
        timeout: int = 30,
        limit: int = 100,
    ) -> dict:
        params: dict = {"types": types, "timeout": timeout, "limit": limit}
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params)

    async def send_message(
        self, user_id: int, text: str, keyboard: Keyboard | None
    ) -> str | None:
        body: dict = {"user_id": user_id, "text": text}
        attachments = keyboard_to_attachments(keyboard)
        if attachments is not None:
            body["attachments"] = attachments
        result = await self._request("POST", "/messages", json=body)
        message = result.get("message") or {}
        message_id = message.get("message_id")
        return str(message_id) if message_id is not None else None

    async def edit_message(
        self, chat_id: int, message_id: str, text: str, keyboard: Keyboard | None
    ) -> dict:
        body: dict = {"text": text}
        attachments = keyboard_to_attachments(keyboard)
        if attachments is not None:
            body["attachments"] = attachments
        return await self._request(
            "PUT",
            "/messages",
            params={"chat_id": chat_id, "message_id": message_id},
            json=body,
        )

    async def delete_message(self, chat_id: int, message_id: str) -> dict:
        return await self._request(
            "DELETE", "/messages", params={"chat_id": chat_id, "message_id": message_id}
        )

    async def answer_callback(self, callback_id: str, notification: str | None) -> dict:
        body: dict = {"callback_id": callback_id}
        if notification:
            body["notification"] = notification
        return await self._request("POST", "/answers", json=body)


class MaxGateway:
    platform = MAX

    def __init__(self, client: MaxClient) -> None:
        self._client = client

    async def send_message(
        self, chat_id: int, text: str, keyboard: Keyboard | None = None
    ) -> str | None:
        try:
            return await self._client.send_message(chat_id, text, keyboard)
        except httpx.HTTPError as e:
            logger.warning("max send to %s failed: %s", chat_id, e)
            return None

    async def edit_message(
        self,
        chat_id: int,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> bool:
        try:
            await self._client.edit_message(chat_id, message_id, text, keyboard)
            return True
        except httpx.HTTPError as e:
            logger.warning("max edit %s failed: %s", message_id, e)
            return False

    async def delete_message(self, chat_id: int, message_id: str) -> None:
        try:
            await self._client.delete_message(chat_id, message_id)
        except httpx.HTTPError as e:
            logger.warning("max delete %s failed: %s", message_id, e)

    async def answer_callback(
        self, callback_id: str | None, text: str | None = None, alert: bool = False
    ) -> None:
        if callback_id is None:
            return
        try:
            await self._client.answer_callback(callback_id, text)
        except httpx.HTTPError as e:
            logger.warning("max answer callback failed: %s", e)


def _user_from_max(raw: dict) -> PlatformUser:
    return PlatformUser(
        platform=MAX,
        user_id=raw.get("user_id", 0),
        username=raw.get("username"),
        name=raw.get("name"),
    )


def _chat_id_from_message(message: dict, fallback_user_id: int) -> int:
    recipient = message.get("recipient") or {}
    return recipient.get("chat_id", fallback_user_id)


def convert_max_update(raw: dict) -> tuple[IncomingMessage | IncomingCallback, ...] | None:
    """MAX update (dict) -> нейтральный апдейт. Возвращает кортеж из одного."""
    update_type = raw.get("update_type")
    if update_type == "message_created":
        message = raw.get("message") or {}
        text = (message.get("body") or {}).get("text") or message.get("text") or ""
        sender = message.get("sender") or {}
        user = _user_from_max(sender)
        return (
            IncomingMessage(
                platform=MAX,
                user=user,
                chat_id=_chat_id_from_message(message, user.user_id),
                message_id=str(message.get("message_id", "")),
                text=text,
            ),
        )
    if update_type == "message_callback":
        callback = raw.get("callback") or {}
        message = raw.get("message") or {}
        user = _user_from_max(callback.get("user") or {})
        return (
            IncomingCallback(
                platform=MAX,
                user=user,
                chat_id=_chat_id_from_message(message, user.user_id),
                message_id=str(message.get("message_id", "")),
                data=callback.get("payload") or "",
                callback_id=str(callback.get("callback_id"))
                if callback.get("callback_id") is not None
                else None,
            ),
        )
    return None


async def run_max_polling(
    gateway: MaxGateway, router: Router, deps: Deps, poll_seconds: int = 30
) -> None:
    """Long polling цикл GET /updates."""
    client = gateway._client  # noqa: SLF001
    marker: int | None = None
    logger.info("max polling started")
    while True:
        try:
            result = await client.get_updates(marker=marker, timeout=poll_seconds)
            marker = result.get("marker", marker)
            for raw in result.get("updates", []):
                converted = convert_max_update(raw)
                if converted is None:
                    continue
                for update in converted:
                    await router.dispatch(update, gateway, deps)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("max polling error: %s", e)
            await asyncio.sleep(3)
