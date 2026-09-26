"""Универсальный роутер команд, callback-ов и текстовых сообщений."""

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from bot_game_book.transport.fsm import FSMContext, MemoryFSMStorage
from bot_game_book.transport.gateway import BotGateway
from bot_game_book.transport.types import (
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    Update,
)

logger = logging.getLogger(__name__)

Handler = Callable[["Context"], Awaitable[None]]


@dataclass
class Deps:
    session_maker: Any
    orchestrator: Any
    generator: Any
    notifier: Any
    settings: Any
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Rule:
    kind: str  # "command" | "callback" | "message"
    pattern: str | None
    handler: Handler
    state: str | None = None


class Context:
    """Контекст одного апдейта: хелперы отправки + зависимости."""

    def __init__(
        self,
        update: Update,
        gateway: BotGateway,
        deps: Deps,
        fsm: FSMContext,
    ) -> None:
        self.update = update
        self.gateway = gateway
        self.deps = deps
        self.fsm = fsm
        self.user = update.user
        self.chat_id = update.chat_id

    @property
    def is_callback(self) -> bool:
        return isinstance(self.update, IncomingCallback)

    @property
    def message_text(self) -> str:
        return self.update.text if isinstance(self.update, IncomingMessage) else ""

    async def reply(self, text: str, keyboard: Keyboard | None = None) -> str | None:
        return await self.gateway.send_message(self.chat_id, text, keyboard)

    async def edit(self, text: str, keyboard: Keyboard | None = None) -> bool:
        if isinstance(self.update, IncomingCallback) and self.update.message_id:
            return await self.gateway.edit_message(
                self.chat_id, self.update.message_id, text, keyboard
            )
        await self.reply(text, keyboard)
        return True

    async def delete(self) -> None:
        if isinstance(self.update, IncomingCallback) and self.update.message_id:
            await self.gateway.delete_message(self.chat_id, self.update.message_id)

    async def answer(self, text: str | None = None, alert: bool = False) -> None:
        callback_id = (
            self.update.callback_id if isinstance(self.update, IncomingCallback) else None
        )
        await self.gateway.answer_callback(callback_id, text, alert)


def parse_command(text: str) -> str | None:
    """'/cmd@bot arg' → 'cmd'; не команда → None."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    token = stripped.split(maxsplit=1)[0]
    name = token.lstrip("/").split("@", 1)[0]
    return name or None


class Router:
    def __init__(self) -> None:
        self._rules: list[_Rule] = []
        self.fsm_storage = MemoryFSMStorage()

    def command(self, name: str, handler: Handler) -> None:
        self._rules.append(_Rule("command", name, handler))

    def callback(self, prefix: str, handler: Handler, state: str | None = None) -> None:
        self._rules.append(_Rule("callback", prefix, handler, state))

    def message(self, handler: Handler, state: str | None = None) -> None:
        self._rules.append(_Rule("message", None, handler, state))

    def _match(self, update: Update, state: str | None) -> _Rule | None:
        stateful_first = sorted(
            self._rules, key=lambda r: 0 if r.state is not None else 1
        )
        is_command = not isinstance(update, IncomingCallback) and parse_command(
            update.text
        ) is not None
        for rule in stateful_first:
            if rule.state is not None and rule.state != state:
                continue
            if isinstance(update, IncomingCallback):
                if rule.kind != "callback" or not update.data.startswith(rule.pattern):
                    continue
            else:
                if rule.kind == "callback":
                    continue
                if rule.kind == "command":
                    if parse_command(update.text) != rule.pattern:
                        continue
                else:
                    # stateless текст (фолбэк) не ловит команды и FSM-диалог
                    if rule.state is None and (is_command or state is not None):
                        continue
                    # state-диалог не ловит команды (их слушают command-правила)
                    if rule.state is not None and is_command:
                        continue
            return rule
        return None

    async def dispatch(self, update: Update, gateway: BotGateway, deps: Deps) -> bool:
        fsm = self.fsm_storage.context_for(update)
        state = await fsm.get_state()
        rule = self._match(update, state)
        if rule is None:
            return False
        ctx = Context(update, gateway, deps, fsm)
        try:
            await rule.handler(ctx)
        except Exception:
            logger.exception(
                "handler %s failed (platform=%s user=%s)",
                rule.handler.__name__,
                update.user.platform,
                update.user.user_id,
            )
            try:
                await ctx.answer()
            except Exception:
                pass
        return True
