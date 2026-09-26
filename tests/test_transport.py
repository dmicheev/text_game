"""Тесты нейтрального транспортного слоя: FSM, роутер, нотификатор."""

import pytest

from bot_game_book.notifier import Notifier, split_text
from bot_game_book.transport.fsm import MemoryFSMStorage
from bot_game_book.transport.router import Deps, Router, parse_command
from bot_game_book.transport.types import (
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    PlatformUser,
)


class FakeGateway:
    def __init__(self, platform: str = "telegram") -> None:
        self.platform = platform
        self.sent: list[tuple[int, str, Keyboard | None]] = []
        self.edits: list[tuple[int, str, str]] = []

    async def send_message(self, chat_id, text, keyboard=None):
        self.sent.append((chat_id, text, keyboard))
        return f"msg{len(self.sent)}"

    async def edit_message(self, chat_id, message_id, text, keyboard=None):
        self.edits.append((chat_id, message_id, text))
        return True

    async def delete_message(self, chat_id, message_id):
        pass

    async def answer_callback(self, callback_id, text=None, alert=False):
        pass


def make_message(text: str, user_id: int = 1, platform: str = "telegram"):
    return IncomingMessage(
        platform=platform,
        user=PlatformUser(platform=platform, user_id=user_id, name="Tester"),
        chat_id=user_id,
        message_id="10",
        text=text,
    )


def make_callback(data: str, user_id: int = 1, platform: str = "telegram"):
    return IncomingCallback(
        platform=platform,
        user=PlatformUser(platform=platform, user_id=user_id, name="Tester"),
        chat_id=user_id,
        message_id="10",
        data=data,
        callback_id="cb1",
    )


def make_deps() -> Deps:
    return Deps(
        session_maker=None, orchestrator=None, generator=None, notifier=None, settings=None
    )


class TestFSM:
    async def test_state_and_data_are_per_user(self):
        storage = MemoryFSMStorage()
        u1 = make_message("x", user_id=1)
        u2 = make_message("x", user_id=2)
        c1 = storage.context_for(u1)
        await c1.set_state("turn:twist")
        await c1.update_data(game_id=5)
        c2 = storage.context_for(u2)
        assert await c2.get_state() is None
        assert await c1.get_state() == "turn:twist"
        assert (await c1.get_data())["game_id"] == 5
        await c1.clear()
        assert await c1.get_state() is None
        assert await c1.get_data() == {}

    async def test_same_user_different_platforms(self):
        storage = MemoryFSMStorage()
        tg = make_message("x", user_id=1, platform="telegram")
        mx = make_message("x", user_id=1, platform="max")
        await storage.context_for(tg).set_state("s1")
        assert await storage.context_for(mx).get_state() is None


class TestRouter:
    async def test_command_routing(self):
        router = Router()
        calls = []

        async def start(ctx):
            calls.append("start")

        async def fallback(ctx):
            calls.append("msg")

        router.command("start", start)
        router.message(fallback)
        gw = FakeGateway()
        await router.dispatch(make_message("/start"), gw, make_deps())
        assert calls == ["start"]
        await router.dispatch(make_message("hello"), gw, make_deps())
        assert calls == ["start", "msg"]

    async def test_callback_prefix(self):
        router = Router()
        calls = []

        async def turn(ctx):
            calls.append(ctx.update.data)

        router.callback("turn:", turn)
        gw = FakeGateway()
        assert await router.dispatch(make_callback("turn:42"), gw, make_deps())
        assert calls == ["turn:42"]
        assert not await router.dispatch(make_callback("other:1"), gw, make_deps())

    async def test_state_bound_message_wins_over_stateless(self):
        router = Router()
        calls = []

        async def dialog(ctx):
            calls.append("dialog")

        async def fallback(ctx):
            calls.append("fallback")

        router.message(fallback)
        router.message(dialog, state="turn:twist")
        storage = router.fsm_storage
        upd = make_message("текст пожeлания")
        await storage.context_for(upd).set_state("turn:twist")
        gw = FakeGateway()
        await router.dispatch(upd, gw, make_deps())
        assert calls == ["dialog"]

    async def test_command_still_works_in_state(self):
        router = Router()
        calls = []

        async def cancel(ctx):
            calls.append("cancel")

        async def dialog(ctx):
            calls.append("dialog")

        router.message(dialog, state="turn:twist")
        router.command("cancel", cancel)
        upd = make_message("/cancel")
        await router.fsm_storage.context_for(upd).set_state("turn:twist")
        gw = FakeGateway()
        await router.dispatch(upd, gw, make_deps())
        assert calls == ["cancel"]

    async def test_fallback_does_not_eat_commands_registered_later(self):
        router = Router()
        calls = []

        async def fallback(ctx):
            calls.append("fallback")

        async def newgame(ctx):
            calls.append("newgame")

        router.message(fallback)  # фолбэк зарегистрирован раньше
        router.command("newgame", newgame)  # команда позже
        gw = FakeGateway()
        await router.dispatch(make_message("/newgame"), gw, make_deps())
        assert calls == ["newgame"]

    async def test_fallback_catches_plain_text(self):
        router = Router()
        calls = []

        async def fallback(ctx):
            calls.append("fallback")

        router.message(fallback)
        gw = FakeGateway()
        await router.dispatch(make_message("просто текст"), gw, make_deps())
        assert calls == ["fallback"]


class TestParseCommand:
    def test_simple(self):
        assert parse_command("/start") == "start"
        assert parse_command("/newgame тема") == "newgame"
        assert parse_command("/help@my_bot") == "help"

    def test_not_command(self):
        assert parse_command("hello") is None
        assert parse_command("/") is None


class TestNotifier:
    async def test_routes_by_platform(self):
        tg = FakeGateway("telegram")
        mx = FakeGateway("max")
        notifier = Notifier({"telegram": tg, "max": mx})

        class U:
            platform = "max"
            platform_user_id = 77

        await notifier.send_user(U(), "привет")  # type: ignore[arg-type]
        assert len(mx.sent) == 1
        assert mx.sent[0][0] == 77
        assert tg.sent == []

    async def test_splits_long_text_keyboard_on_last_part(self):
        tg = FakeGateway("telegram")
        notifier = Notifier({"telegram": tg})
        text = "\n\n".join(f"para {i} " + "x" * 2000 for i in range(5))
        await notifier.send("telegram", 1, text, [[__import__("bot_game_book.transport.types", fromlist=["Button"]).Button("ok", "ok")]])
        assert len(tg.sent) > 1
        assert all(kb is None for _cid, _t, kb in tg.sent[:-1])
        assert tg.sent[-1][2] is not None

    async def test_edit_or_send_returns_same_id_on_success(self):
        tg = FakeGateway("telegram")
        notifier = Notifier({"telegram": tg})
        assert await notifier.edit_or_send("telegram", 5, "99", "текст") == "99"
        assert tg.sent == []

    async def test_edit_or_send_falls_back_on_failure(self):
        class NoEditGateway(FakeGateway):
            async def edit_message(self, chat_id, message_id, text, keyboard=None):
                return False

        tg = NoEditGateway("telegram")
        notifier = Notifier({"telegram": tg})
        result = await notifier.edit_or_send("telegram", 5, "99", "текст")
        assert result == "msg1"
        assert tg.sent[0][0] == 5


class TestSplitText:
    def test_short_text_single_part(self):
        assert split_text("abc") == ["abc"]

    def test_respects_paragraph_boundaries(self):
        parts = split_text("a" * 100 + "\n\n" + "b" * 3700)
        assert len(parts) == 2
        assert all(len(p) <= 3800 for p in parts)
