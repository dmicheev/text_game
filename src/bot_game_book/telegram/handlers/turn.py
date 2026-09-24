from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot_game_book.engine.orchestrator import TurnOrchestrator
from bot_game_book.engine.views import chapter_preview
from bot_game_book.keyboards import confirm_kb, gen_only_kb, twist_kb
from bot_game_book.llm.generation import ChapterGenerator
from bot_game_book.llm.provider import LLMError
from bot_game_book.models import Chapter, GameStatus
from bot_game_book.telegram.handlers.common import get_user_by_tg

router = Router()

MAX_REGENS = 2


class TurnFSM(StatesGroup):
    twist = State()
    busy = State()
    confirm = State()


async def _load_game(session_maker, game_id: int):
    from bot_game_book.models import Game

    async with session_maker() as session:
        result = await session.execute(select(Game).where(Game.id == game_id))
        return result.scalar_one_or_none()


async def _last_summary(session_maker, game_id: int, chapter_idx: int) -> str | None:
    async with session_maker() as session:
        result = await session.execute(
            select(Chapter.summary).where(
                Chapter.game_id == game_id, Chapter.idx == chapter_idx - 1
            )
        )
        return result.scalar_one_or_none()


@router.callback_query(F.data.startswith("turn:"))
async def cb_turn(
    cb: CallbackQuery,
    state: FSMContext,
    session_maker: async_sessionmaker,
    orchestrator: TurnOrchestrator,
) -> None:
    game_id = int(cb.data.split(":")[1])
    async with session_maker() as session:
        game = await orchestrator.get_game(session, game_id)
        if game is None or game.status != GameStatus.running:
            await cb.answer("Игра не активна", show_alert=True)
            return
        current = next(
            (p for p in game.players if p.user_id == game.current_player_id), None
        )
        if current is None or current.user.tg_id != cb.from_user.id:
            await cb.answer("Сейчас не твой ход", show_alert=True)
            return
    await state.set_state(TurnFSM.twist)
    await state.update_data(game_id=game_id, twist=None, regens=0)
    await cb.message.answer(
        "💭 Опиши одним сообщением, что должно произойти в твоей главе "
        "(пожелание для ИИ) — или нажми «Без пожелания».",
        reply_markup=twist_kb(game_id),
    )
    await cb.answer()


@router.message(TurnFSM.twist)
async def on_twist(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(twist=message.text.strip())
    await message.answer(
        "Принято! Когда будешь готов — генерируем.",
        reply_markup=gen_only_kb(data["game_id"]),
    )


@router.callback_query(TurnFSM.twist, F.data.startswith("twskip:"))
async def cb_twist_skip(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(twist=None)
    await cb.answer()
    await cb.message.answer(
        "Хорошо, ИИ сам решит, что происходит. Генерируем?",
        reply_markup=gen_only_kb(data["game_id"]),
    )


@router.callback_query(F.data.startswith("gen:"))
async def cb_generate(
    cb: CallbackQuery,
    state: FSMContext,
    session_maker: async_sessionmaker,
    orchestrator: TurnOrchestrator,
    generator: ChapterGenerator,
) -> None:
    game_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    if data.get("game_id") != game_id:
        await cb.answer("Не твоя текущая игра", show_alert=True)
        return
    async with session_maker() as session:
        game = await orchestrator.get_game(session, game_id)
        if game is None or game.status != GameStatus.running:
            await cb.answer("Игра не активна", show_alert=True)
            return
        current = next(
            (p for p in game.players if p.user_id == game.current_player_id), None
        )
        if current is None or current.user.tg_id != cb.from_user.id:
            await cb.answer("Сейчас не твой ход", show_alert=True)
            return
    await cb.answer()
    await state.set_state(TurnFSM.busy)
    status = await cb.message.answer("🌀 Пишу главу... это займёт до минуты.")
    prev_summary = await _last_summary(session_maker, game_id, game.current_chapter_idx)
    try:
        draft = await generator.generate_chapter(
            style_card_text=game.style_card_text,
            topic=game.topic,
            chapter_idx=game.current_chapter_idx,
            chapters_total=game.chapters_total,
            words_target=game.words_target,
            summary_words=game.summary_words,
            prev_summary=prev_summary,
            twist=data.get("twist"),
        )
    except LLMError:
        await state.set_state(TurnFSM.twist)
        await status.edit_text(
            "😔 ИИ недоступен. Попробуй ещё раз чуть позже.",
            reply_markup=gen_only_kb(game_id),
        )
        return
    await state.update_data(draft=draft)
    await state.set_state(TurnFSM.confirm)
    can_rewrite = data.get("regens", 0) < MAX_REGENS
    await status.delete()
    await cb.message.answer(
        chapter_preview(draft.title, draft.chapter, game.words_target),
        reply_markup=confirm_kb(game_id, can_rewrite),
    )


@router.callback_query(TurnFSM.confirm, F.data.startswith("ok:"))
async def cb_confirm(
    cb: CallbackQuery,
    state: FSMContext,
    session_maker: async_sessionmaker,
    orchestrator: TurnOrchestrator,
) -> None:
    game_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    draft = data.get("draft")
    if draft is None:
        await cb.answer("Глава потерялась, начни ход заново", show_alert=True)
        await state.clear()
        return
    async with session_maker() as session:
        user = await get_user_by_tg(session, cb.from_user.id)
        if user is None:
            await cb.answer("Сначала /start", show_alert=True)
            return
        outcome = await orchestrator.confirm_chapter(session, game_id, draft, user.id)
    if outcome == "finished":
        await cb.message.answer(
            "🏁 Это была последняя глава! Книга собирается и скоро придёт всем участникам."
        )
    elif outcome == "ok":
        await cb.message.answer("✅ Глава сохранена. Ход передан следующему автору!")
    elif outcome == "not_your_turn":
        await cb.message.answer("Ход уже не твой (например, истёк таймаут).")
    else:
        await cb.message.answer("Игра не активна.")
    await state.clear()
    await cb.answer()


@router.callback_query(TurnFSM.confirm, F.data.startswith("rw:"))
async def cb_rewrite(
    cb: CallbackQuery,
    state: FSMContext,
    session_maker: async_sessionmaker,
    orchestrator: TurnOrchestrator,
    generator: ChapterGenerator,
) -> None:
    game_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    regens = data.get("regens", 0)
    if regens >= MAX_REGENS:
        await cb.answer("Лимит перезаписей исчерпан", show_alert=True)
        return
    async with session_maker() as session:
        game = await orchestrator.get_game(session, game_id)
        if game is None or game.status != GameStatus.running:
            await cb.answer("Игра не активна", show_alert=True)
            return
    await cb.answer()
    await state.update_data(regens=regens + 1)
    status = await cb.message.answer("🌀 Пишу заново...")
    prev_summary = await _last_summary(session_maker, game_id, game.current_chapter_idx)
    try:
        draft = await generator.generate_chapter(
            style_card_text=game.style_card_text,
            topic=game.topic,
            chapter_idx=game.current_chapter_idx,
            chapters_total=game.chapters_total,
            words_target=game.words_target,
            summary_words=game.summary_words,
            prev_summary=prev_summary,
            twist=data.get("twist"),
            rewrite_note=(
                "автор просит написать эту главу полностью иначе, "
                "сохранив стиль и преемственность сюжета"
            ),
        )
    except LLMError:
        await status.edit_text("😔 ИИ недоступен, попробуй ещё раз.")
        return
    await state.update_data(draft=draft)
    can_rewrite = regens + 1 < MAX_REGENS
    await status.delete()
    await cb.message.answer(
        chapter_preview(draft.title, draft.chapter, game.words_target),
        reply_markup=confirm_kb(game_id, can_rewrite),
    )
