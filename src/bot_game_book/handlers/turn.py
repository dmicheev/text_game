"""Цикл хода: кнопка «Пишу главу», twist, генерация, подтверждение."""

from sqlalchemy import select

from bot_game_book.engine.views import chapter_preview
from bot_game_book.handlers.common import get_user
from bot_game_book.keyboards import confirm_kb, gen_only_kb, twist_kb
from bot_game_book.llm.provider import LLMError
from bot_game_book.llm.validator import ChapterDraft
from bot_game_book.models import Chapter, GameStatus
from bot_game_book.transport.router import Context, Router

STATE_TWIST = "turn:twist"
STATE_BUSY = "turn:busy"
STATE_CONFIRM = "turn:confirm"

MAX_REGENS = 2


def _writing_status_text(ctx: Context) -> str:
    variants = 1
    settings = ctx.deps.settings
    if settings is not None:
        variants = getattr(settings, "chapter_variants", 1) or 1
    if variants > 1:
        return (
            "🌀 Пишу главу: несколько вариантов, критика и шлифовка — "
            "это может занять 5–10 минут. Наберись терпения."
        )
    return "🌀 Пишу главу... это займёт до пары минут."


async def _load_game(ctx: Context, game_id: int):
    async with ctx.deps.session_maker() as session:
        game = await ctx.deps.orchestrator.get_game(session, game_id)
        return game


async def _last_summary(
    ctx: Context, game_id: int, chapter_idx: int
) -> tuple[str | None, str | None]:
    """(короткое резюме, развёрнутая память) предыдущей главы."""
    async with ctx.deps.session_maker() as session:
        result = await session.execute(
            select(Chapter.summary, Chapter.memory).where(
                Chapter.game_id == game_id, Chapter.idx == chapter_idx - 1
            )
        )
        row = result.first()
        return (row[0], row[1]) if row else (None, None)


def _is_current_player(game, ctx: Context) -> bool:
    current = next(
        (p for p in game.players if p.user_id == game.current_player_id), None
    )
    if current is None:
        return False
    user = current.user
    return user.platform == ctx.user.platform and user.platform_user_id == ctx.user.user_id


async def cb_turn(ctx: Context) -> None:
    game_id = int(ctx.update.data.split(":")[1])  # type: ignore[attr-defined]
    async with ctx.deps.session_maker() as session:
        game = await ctx.deps.orchestrator.get_game(session, game_id)
        if game is None or game.status != GameStatus.running:
            await ctx.answer("Игра не активна", alert=True)
            return
        if not _is_current_player(game, ctx):
            await ctx.answer("Сейчас не твой ход", alert=True)
            return
    await ctx.fsm.set_state(STATE_TWIST)
    await ctx.fsm.update_data(game_id=game_id, twist=None, regens=0)
    await ctx.answer()
    await ctx.reply(
        "💭 Опиши одним сообщением, что должно произойти в твоей главе "
        "(пожелание для ИИ) — или нажми «Без пожелания».",
        twist_kb(game_id),
    )


async def on_twist(ctx: Context) -> None:
    data = await ctx.fsm.get_data()
    await ctx.fsm.update_data(twist=ctx.message_text.strip())
    await _generate_flow(ctx, data["game_id"])


async def cb_twist_skip(ctx: Context) -> None:
    data = await ctx.fsm.get_data()
    await ctx.fsm.update_data(twist=None)
    await ctx.answer()
    await _generate_flow(ctx, data["game_id"])


async def _generate_flow(ctx: Context, game_id: int) -> None:
    data = await ctx.fsm.get_data()
    game = await _load_game(ctx, game_id)
    if game is None or game.status != GameStatus.running:
        await ctx.reply("Игра не активна.")
        return
    if not _is_current_player(game, ctx):
        await ctx.reply("Сейчас не твой ход.")
        return
    await ctx.fsm.set_state(STATE_BUSY)
    status_id = await ctx.reply(_writing_status_text(ctx))

    async def _on_stage(text: str) -> None:
        if status_id:
            await ctx.gateway.edit_message(ctx.chat_id, status_id, text)

    prev_summary, prev_memory = await _last_summary(ctx, game_id, game.current_chapter_idx)
    try:
        draft = await ctx.deps.generator.generate_chapter(
            style_card_text=game.style_card_text,
            topic=game.topic,
            chapter_idx=game.current_chapter_idx,
            chapters_total=game.chapters_total,
            words_target=game.words_target,
            summary_words=game.summary_words,
            prev_summary=prev_summary,
            prev_memory=prev_memory,
            twist=data.get("twist"),
            temperature=game.style_temperature,
            style_label=game.style_label,
            on_stage=_on_stage,
        )
    except LLMError:
        await ctx.fsm.set_state(STATE_TWIST)
        await ctx.gateway.edit_message(
            ctx.chat_id,
            status_id or "",
            "😔 ИИ недоступен. Попробуй ещё раз чуть позже.",
            gen_only_kb(game_id),
        )
        return
    await ctx.fsm.update_data(
        draft={
            "title": draft.title,
            "chapter": draft.chapter,
            "summary": draft.summary,
            "memory": draft.memory,
        }
    )
    await ctx.fsm.set_state(STATE_CONFIRM)
    can_rewrite = data.get("regens", 0) < MAX_REGENS
    if status_id:
        await ctx.gateway.delete_message(ctx.chat_id, status_id)
    await ctx.reply(
        chapter_preview(draft.title, draft.chapter, game.words_target),
        confirm_kb(game_id, can_rewrite),
    )


async def cb_generate(ctx: Context) -> None:
    game_id = int(ctx.update.data.split(":")[1])  # type: ignore[attr-defined]
    data = await ctx.fsm.get_data()
    if data.get("game_id") != game_id:
        await ctx.answer("Не твоя текущая игра", alert=True)
        return
    await ctx.answer()
    await _generate_flow(ctx, game_id)


async def cb_confirm(ctx: Context) -> None:
    game_id = int(ctx.update.data.split(":")[1])  # type: ignore[attr-defined]
    data = await ctx.fsm.get_data()
    raw_draft = data.get("draft")
    draft = ChapterDraft(**raw_draft) if isinstance(raw_draft, dict) else raw_draft
    if draft is None:
        await ctx.answer("Глава потерялась, начни ход заново", alert=True)
        await ctx.fsm.clear()
        return
    async with ctx.deps.session_maker() as session:
        user = await get_user(session, ctx.user)
        if user is None:
            await ctx.answer("Сначала /start", alert=True)
            return
        outcome = await ctx.deps.orchestrator.confirm_chapter(
            session, game_id, draft, user.id
        )
    if outcome == "finished":
        await ctx.reply(
            "🏁 Это была последняя глава! Книга собирается и скоро придёт всем участникам."
        )
    elif outcome == "ok":
        await ctx.reply("✅ Глава сохранена. Ход передан следующему автору!")
    elif outcome == "not_your_turn":
        await ctx.reply("Ход уже не твой (например, истёк таймаут).")
    else:
        await ctx.reply("Игра не активна.")
    await ctx.fsm.clear()
    await ctx.answer()


async def cb_rewrite(ctx: Context) -> None:
    game_id = int(ctx.update.data.split(":")[1])  # type: ignore[attr-defined]
    data = await ctx.fsm.get_data()
    regens = data.get("regens", 0)
    if regens >= MAX_REGENS:
        await ctx.answer("Лимит перезаписей исчерпан", alert=True)
        return
    game = await _load_game(ctx, game_id)
    if game is None or game.status != GameStatus.running:
        await ctx.answer("Игра не активна", alert=True)
        return
    await ctx.answer()
    await ctx.fsm.update_data(regens=regens + 1)
    status_id = await ctx.reply(_writing_status_text(ctx))

    async def _on_stage(text: str) -> None:
        if status_id:
            await ctx.gateway.edit_message(ctx.chat_id, status_id, text)

    prev_summary, prev_memory = await _last_summary(ctx, game_id, game.current_chapter_idx)
    try:
        draft = await ctx.deps.generator.generate_chapter(
            style_card_text=game.style_card_text,
            topic=game.topic,
            chapter_idx=game.current_chapter_idx,
            chapters_total=game.chapters_total,
            words_target=game.words_target,
            summary_words=game.summary_words,
            prev_summary=prev_summary,
            prev_memory=prev_memory,
            twist=data.get("twist"),
            rewrite_note=(
                "автор просит написать эту главу полностью иначе, "
                "сохранив стиль и преемственность сюжета"
            ),
            temperature=game.style_temperature,
            style_label=game.style_label,
            on_stage=_on_stage,
        )
    except LLMError:
        await ctx.gateway.edit_message(ctx.chat_id, status_id or "", "😔 ИИ недоступен, попробуй ещё раз.")
        return
    await ctx.fsm.update_data(
        draft={
            "title": draft.title,
            "chapter": draft.chapter,
            "summary": draft.summary,
            "memory": draft.memory,
        }
    )
    can_rewrite = regens + 1 < MAX_REGENS
    if status_id:
        await ctx.gateway.delete_message(ctx.chat_id, status_id)
    await ctx.reply(
        chapter_preview(draft.title, draft.chapter, game.words_target),
        confirm_kb(game_id, can_rewrite),
    )


def register(router: Router) -> None:
    router.callback("turn:", cb_turn)
    router.message(on_twist, state=STATE_TWIST)
    router.callback("twskip:", cb_twist_skip, state=STATE_TWIST)
    router.callback("gen:", cb_generate)
    router.callback("ok:", cb_confirm, state=STATE_CONFIRM)
    router.callback("rw:", cb_rewrite, state=STATE_CONFIRM)
