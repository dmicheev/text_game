"""Адаптер Telegram: aiogram Bot за нейтральным BotGateway."""

import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot_game_book.transport.gateway import BotGateway
from bot_game_book.transport.router import Deps, Router
from bot_game_book.transport.types import (
    TELEGRAM,
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    PlatformUser,
)

logger = logging.getLogger(__name__)


def to_telegram_keyboard(keyboard: Keyboard | None) -> InlineKeyboardMarkup | None:
    if keyboard is None:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b.text, callback_data=b.data) for b in row]
            for row in keyboard
        ]
    )


class TelegramGateway:
    platform = TELEGRAM

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_message(
        self, chat_id: int, text: str, keyboard: Keyboard | None = None
    ) -> str | None:
        try:
            msg = await self._bot.send_message(
                chat_id, text, reply_markup=to_telegram_keyboard(keyboard)
            )
            return str(msg.message_id)
        except TelegramForbiddenError:
            logger.warning("user %s blocked the bot", chat_id)
        except TelegramBadRequest as e:
            logger.warning("send to %s failed: %s", chat_id, e)
        return None

    async def edit_message(
        self,
        chat_id: int,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> bool:
        try:
            await self._bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=int(message_id),
                reply_markup=to_telegram_keyboard(keyboard),
            )
            return True
        except TelegramBadRequest as e:
            logger.warning("edit %s failed: %s", message_id, e)
            return False

    async def delete_message(self, chat_id: int, message_id: str) -> None:
        try:
            await self._bot.delete_message(chat_id, int(message_id))
        except TelegramAPIError as e:
            logger.warning("delete %s failed: %s", message_id, e)

    async def answer_callback(
        self, callback_id: str | None, text: str | None = None, alert: bool = False
    ) -> None:
        if callback_id is None:
            return
        try:
            await self._bot.answer_callback_query(callback_id, text=text, show_alert=alert)
        except TelegramAPIError as e:
            logger.warning("answer callback failed: %s", e)


def _platform_user(tg_user) -> PlatformUser:
    return PlatformUser(
        platform=TELEGRAM,
        user_id=tg_user.id,
        username=tg_user.username,
        name=tg_user.first_name,
    )


async def run_telegram_polling(
    bot: Bot, gateway: TelegramGateway, router: Router, deps: Deps
) -> None:
    """Единая точка входа aiogram: все апдейты нормализуются и уходят в роутер."""

    async def on_message(message: Message) -> None:
        if message.from_user is None or message.text is None:
            return
        update = IncomingMessage(
            platform=TELEGRAM,
            user=_platform_user(message.from_user),
            chat_id=message.chat.id,
            message_id=str(message.message_id),
            text=message.text,
        )
        await router.dispatch(update, gateway, deps)

    async def on_callback(cb: CallbackQuery) -> None:
        if cb.from_user is None or cb.data is None:
            return
        chat_id = cb.message.chat.id if cb.message else cb.from_user.id
        message_id = str(cb.message.message_id) if cb.message else None
        update = IncomingCallback(
            platform=TELEGRAM,
            user=_platform_user(cb.from_user),
            chat_id=chat_id,
            message_id=message_id or "",
            data=cb.data,
            callback_id=cb.id,
        )
        await router.dispatch(update, gateway, deps)

    dp = Dispatcher()
    dp.message.register(on_message)
    dp.callback_query.register(on_callback)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("telegram polling started")
    await dp.start_polling(bot)
