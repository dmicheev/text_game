"""Визард /newgame: стиль → тема → главы → слова → резюме → таймаут → участники."""

import random

from rapidfuzz import fuzz, process
from sqlalchemy import select

from bot_game_book.engine.views import fmt_user
from bot_game_book.llm.provider import LLMError
from bot_game_book.models import Game, GamePlayer, StyleCard, User
from bot_game_book.transport.router import Context, Router
from bot_game_book.transport.types import Button, Keyboard

STATE_STYLE = "newgame:style"
STATE_STYLE_CUSTOM = "newgame:style_custom"
STATE_STYLE_GEN = "newgame:style_gen"
STATE_TOPIC = "newgame:topic"
STATE_CHAPTERS = "newgame:chapters"
STATE_WORDS = "newgame:words"
STATE_SUMMARY = "newgame:summary"
STATE_TIMEOUT = "newgame:timeout"
STATE_PLAYERS = "newgame:players"
STATE_CONFIRM = "newgame:confirm"

PAGE_SIZE = 8

STYLE_PROMPT = "🎭 Шаг 1/8. Выбери писателя, в стиле которого будет написана книга:"
PLAYERS_PROMPT = "👥 Шаг 7/8. Выбери участников (минимум 2). Ты отмечен по умолчанию:"


def catalog_kb(names: list[tuple[str, str]], page: int) -> Keyboard:
    total_pages = max(1, (len(names) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = page % total_pages
    rows: Keyboard = [
        [Button(name, f"stylepick:{slug}")]
        for slug, name in names[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    ]
    nav = []
    if page > 0:
        nav.append(Button("◀️", f"cat:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(Button("▶️", f"cat:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([Button("✍️ Свой автор", "catcustom")])
    return rows


def choice_kb(field: str, options: list[int], suffix: str = "") -> Keyboard:
    rows = [
        [Button(f"{value}{suffix}", f"set:{field}:{value}")]
        for value in options[:4]
    ]
    if len(options) > 4:
        rows.append(
            [Button(f"{value}{suffix}", f"set:{field}:{value}") for value in options[4:]]
        )
    return rows


def players_kb(users: list[User], selected: set[int]) -> Keyboard:
    rows: Keyboard = []
    for user in users:
        mark = "✅ " if user.id in selected else ""
        rows.append([Button(f"{mark}{fmt_user(user)}", f"pg:{user.id}")])
    rows.append([Button("✔️ Готово", "pgdone")])
    return rows


def card_confirm_kb() -> Keyboard:
    return [
        [Button("✅ Дальше", "cardok")],
        [Button("🔄 Перегенерировать", "cardregen")],
        [Button("◀️ Назад к каталогу", "backcat")],
    ]


def card_from_catalog_kb() -> Keyboard:
    return [
        [Button("✅ Дальше", "cardok")],
        [Button("🔄 Сгенерировать свою", "catcustom")],
    ]


async def ask_style(ctx: Context) -> None:
    async with ctx.deps.session_maker() as session:
        result = await session.execute(
            select(StyleCard)
            .where(StyleCard.is_active)
            .order_by(StyleCard.sort_order, StyleCard.name_ru)
        )
        cards = result.scalars().all()
    names = [(c.slug, c.name_ru) for c in cards]
    await ctx.fsm.set_state(STATE_STYLE)
    await ctx.fsm.update_data(catalog=names)
    await ctx.reply(STYLE_PROMPT, catalog_kb(names, 0))


async def cmd_newgame(ctx: Context) -> None:
    from bot_game_book.handlers.common import upsert_user

    async with ctx.deps.session_maker() as session:
        await upsert_user(session, ctx.user)
    await ask_style(ctx)


async def cb_catalog_page(ctx: Context) -> None:
    data = await ctx.fsm.get_data()
    page = int(ctx.update.data.split(":")[1])  # type: ignore[attr-defined]
    await ctx.edit(STYLE_PROMPT, catalog_kb(data["catalog"], page))
    await ctx.answer()


def card_text_of(card: StyleCard) -> str:
    if card.is_public_domain:
        text = f"Пиши в стиле {card.name_ru}. {card.description}"
    else:
        text = card.description
    if card.excerpt:
        text += f"\n\nТВОЙ ГОЛОС — ОБРАЗЕЦ:\n{card.excerpt}"
    return text


async def _card_by_slug(session, slug: str) -> StyleCard | None:
    result = await session.execute(select(StyleCard).where(StyleCard.slug == slug))
    return result.scalar_one_or_none()


def card_text_of(card: StyleCard) -> str:
    if card.is_public_domain:
        text = f"Пиши в стиле {card.name_ru}. {card.description}"
    else:
        text = card.description
    if card.excerpt:
        text += f"\n\nТВОЙ ГОЛОС — ОБРАЗЕЦ:\n{card.excerpt}"
    return text


async def cb_style_pick(ctx: Context) -> None:
    slug = ctx.update.data.split(":")[1]  # type: ignore[attr-defined]
    async with ctx.deps.session_maker() as session:
        card = await _card_by_slug(session, slug)
    if card is None:
        await ctx.answer("Карточка не найдена", alert=True)
        return
    await ctx.fsm.update_data(
        style_label=card.name_ru,
        style_card_text=card_text_of(card),
        style_temperature=card.temperature,
    )
    await ctx.fsm.set_state(STATE_STYLE_GEN)
    await ctx.answer()
    await ctx.reply(
        f"Найдено в каталоге: «{card.name_ru}»\n\n{card_text_of(card)}",
        card_from_catalog_kb(),
    )


async def cb_custom(ctx: Context) -> None:
    await ctx.fsm.set_state(STATE_STYLE_CUSTOM)
    await ctx.answer()
    await ctx.reply("✍️ Напиши имя автора (можно любого — карточку стиля сгенерирует ИИ):")


async def proceed_to_topic(ctx: Context) -> None:
    await ctx.fsm.set_state(STATE_TOPIC)
    await ctx.reply(
        "💡 Шаг 2/8. Какова тема книги? Любая, например "
        "«космический детектив на сыродельном заводе»:"
    )


async def on_author_text(ctx: Context) -> None:
    query = ctx.message_text.strip()
    data = await ctx.fsm.get_data()
    names = dict(data["catalog"])
    match = process.extractOne(query, names, scorer=fuzz.WRatio, score_cutoff=85)
    if match is not None:
        _name, _score, slug = match
        async with ctx.deps.session_maker() as session:
            card = await _card_by_slug(session, slug)
        if card is not None:
            await ctx.fsm.update_data(
                style_label=card.name_ru,
                style_card_text=card_text_of(card),
                style_temperature=card.temperature,
            )
            await ctx.fsm.set_state(STATE_STYLE_GEN)
            await ctx.reply(
                f"Найдено в каталоге: «{card.name_ru}»\n\n{card_text_of(card)}",
                card_from_catalog_kb(),
            )
            return
    status_id = await ctx.reply("🌀 Генерирую карточку стиля...")
    try:
        card_text = await ctx.deps.generator.generate_style_card(query)
    except LLMError:
        await ctx.gateway.edit_message(
            ctx.chat_id,
            status_id or "",
            "ИИ недоступен. Попробуй ещё раз или выбери автора из каталога (/newgame).",
        )
        return
    await ctx.fsm.update_data(style_label=query, style_card_text=card_text)
    await ctx.fsm.set_state(STATE_STYLE_GEN)
    await ctx.gateway.edit_message(
        ctx.chat_id,
        status_id or "",
        f"Карточка стиля для «{query}»:\n\n{card_text}",
        card_confirm_kb(),
    )


async def cb_cardregen(ctx: Context) -> None:
    data = await ctx.fsm.get_data()
    await ctx.answer()
    try:
        card_text = await ctx.deps.generator.generate_style_card(data["style_label"])
    except LLMError:
        await ctx.reply("ИИ недоступен, попробуй ещё раз.")
        return
    await ctx.fsm.update_data(style_card_text=card_text)
    await ctx.reply(
        f"Новая карточка стиля для «{data['style_label']}»:\n\n{card_text}",
        card_confirm_kb(),
    )


async def cb_cardok(ctx: Context) -> None:
    await ctx.answer()
    await proceed_to_topic(ctx)


async def cb_backcat(ctx: Context) -> None:
    await ctx.answer()
    await ask_style(ctx)


async def on_topic(ctx: Context) -> None:
    await ctx.fsm.update_data(topic=ctx.message_text.strip())
    await ctx.fsm.set_state(STATE_CHAPTERS)
    await ctx.reply(
        "📚 Шаг 3/8. Сколько глав в книге?",
        choice_kb("chapters", [4, 6, 8, 10, 12, 16]),
    )


async def cb_chapters(ctx: Context) -> None:
    await ctx.fsm.update_data(chapters_total=int(ctx.update.data.split(":")[2]))  # type: ignore[attr-defined]
    await ctx.fsm.set_state(STATE_WORDS)
    await ctx.answer()
    await ctx.reply(
        "📝 Шаг 4/8. Сколько слов в главе (примерно)?",
        choice_kb("words", [200, 300, 500, 800]),
    )


async def cb_words(ctx: Context) -> None:
    await ctx.fsm.update_data(words_target=int(ctx.update.data.split(":")[2]))  # type: ignore[attr-defined]
    await ctx.fsm.set_state(STATE_SUMMARY)
    await ctx.answer()
    await ctx.reply(
        "🔗 Шаг 5/8. Сколько слов в резюме главы для следующего автора?",
        choice_kb("summary", [3, 5, 7]),
    )


async def cb_summary(ctx: Context) -> None:
    await ctx.fsm.update_data(summary_words=int(ctx.update.data.split(":")[2]))  # type: ignore[attr-defined]
    await ctx.fsm.set_state(STATE_TIMEOUT)
    await ctx.answer()
    await ctx.reply(
        "⏳ Шаг 6/8. Таймаут хода: сколько ждать автора, прежде чем передать ход?",
        choice_kb("timeout", [6, 12, 24, 48], suffix=" ч"),
    )


async def cb_timeout(ctx: Context) -> None:
    await ctx.fsm.update_data(turn_timeout_hours=int(ctx.update.data.split(":")[2]))  # type: ignore[attr-defined]
    async with ctx.deps.session_maker() as session:
        result = await session.execute(select(User).order_by(User.name))
        users = list(result.scalars().all())
    me = next(
        (u for u in users if u.platform == ctx.user.platform and u.platform_user_id == ctx.user.user_id),
        None,
    )
    selected = {me.id} if me is not None else set()
    await ctx.fsm.update_data(users=[u.id for u in users], selected=list(selected))
    await ctx.fsm.set_state(STATE_PLAYERS)
    await ctx.answer()
    await ctx.reply(PLAYERS_PROMPT, players_kb(users, selected))


async def _users_by_ids(ids: list[int]) -> list[User]:
    from bot_game_book.db import get_session_maker

    maker = get_session_maker()
    async with maker() as session:
        result = await session.execute(select(User).where(User.id.in_(ids)))
        by_id = {u.id: u for u in result.scalars().all()}
    return [by_id[i] for i in ids if i in by_id]


async def cb_toggle_player(ctx: Context) -> None:
    data = await ctx.fsm.get_data()
    selected = set(data["selected"])
    user_id = int(ctx.update.data.split(":")[1])  # type: ignore[attr-defined]
    if user_id in selected:
        selected.discard(user_id)
    else:
        selected.add(user_id)
    await ctx.fsm.update_data(selected=list(selected))
    users = await _users_by_ids(data["users"])
    await ctx.edit(PLAYERS_PROMPT, players_kb(users, selected))
    await ctx.answer()


async def cb_players_done(ctx: Context) -> None:
    data = await ctx.fsm.get_data()
    selected = set(data["selected"])
    if len(selected) < 2:
        await ctx.answer("Минимум 2 участника!", alert=True)
        return
    users = await _users_by_ids(list(selected))
    names = ", ".join(fmt_user(u) for u in users)
    await ctx.fsm.set_state(STATE_CONFIRM)
    await ctx.answer()
    await ctx.reply(
        "✅ Шаг 8/8. Проверь настройки:\n\n"
        f"Стиль: {data['style_label']}\n"
        f"Тема: {data['topic']}\n"
        f"Глав: {data['chapters_total']}, слов в главе: ~{data['words_target']}\n"
        f"Резюме: {data['summary_words']} слов, таймаут хода: {data['turn_timeout_hours']} ч\n"
        f"Участники: {names}",
        [
            [Button("🚀 Создать игру", "goconfirm")],
            [Button("❌ Отмена", "cancelgame")],
        ],
    )


async def cb_create_game(ctx: Context) -> None:
    from bot_game_book.handlers.common import get_user

    data = await ctx.fsm.get_data()
    async with ctx.deps.session_maker() as session:
        host = await get_user(session, ctx.user)
        if host is None:
            await ctx.answer("Сначала /start", alert=True)
            return
        game = Game(
            host_user_id=host.id,
            style_label=data["style_label"],
            style_card_text=data["style_card_text"],
            style_temperature=data.get("style_temperature"),
            topic=data["topic"],
            chapters_total=data["chapters_total"],
            words_target=data["words_target"],
            summary_words=data["summary_words"],
            turn_timeout_hours=data["turn_timeout_hours"],
            dashboard_platform=host.platform,
            dashboard_chat_id=host.platform_user_id,
        )
        session.add(game)
        await session.flush()
        order = list(data["selected"])
        random.shuffle(order)
        for position, user_id in enumerate(order):
            session.add(GamePlayer(game_id=game.id, user_id=user_id, position=position))
        await session.commit()
        game = await ctx.deps.orchestrator.get_game(session, game.id)
        if game is None:
            await ctx.answer("Не удалось создать игру", alert=True)
            return
        queue = " → ".join(fmt_user(u) for u in await _users_by_ids(order))
        await ctx.deps.orchestrator.start_game(session, game)
    await ctx.fsm.clear()
    await ctx.answer()
    await ctx.reply(
        f"🚀 Игра #{game.id} запущена!\n\nОчередь авторов: {queue}\n\n"
        "Панель управления: /admin. Дашборд игры я прислал отдельно."
    )


async def cb_cancel_game(ctx: Context) -> None:
    await ctx.fsm.clear()
    await ctx.answer()
    await ctx.reply("Создание игры отменено.")


def register(router: Router) -> None:
    router.command("newgame", cmd_newgame)
    router.callback("cat:", cb_catalog_page, state=STATE_STYLE)
    router.callback("stylepick:", cb_style_pick, state=STATE_STYLE)
    router.callback("catcustom", cb_custom, state=STATE_STYLE)
    router.message(on_author_text, state=STATE_STYLE_CUSTOM)
    router.callback("cardregen", cb_cardregen, state=STATE_STYLE_GEN)
    router.callback("cardok", cb_cardok, state=STATE_STYLE_GEN)
    router.callback("backcat", cb_backcat, state=STATE_STYLE_GEN)
    router.message(on_topic, state=STATE_TOPIC)
    router.callback("set:chapters:", cb_chapters, state=STATE_CHAPTERS)
    router.callback("set:words:", cb_words, state=STATE_WORDS)
    router.callback("set:summary:", cb_summary, state=STATE_SUMMARY)
    router.callback("set:timeout:", cb_timeout, state=STATE_TIMEOUT)
    router.callback("pg:", cb_toggle_player, state=STATE_PLAYERS)
    router.callback("pgdone", cb_players_done, state=STATE_PLAYERS)
    router.callback("goconfirm", cb_create_game, state=STATE_CONFIRM)
    router.callback("cancelgame", cb_cancel_game)
