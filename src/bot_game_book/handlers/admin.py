"""Команды ведущего: /admin и действия дашборда."""

from sqlalchemy import select

from bot_game_book.engine.views import dashboard_text, utcnow
from bot_game_book.handlers.common import get_user
from bot_game_book.models import Game, GameStatus
from bot_game_book.transport.router import Context, Router
from bot_game_book.transport.types import Button

ACTIVE_STATUSES = (GameStatus.running, GameStatus.paused)


async def cmd_admin(ctx: Context) -> None:
    async with ctx.deps.session_maker() as session:
        user = await get_user(session, ctx.user)
        if user is None:
            await ctx.reply("Сначала /start.")
            return
        result = await session.execute(select(Game).where(Game.status.in_(ACTIVE_STATUSES)))
        games = list(result.scalars().all())
        if not user.is_admin:
            games = [g for g in games if g.host_user_id == user.id]
    if not games:
        await ctx.reply("Активных игр нет. Создай новую: /newgame")
        return
    rows = [
        [Button(f"«{game.topic}» #{game.id}", f"admg:{game.id}")] for game in games
    ]
    await ctx.reply("Панель управления. Выбери игру:", rows)


async def cb_open_dashboard(ctx: Context) -> None:
    game_id = int(ctx.update.data.split(":")[1])  # type: ignore[attr-defined]
    async with ctx.deps.session_maker() as session:
        game = await ctx.deps.orchestrator.get_game(session, game_id)
        if game is None:
            await ctx.answer("Игра не найдена", alert=True)
            return
        text = dashboard_text(game, game.players, utcnow())
        _ = text
        game.dashboard_platform = ctx.user.platform
        game.dashboard_chat_id = ctx.chat_id
        game.dashboard_message_id = None
        await session.commit()
        await ctx.deps.orchestrator.refresh_dashboard(session, game)
        await session.commit()
    await ctx.answer()


async def cb_admin_action(ctx: Context) -> None:
    _, game_id_str, action = ctx.update.data.split(":")  # type: ignore[attr-defined]
    game_id = int(game_id_str)
    orchestrator = ctx.deps.orchestrator
    async with ctx.deps.session_maker() as session:
        game = await orchestrator.get_game(session, game_id)
        if game is None:
            await ctx.answer("Игра не найдена", alert=True)
            return
        user = await get_user(session, ctx.user)
        if user is None or (game.host_user_id != user.id and not user.is_admin):
            await ctx.answer("Ты не ведущий этой игры", alert=True)
            return

    if action == "noop":
        async with ctx.deps.session_maker() as session:
            game = await orchestrator.get_game(session, game_id)
            await orchestrator.refresh_dashboard(session, game)
            await session.commit()
        await ctx.answer()
        return

    if action == "skip":
        async with ctx.deps.session_maker() as session:
            game = await orchestrator.get_game(session, game_id)
            await orchestrator.refresh_dashboard(session, game, confirm="skip")
            await session.commit()
        await ctx.answer("Подтверди передачу хода")
        return

    if action == "skipyes":
        outcome = await orchestrator.skip_turn_by_id(game_id, "ведущий передал ход")
        await ctx.answer("Ход передан" if outcome == "ok" else outcome)
        return

    if action == "remind":
        async with ctx.deps.session_maker() as session:
            done = await orchestrator.remind(session, game_id, "ведущий")
        await ctx.answer("Напомнил" if done else "Не удалось")
        return

    if action == "pause":
        async with ctx.deps.session_maker() as session:
            await orchestrator.pause(session, game_id)
        await ctx.answer("Игра на паузе")
        return

    if action == "resume":
        async with ctx.deps.session_maker() as session:
            await orchestrator.resume(session, game_id)
        await ctx.answer("Игра продолжается")
        return

    if action == "cancel":
        async with ctx.deps.session_maker() as session:
            game = await orchestrator.get_game(session, game_id)
            await orchestrator.refresh_dashboard(session, game, confirm="cancel")
            await session.commit()
        await ctx.answer("Подтверди отмену")
        return

    if action == "cancelyes":
        async with ctx.deps.session_maker() as session:
            await orchestrator.cancel(session, game_id, "ведущий отменил")
        await ctx.answer("Игра отменена")
        return

    await ctx.answer()


def register(router: Router) -> None:
    router.command("admin", cmd_admin)
    router.callback("admg:", cb_open_dashboard)
    router.callback("adm:", cb_admin_action)
