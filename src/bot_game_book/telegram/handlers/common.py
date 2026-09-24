from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot_game_book.models import User

router = Router()

HELP_TEXT = (
    "📖 «Книга в стиле испорченный телефон»\n\n"
    "Игроки по очереди пишут главы книги с помощью ИИ. Каждый следующий автор "
    "видит только короткое резюме предыдущей главы — сюжет дрейфует, в этом и соль.\n\n"
    "Команды:\n"
    "/newgame — настроить новую игру (для ведущего)\n"
    "/admin — панель управления играми\n"
    "/whoami — мой профиль\n"
    "/cancel — отменить текущее действие"
)


async def upsert_user(session, tg_user) -> User:
    result = await session.execute(select(User).where(User.tg_id == tg_user.id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            tg_id=tg_user.id,
            username=tg_user.username,
            name=tg_user.first_name or tg_user.username or str(tg_user.id),
        )
        session.add(user)
    else:
        user.username = tg_user.username or user.username
        user.name = tg_user.first_name or user.name
    await session.commit()
    return user


async def get_user_by_tg(session, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


@router.message(CommandStart())
async def cmd_start(message: Message, session_maker: async_sessionmaker) -> None:
    async with session_maker() as session:
        user = await upsert_user(session, message.from_user)
    await message.answer(
        f"Привет, {user.name}! Ты в игре.\n\n{HELP_TEXT}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message, session_maker: async_sessionmaker) -> None:
    async with session_maker() as session:
        user = await get_user_by_tg(session, message.from_user.id)
    if user is None:
        await message.answer("Ты ещё не зарегистрирован — нажми /start.")
        return
    admin_note = " (админ)" if user.is_admin else ""
    await message.answer(
        f"Имя: {user.name}{admin_note}\n"
        f"Username: {user.username or '—'}\n"
        f"ID: {user.id}"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.")
