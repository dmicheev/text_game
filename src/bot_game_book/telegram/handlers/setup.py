import random

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot_game_book.engine.orchestrator import TurnOrchestrator
from bot_game_book.engine.views import fmt_user
from bot_game_book.llm.generation import ChapterGenerator
from bot_game_book.llm.provider import LLMError
from bot_game_book.models import Game, GamePlayer, StyleCard, User
from bot_game_book.telegram.handlers.common import get_user_by_tg

router = Router()

PAGE_SIZE = 8


class NewGameFSM(StatesGroup):
    style = State()
    style_custom = State()
    style_gen = State()
    topic = State()
    chapters = State()
    words = State()
    summary = State()
    timeout = State()
    players = State()
    confirm = State()


def catalog_kb(names: list[tuple[str, str]], page: int) -> InlineKeyboardMarkup:
    from aiogram.types import InlineKeyboardButton

    total_pages = max(1, (len(names) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = page % total_pages
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=name, callback_data=f"stylepick:{slug}")]
        for slug, name in names[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    ]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"cat:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"cat:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton(text="✍️ Свой автор", callback_data="catcustom")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def choice_kb(field: str, options: list[int], suffix: str = "") -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    for value in options:
        b.button(text=f"{value}{suffix}", callback_data=f"set:{field}:{value}")
    b.adjust(4)
    return b.as_markup()


def players_kb(
    users: list[User], selected: set[int]
) -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    for user in users:
        mark = "✅ " if user.id in selected else ""
        b.button(text=f"{mark}{fmt_user(user)}", callback_data=f"pg:{user.id}")
    b.button(text="✔️ Готово", callback_data="pgdone")
    b.adjust(1)
    return b.as_markup()


async def ask_style(message: Message, state: FSMContext, session_maker) -> None:
    async with session_maker() as session:
        result = await session.execute(
            select(StyleCard)
            .where(StyleCard.is_active)
            .order_by(StyleCard.sort_order, StyleCard.name_ru)
        )
        cards = result.scalars().all()
    names = [(c.slug, c.name_ru) for c in cards]
    await state.set_state(NewGameFSM.style)
    await state.update_data(catalog=names)
    await message.answer(
        "🎭 Шаг 1/8. Выбери писателя, в стиле которого будет написана книга:",
        reply_markup=catalog_kb(names, 0),
    )


@router.message(Command("newgame"))
async def cmd_newgame(
    message: Message, state: FSMContext, session_maker: async_sessionmaker
) -> None:
    async with session_maker() as session:
        await get_user_by_tg(session, message.from_user.id)
    await ask_style(message, state, session_maker)


@router.callback_query(NewGameFSM.style, F.data.startswith("cat:"))
async def cb_catalog_page(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    page = int(cb.data.split(":")[1])
    await cb.message.edit_reply_markup(
        reply_markup=catalog_kb(data["catalog"], page)
    )
    await cb.answer()


@router.callback_query(NewGameFSM.style, F.data.startswith("stylepick:"))
async def cb_style_pick(
    cb: CallbackQuery, state: FSMContext, session_maker: async_sessionmaker
) -> None:
    slug = cb.data.split(":")[1]
    async with session_maker() as session:
        card = await session.get(StyleCard, slug)
    if card is None:
        await cb.answer("Карточка не найдена", show_alert=True)
        return
    card_text = (
        f"Пиши в стиле {card.name_ru}. {card.description}"
        if card.is_public_domain
        else card.description
    )
    await cb.answer()
    await show_card_and_confirm_cb(cb.message, state, card.name_ru, card_text)


@router.callback_query(NewGameFSM.style, F.data == "catcustom")
async def cb_custom(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewGameFSM.style_custom)
    await cb.message.answer(
        "✍️ Напиши имя автора (можно любого — карточку стиля сгенерирует ИИ):"
    )
    await cb.answer()


async def proceed_to_topic(message: Message, state: FSMContext) -> None:
    await state.set_state(NewGameFSM.topic)
    await message.answer(
        "💡 Шаг 2/8. Какова тема книги? Любая, например «космический детектив "
        "на сыродельном заводе»:"
    )


@router.message(NewGameFSM.style_custom)
async def on_author_text(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker,
    generator: ChapterGenerator,
) -> None:
    query = message.text.strip()
    data = await state.get_data()
    names = dict(data["catalog"])
    match = process.extractOne(query, names, scorer=fuzz.WRatio, score_cutoff=85)
    if match is not None:
        _name, score, slug = match
        async with session_maker() as session:
            card = await session.get(StyleCard, slug)
        if card is not None:
            card_text = (
                f"Пиши в стиле {card.name_ru}. {card.description}"
                if card.is_public_domain
                else card.description
            )
            await show_card_and_confirm_cb(message, state, card.name_ru, card_text)
            return
    generating = await message.answer("🌀 Генерирую карточку стиля...")
    try:
        card_text = await generator.generate_style_card(query)
    except LLMError:
        await generating.edit_text(
            "ИИ недоступен. Попробуй ещё раз или выбери автора из каталога (/newgame)."
        )
        return
    await state.update_data(style_label=query, style_card_text=card_text)
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    b.button(text="✅ Дальше", callback_data="cardok")
    b.button(text="🔄 Перегенерировать", callback_data="cardregen")
    b.button(text="◀️ Назад к каталогу", callback_data="backcat")
    b.adjust(1)
    await state.set_state(NewGameFSM.style_gen)
    await generating.edit_text(
        f"Карточка стиля для «{query}»:\n\n{card_text}", reply_markup=b.as_markup()
    )


async def show_card_and_confirm_cb(
    message: Message, state: FSMContext, label: str, card_text: str
) -> None:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    await state.update_data(style_label=label, style_card_text=card_text)
    b = InlineKeyboardBuilder()
    b.button(text="✅ Дальше", callback_data="cardok")
    b.button(text="🔄 Сгенерировать свою", callback_data="catcustom")
    b.adjust(1)
    await state.set_state(NewGameFSM.style_gen)
    await message.answer(
        f"Найдено в каталоге: «{label}»\n\n{card_text}", reply_markup=b.as_markup()
    )


@router.callback_query(NewGameFSM.style_gen, F.data == "cardregen")
async def cb_cardregen(
    cb: CallbackQuery,
    state: FSMContext,
    generator: ChapterGenerator,
) -> None:
    data = await state.get_data()
    await cb.answer()
    try:
        card_text = await generator.generate_style_card(data["style_label"])
    except LLMError:
        await cb.message.answer("ИИ недоступен, попробуй ещё раз.")
        return
    await state.update_data(style_card_text=card_text)
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    b.button(text="✅ Дальше", callback_data="cardok")
    b.button(text="🔄 Перегенерировать", callback_data="cardregen")
    b.button(text="◀️ Назад к каталогу", callback_data="backcat")
    b.adjust(1)
    await cb.message.answer(
        f"Новая карточка стиля для «{data['style_label']}»:\n\n{card_text}",
        reply_markup=b.as_markup(),
    )


@router.callback_query(NewGameFSM.style_gen, F.data == "cardok")
async def cb_cardok(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await proceed_to_topic(cb.message, state)


@router.callback_query(NewGameFSM.style_gen, F.data == "backcat")
async def cb_backcat(cb: CallbackQuery, state: FSMContext, session_maker) -> None:
    await cb.answer()
    await ask_style(cb.message, state, session_maker)


@router.message(NewGameFSM.topic)
async def on_topic(message: Message, state: FSMContext) -> None:
    await state.update_data(topic=message.text.strip())
    await state.set_state(NewGameFSM.chapters)
    await message.answer(
        "📚 Шаг 3/8. Сколько глав в книге?",
        reply_markup=choice_kb("chapters", [4, 6, 8, 10, 12, 16]),
    )


@router.callback_query(NewGameFSM.chapters, F.data.startswith("set:chapters:"))
async def cb_chapters(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(chapters_total=int(cb.data.split(":")[2]))
    await state.set_state(NewGameFSM.words)
    await cb.answer()
    await cb.message.answer(
        "📝 Шаг 4/8. Сколько слов в главе (примерно)?",
        reply_markup=choice_kb("words", [200, 300, 500, 800]),
    )


@router.callback_query(NewGameFSM.words, F.data.startswith("set:words:"))
async def cb_words(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(words_target=int(cb.data.split(":")[2]))
    await state.set_state(NewGameFSM.summary)
    await cb.answer()
    await cb.message.answer(
        "🔗 Шаг 5/8. Сколько слов в резюме главы для следующего автора?",
        reply_markup=choice_kb("summary", [3, 5, 7]),
    )


@router.callback_query(NewGameFSM.summary, F.data.startswith("set:summary:"))
async def cb_summary(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(summary_words=int(cb.data.split(":")[2]))
    await state.set_state(NewGameFSM.timeout)
    await cb.answer()
    await cb.message.answer(
        "⏳ Шаг 6/8. Таймаут хода: сколько ждать автора, прежде чем передать ход?",
        reply_markup=choice_kb("timeout", [6, 12, 24, 48], suffix=" ч"),
    )


@router.callback_query(NewGameFSM.timeout, F.data.startswith("set:timeout:"))
async def cb_timeout(
    cb: CallbackQuery, state: FSMContext, session_maker: async_sessionmaker
) -> None:
    await state.update_data(turn_timeout_hours=int(cb.data.split(":")[2]))
    async with session_maker() as session:
        result = await session.execute(select(User).order_by(User.name))
        users = list(result.scalars().all())
    me = next((u for u in users if u.tg_id == cb.from_user.id), None)
    if me is not None:
        selected = {me.id}
    else:
        selected = set()
    await state.update_data(users=[u.id for u in users], selected=list(selected))
    await state.set_state(NewGameFSM.players)
    await cb.answer()
    await cb.message.answer(
        "👥 Шаг 7/8. Выбери участников (минимум 2). Ты отмечен по умолчанию:",
        reply_markup=players_kb(users, selected),
    )


@router.callback_query(NewGameFSM.players, F.data.startswith("pg:"))
async def cb_toggle_player(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = set(data["selected"])
    user_id = int(cb.data.split(":")[1])
    if user_id in selected:
        selected.discard(user_id)
    else:
        selected.add(user_id)
    await state.update_data(selected=list(selected))
    users = await _users_by_ids(data["users"])
    await cb.message.edit_reply_markup(reply_markup=players_kb(users, selected))
    await cb.answer()


@router.callback_query(NewGameFSM.players, F.data == "pgdone")
async def cb_players_done(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = set(data["selected"])
    if len(selected) < 2:
        await cb.answer("Минимум 2 участника!", show_alert=True)
        return
    users = await _users_by_ids(list(selected))
    names = ", ".join(fmt_user(u) for u in users)
    await state.set_state(NewGameFSM.confirm)
    await cb.answer()
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    b.button(text="🚀 Создать игру", callback_data="goconfirm")
    b.button(text="❌ Отмена", callback_data="cancelgame")
    b.adjust(1)
    await cb.message.answer(
        "✅ Шаг 8/8. Проверь настройки:\n\n"
        f"Стиль: {data['style_label']}\n"
        f"Тема: {data['topic']}\n"
        f"Глав: {data['chapters_total']}, слов в главе: ~{data['words_target']}\n"
        f"Резюме: {data['summary_words']} слов, таймаут хода: {data['turn_timeout_hours']} ч\n"
        f"Участники: {names}",
        reply_markup=b.as_markup(),
    )


async def _users_by_ids(ids: list[int]) -> list[User]:
    from bot_game_book.db import get_session_maker

    maker = get_session_maker()
    async with maker() as session:
        result = await session.execute(select(User).where(User.id.in_(ids)))
        by_id = {u.id: u for u in result.scalars().all()}
    return [by_id[i] for i in ids if i in by_id]


@router.callback_query(NewGameFSM.confirm, F.data == "goconfirm")
async def cb_create_game(
    cb: CallbackQuery,
    state: FSMContext,
    session_maker: async_sessionmaker,
    orchestrator: TurnOrchestrator,
) -> None:
    data = await state.get_data()
    async with session_maker() as session:
        host = await get_user_by_tg(session, cb.from_user.id)
        if host is None:
            await cb.answer("Сначала /start", show_alert=True)
            return
        game = Game(
            host_user_id=host.id,
            style_label=data["style_label"],
            style_card_text=data["style_card_text"],
            topic=data["topic"],
            chapters_total=data["chapters_total"],
            words_target=data["words_target"],
            summary_words=data["summary_words"],
            turn_timeout_hours=data["turn_timeout_hours"],
            dashboard_chat_id=host.tg_id,
        )
        session.add(game)
        await session.flush()
        order = list(data["selected"])
        random.shuffle(order)
        for position, user_id in enumerate(order):
            session.add(
                GamePlayer(game_id=game.id, user_id=user_id, position=position)
            )
        await session.commit()
        queue = " → ".join(
            fmt_user(u) for u in await _users_by_ids(order)
        )
        await orchestrator.start_game(session, game)
    await state.clear()
    await cb.answer()
    await cb.message.answer(
        f"🚀 Игра #{game.id} запущена!\n\nОчередь авторов: {queue}\n\n"
        "Панель управления: /admin. Дашборд игры я прислал отдельно."
    )


@router.callback_query(F.data == "cancelgame")
async def cb_cancel_game(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await cb.message.answer("Создание игры отменено.")
