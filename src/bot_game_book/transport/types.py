"""Платформонезависимые типы транспортного слоя."""

from dataclasses import dataclass

TELEGRAM = "telegram"
MAX = "max"


@dataclass(frozen=True)
class Button:
    text: str
    data: str


Keyboard = list[list[Button]]


@dataclass(frozen=True)
class PlatformUser:
    platform: str
    user_id: int
    username: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class IncomingMessage:
    platform: str
    user: PlatformUser
    chat_id: int
    message_id: str
    text: str


@dataclass(frozen=True)
class IncomingCallback:
    platform: str
    user: PlatformUser
    chat_id: int
    message_id: str
    data: str
    callback_id: str | None = None


Update = IncomingMessage | IncomingCallback
