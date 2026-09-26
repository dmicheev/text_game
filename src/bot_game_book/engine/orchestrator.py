import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot_game_book.db import get_session_maker
from bot_game_book.engine.compiler import compile_book
from bot_game_book.engine.queue import next_position
from bot_game_book.engine.views import (
    dashboard_text,
    fmt_user,
    summaries_chain,
    turn_assigned_note,
    turn_prompt,
    utcnow,
)
from bot_game_book.keyboards import dashboard_kb, write_kb
from bot_game_book.llm.validator import ChapterDraft
from bot_game_book.models import (
    Chapter,
    Game,
    GameEvent,
    GamePlayer,
    GameStatus,
    PlayerStatus,
    User,
)
from bot_game_book.notifier import Notifier

logger = logging.getLogger(__name__)


class TurnOrchestrator:
    def __init__(self, notifier: Notifier) -> None:
        self._notifier = notifier
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, game_id: int) -> asyncio.Lock:
        return self._locks.setdefault(game_id, asyncio.Lock())

    async def get_game(self, session, game_id: int) -> Game | None:
        result = await session.execute(
            select(Game)
            .where(Game.id == game_id)
            .options(selectinload(Game.players).selectinload(GamePlayer.user))
        )
        return result.scalar_one_or_none()

    async def _log_event(self, session, game_id: int, type_: str, payload: dict) -> None:
        session.add(GameEvent(game_id=game_id, type=type_, payload=payload))

    def _active_positions(self, game: Game) -> list[int]:
        return sorted(
            p.position for p in game.players if p.status == PlayerStatus.active
        )

    def _player_at(self, game: Game, position: int) -> GamePlayer | None:
        return next((p for p in game.players if p.position == position), None)

    def _current_user(self, game: Game) -> User | None:
        player = next(
            (p for p in game.players if p.user_id == game.current_player_id), None
        )
        return player.user if player else None

    async def _last_summary(self, session, game: Game) -> str | None:
        result = await session.execute(
            select(Chapter.summary)
            .where(Chapter.game_id == game.id, Chapter.idx == game.current_chapter_idx - 1)
        )
        row = result.scalar_one_or_none()
        return row

    async def start_game(self, session, game: Game) -> None:
        game.status = GameStatus.running
        game.current_chapter_idx = 1
        game.consecutive_skips = 0
        game.player_cursor = -1
        game.current_player_id = None
        await self._log_event(session, game.id, "game_started", {})
        await self._assign_turn(session, game)
        await session.commit()

    async def _assign_turn(self, session, game: Game) -> None:
        positions = self._active_positions(game)
        if not positions:
            await self._cancel_game(session, game, "нет активных игроков")
            return
        game.player_cursor = next_position(positions, game.player_cursor)
        player = self._player_at(game, game.player_cursor)
        if player is None:
            await self._cancel_game(session, game, "очередь повреждена")
            return
        game.current_player_id = player.user_id
        game.turn_deadline = utcnow() + timedelta(hours=game.turn_timeout_hours)
        game.turn_assigned_at = utcnow()
        game.turn_reminded = False
        prev_summary = await self._last_summary(session, game)
        await self._notifier.send_user(
            player.user, turn_prompt(game, prev_summary), write_kb(game.id)
        )
        await self.refresh_dashboard(session, game)

    async def resend_turn(self, session, game: Game) -> None:
        user = self._current_user(game)
        if user is None:
            return
        prev_summary = await self._last_summary(session, game)
        await self._notifier.send_user(
            user, turn_prompt(game, prev_summary), write_kb(game.id)
        )
        await self.refresh_dashboard(session, game)

    async def refresh_dashboard(self, session, game: Game, confirm: str | None = None) -> None:
        if game.dashboard_chat_id is None:
            return
        host = await session.get(User, game.host_user_id)
        if host is None:
            return
        text = dashboard_text(game, game.players, utcnow())
        platform = game.dashboard_platform or host.platform
        message_id = await self._notifier.edit_or_send(
            platform,
            game.dashboard_chat_id,
            game.dashboard_message_id,
            text,
            dashboard_kb(game, confirm),
        )
        if message_id is not None and message_id != game.dashboard_message_id:
            game.dashboard_message_id = message_id
            game.dashboard_chat_id = host.platform_user_id
            game.dashboard_platform = host.platform

    async def confirm_chapter(
        self, session, game_id: int, draft: ChapterDraft, author_user_id: int
    ) -> str:
        async with self._lock_for(game_id):
            game = await self.get_game(session, game_id)
            if game is None or game.status != GameStatus.running:
                return "stale"
            if game.current_player_id != author_user_id:
                return "not_your_turn"
            session.add(
                Chapter(
                    game_id=game.id,
                    idx=game.current_chapter_idx,
                    author_user_id=author_user_id,
                    title=draft.title,
                    body=draft.chapter,
                    summary=draft.summary,
                    memory=draft.memory,
                )
            )
            await self._log_event(
                session,
                game.id,
                "chapter_confirmed",
                {"idx": game.current_chapter_idx, "author": author_user_id},
            )
            if game.current_chapter_idx >= game.chapters_total:
                await self._finish_game(session, game)
                outcome = "finished"
            else:
                game.current_chapter_idx += 1
                game.consecutive_skips = 0
                await self._assign_turn(session, game)
                outcome = "ok"
            await session.commit()
            return outcome

    async def skip_turn_by_id(self, game_id: int, reason: str) -> str:
        maker = get_session_maker()
        async with maker() as session:
            return await self.skip_turn(session, game_id, reason)

    async def skip_turn(self, session, game_id: int, reason: str) -> str:
        async with self._lock_for(game_id):
            game = await self.get_game(session, game_id)
            if game is None or game.status == GameStatus.finished:
                return "stale"
            skipped_user = self._current_user(game)
            game.consecutive_skips += 1
            await self._log_event(
                session,
                game.id,
                "turn_skipped",
                {"reason": reason, "player": game.current_player_id},
            )
            if game.consecutive_skips >= len(self._active_positions(game)):
                await self._cancel_game(session, game, f"пропуски подряд ({reason})")
                await session.commit()
                return "cancelled"
            if skipped_user is not None:
                await self._notifier.send_user(
                    skipped_user,
                    f"⏭ Твой ход в игре «{game.topic}» пропущен ({reason}). "
                    "Ты вернёшься в очередь на следующем круге.",
                )
            await self._assign_turn(session, game)
            await session.commit()
            return "ok"

    async def remind(self, session, game_id: int, source: str) -> bool:
        game = await self.get_game(session, game_id)
        if game is None or game.status != GameStatus.running:
            return False
        user = self._current_user(game)
        if user is None:
            return False
        await self._notifier.send_user(user, turn_assigned_note(game))
        await self._log_event(session, game.id, "reminded", {"source": source})
        await session.commit()
        return True

    async def pause(self, session, game_id: int) -> bool:
        game = await self.get_game(session, game_id)
        if game is None or game.status != GameStatus.running:
            return False
        game.status = GameStatus.paused
        game.paused_at = utcnow()
        await self._log_event(session, game.id, "paused", {})
        await self.refresh_dashboard(session, game)
        await session.commit()
        return True

    async def resume(self, session, game_id: int) -> bool:
        game = await self.get_game(session, game_id)
        if game is None or game.status != GameStatus.paused:
            return False
        now = utcnow()
        if game.paused_at is not None and game.turn_deadline is not None:
            game.turn_deadline += now - game.paused_at
        game.paused_at = None
        game.status = GameStatus.running
        await self._log_event(session, game.id, "resumed", {})
        await self.refresh_dashboard(session, game)
        await session.commit()
        return True

    async def cancel(self, session, game_id: int, by: str) -> bool:
        async with self._lock_for(game_id):
            game = await self.get_game(session, game_id)
            if game is None or game.status in (GameStatus.finished, GameStatus.cancelled):
                return False
            await self._cancel_game(session, game, f"отменена ({by})")
            await session.commit()
            return True

    async def _cancel_game(self, session, game: Game, reason: str) -> None:
        game.status = GameStatus.cancelled
        game.finished_at = utcnow()
        await self._log_event(session, game.id, "game_cancelled", {"reason": reason})
        text = f"❌ Игра «{game.topic}» остановлена: {reason}."
        for player in game.players:
            await self._notifier.send_user(player.user, text)
        host = await session.get(User, game.host_user_id)
        if host is not None:
            await self._notifier.send_user(host, text)
        await self.refresh_dashboard(session, game)
        self._locks.pop(game.id, None)

    async def _finish_game(self, session, game: Game) -> None:
        result = await session.execute(
            select(Chapter)
            .where(Chapter.game_id == game.id)
            .order_by(Chapter.idx)
        )
        chapters = list(result.scalars().all())
        labels = {p.user_id: fmt_user(p.user) for p in game.players}
        game.status = GameStatus.finished
        game.finished_at = utcnow()
        await self._log_event(session, game.id, "game_finished", {"chapters": len(chapters)})
        parts = compile_book(game, chapters, labels)
        chain = summaries_chain(chapters, labels)
        for player in game.players:
            for part in parts:
                await self._notifier.send_user(player.user, part)
            await self._notifier.send_user(player.user, chain)
        host = await session.get(User, game.host_user_id)
        host_ids = {
            (p.user.platform, p.user.platform_user_id) for p in game.players
        }
        if host is not None and (host.platform, host.platform_user_id) not in host_ids:
            for part in parts:
                await self._notifier.send_user(host, part)
            await self._notifier.send_user(host, chain)
        await self.refresh_dashboard(session, game)
        self._locks.pop(game.id, None)

    async def check_deadlines(self) -> None:
        maker = get_session_maker()
        async with maker() as session:
            result = await session.execute(
                select(Game.id).where(Game.status == GameStatus.running)
            )
            game_ids = [gid for (gid,) in result.all()]
        now = utcnow()
        for gid in game_ids:
            async with maker() as session:
                game = await self.get_game(session, gid)
                if game is None or game.status != GameStatus.running:
                    continue
                deadline = game.turn_deadline
                if deadline is None:
                    continue
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=utcnow().tzinfo)
                if now >= deadline:
                    await self.skip_turn(session, gid, "таймаут")
                elif not game.turn_reminded:
                    half = timedelta(hours=game.turn_timeout_hours) / 2
                    if now >= deadline - half:
                        user = self._current_user(game)
                        if user is not None:
                            await self._notifier.send_user(
                                user,
                                f"⏰ Напоминание: твой ход в игре «{game.topic}» "
                                "ждёт тебя!",
                            )
                        game.turn_reminded = True
                        await session.commit()

    async def recover_running(self) -> None:
        maker = get_session_maker()
        async with maker() as session:
            result = await session.execute(
                select(Game.id).where(Game.status == GameStatus.running)
            )
            game_ids = [gid for (gid,) in result.all()]
        for gid in game_ids:
            async with maker() as session:
                game = await self.get_game(session, gid)
                if game is None or game.current_player_id is None:
                    continue
                await self.resend_turn(session, game)
                await session.commit()
        logger.info("recovered %s running games", len(game_ids))
