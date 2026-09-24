import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)


def split_text(text: str, limit: int = 3800) -> list[str]:
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
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(
        self, chat_id: int, text: str, keyboard: InlineKeyboardMarkup | None = None
    ) -> None:
        parts = split_text(text)
        for i, part in enumerate(parts):
            kb = keyboard if i == len(parts) - 1 else None
            try:
                await self._bot.send_message(chat_id, part, reply_markup=kb)
            except TelegramForbiddenError:
                logger.warning("user %s blocked the bot", chat_id)
            except TelegramBadRequest as e:
                logger.warning("send to %s failed: %s", chat_id, e)

    async def edit_or_send(
        self,
        chat_id: int,
        message_id: int | None,
        text: str,
        keyboard: InlineKeyboardMarkup | None = None,
    ) -> int | None:
        if message_id is not None:
            try:
                await self._bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=keyboard,
                )
                return message_id
            except TelegramBadRequest as e:
                logger.warning("edit %s failed: %s", message_id, e)
        try:
            msg = await self._bot.send_message(chat_id, text, reply_markup=keyboard)
            return msg.message_id
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.warning("dashboard send to %s failed: %s", chat_id, e)
            return None
