"""Протокол шлюза мессенджера: минимальный набор операций бота."""

from typing import Protocol

from bot_game_book.transport.types import Keyboard

MESSAGE_SPLIT_LIMIT = 3800


class BotGateway(Protocol):
    """Единый интерфейс доставки для всех мессенджеров."""

    platform: str

    async def send_message(
        self, chat_id: int, text: str, keyboard: Keyboard | None = None
    ) -> str | None:
        """Отправить сообщение; вернуть id сообщения или None при неудаче."""
        ...

    async def edit_message(
        self,
        chat_id: int,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> bool:
        """Отредактировать текст (и клавиатуру) своего сообщения."""
        ...

    async def delete_message(self, chat_id: int, message_id: str) -> None:
        """Удалить своё сообщение; ошибки молча игнорируются."""
        ...

    async def answer_callback(
        self, callback_id: str | None, text: str | None = None, alert: bool = False
    ) -> None:
        """Ответить на нажатие кнопки (закрывает индикатор загрузки)."""
        ...
