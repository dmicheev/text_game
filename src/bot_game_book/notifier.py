"""Мультиплатформенная доставка сообщений: маршрут по платформе получателя."""

import logging

from bot_game_book.models import User
from bot_game_book.transport.gateway import MESSAGE_SPLIT_LIMIT, BotGateway
from bot_game_book.transport.types import Keyboard

logger = logging.getLogger(__name__)


def split_text(text: str, limit: int = MESSAGE_SPLIT_LIMIT) -> list[str]:
    parts: list[str] = []
    buffer = ""
    for paragraph in text.split("\n\n"):
        chunk = paragraph if not buffer else f"{buffer}\n\n{paragraph}"
        while len(chunk) > limit:
            cut = chunk.rfind("\n", 0, limit)
            if cut <= 0:
                cut = limit
            parts.append(chunk[:cut])
            chunk = chunk[cut:].lstrip("\n")
        if len(chunk) > limit:
            parts.append(chunk[:limit])
            buffer = chunk[limit:]
        else:
            buffer = chunk
    if buffer:
        parts.append(buffer)
    return parts or [""]


class Notifier:
    def __init__(self, gateways: dict[str, BotGateway]) -> None:
        self._gateways = gateways

    def _gateway(self, platform: str) -> BotGateway | None:
        gateway = self._gateways.get(platform)
        if gateway is None:
            logger.warning("no gateway for platform %s", platform)
        return gateway

    async def send_user(
        self, user: User, text: str, keyboard: Keyboard | None = None
    ) -> None:
        await self.send(user.platform, user.platform_user_id, text, keyboard)

    async def send(
        self, platform: str, chat_id: int, text: str, keyboard: Keyboard | None = None
    ) -> None:
        gateway = self._gateway(platform)
        if gateway is None:
            return
        parts = split_text(text)
        for i, part in enumerate(parts):
            kb = keyboard if i == len(parts) - 1 else None
            await gateway.send_message(chat_id, part, kb)

    async def edit_or_send(
        self,
        platform: str,
        chat_id: int,
        message_id: str | None,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> str | None:
        gateway = self._gateway(platform)
        if gateway is None:
            return None
        if message_id is not None:
            try:
                if await gateway.edit_message(chat_id, message_id, text, keyboard):
                    return message_id
            except Exception as e:
                logger.warning("edit %s/%s failed: %s", platform, message_id, e)
        try:
            return await gateway.send_message(chat_id, text, keyboard)
        except Exception as e:
            logger.warning("dashboard send to %s/%s failed: %s", platform, chat_id, e)
            return None
