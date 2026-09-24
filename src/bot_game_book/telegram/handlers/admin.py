from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot_game_book.engine.orchestrator import TurnOrchestrator
from bot_game_book.engine.views import dashboard_text, utcnow
from bot_game_book.keyboards import dashboard_kb
from bot_game_book.models import Game, GameStatus
from bot_game_book.telegram.handlers.common import get_user_by_tg

router = Router()

ACTIVE_STATUSES = (GameStatus.running, GameStatus.paused)


@router.message(Command("admin"))
async def cmd_admin(message: Message, session_maker: async_sessionmaker) -> None:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    async with session_maker() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if user is None:
            await message.answer("Сначала /start.")
            return
        result = await session.execute(select(Game).where(Game.status.in_(ACTIVE_STATUSES)))
        games = list(result.scalars().all())
        if not user.is_admin:
            games = [g for g in games if g.host_user_id == user.id]
    if not games:
        await message.answer("Активных игр нет. Создай новую: /newgame")
        return
    b = InlineKeyboardBuilder()
    for game in games:
        b.button(text=f"«{game.topic}» #{game.id}", callback_data=f"admg:{game.id}")
    b.adjust(1)
    await message.answer("Панель управления. Выбери игру:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("admg:"))
async def cb_open_dashboard(
    cb: CallbackQuery,
    session_maker: async_sessionmaker,
    orchestrator: TurnOrchestrator,
) -> None:
    game_id = int(cb.data.split(":")[1])
    async with session_maker() as session:
        game = await orchestrator.get_game(session, game_id)
        if game is None:
            await cb.answer("Игра не найдена", show_alert=True)
            return
        text = dashboard_text(game, game.players, utcnow())
        game.dashboard_chat_id = cb.from_user.id
        game.dashboard_message_id = None
        await session.commit()
        await orchestrator.refresh_dashboard(session, game)
        await session.commit()
    await cb.answer()


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin_action(
    cb: CallbackQuery,
    session_maker: async_sessionmaker,
    orchestrator: TurnOrchestrator,
) -> None:
    _, game_id_str, action = cb.data.split(":")
    game_id = int(game_id_str)
    async with session_maker() as session:
        game = await orchestrator.get_game(session, game_id)
        if game is None:
            await cb.answer("Игра не найдена", show_alert=True)
            return
        user = await get_user_by_tg(session, cb.from_user.id)
        if user is None or (game.host_user_id != user.id and not user.is_admin):
            await cb.answer("Ты не ведущий этой игры", show_alert=True)
            return

    if action == "noop":
        async with session_maker() as session:
            game = await orchestrator.get_game(session, game_id)
            await orchestrator.refresh_dashboard(session, game)
            await session.commit()
        await cb.answer()
        return

    if action == "skip":
        async with session_maker() as session:
            game = await orchestrator.get_game(session, game_id)
            await orchestrator.refresh_dashboard(session, game, confirm="skip")
            await session.commit()
        await cb.answer("Подтверди передачу хода")
        return

    if action == "skipyes":
        outcome = await orchestrator.skip_turn_by_id(game_id, "ведущий передал ход")
        await cb.answer("Ход передан" if outcome == "ok" else outcome)
        return

    if action == "remind":
        async with session_maker() as session:
            done = await orchestrator.remind(session, game_id, "ведущий")
        await cb.answer("Напомнил" if done else "Не удалось")
        return

    if action == "pause":
        async with session_maker() as session:
            await orchestrator.pause(session, game_id)
        await cb.answer("Игра на паузе")
        return

    if action == "resume":
        async with session_maker() as session:
            await orchestrator.resume(session, game_id)
        await cb.answer("Игра продолжается")
        return

    if action == "cancel":
        async with session_maker() as session:
            game = await orchestrator.get_game(session, game_id)
            await orchestrator.refresh_dashboard(session, game, confirm="cancel")
            await session.commit()
        await cb.answer("Подтверди отмену")
        return

    if action == "cancelyes":
        async with session_maker() as session:
            await orchestrator.cancel(session, game_id, "ведущий отменил")
        await cb.answer("Игра отменена")
        return

    await cb.answer()
