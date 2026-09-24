"""Общие команды: /start, /help, /whoami, /cancel."""

from sqlalchemy import select

from bot_game_book.models import User
from bot_game_book.transport.router import Context, Router
from bot_game_book.transport.types import PlatformUser

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


async def upsert_user(session, pu: PlatformUser) -> User:
    result = await session.execute(
        select(User).where(
            User.platform == pu.platform, User.platform_user_id == pu.user_id
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            platform=pu.platform,
            platform_user_id=pu.user_id,
            username=pu.username,
            name=pu.name or pu.username or str(pu.user_id),
        )
        session.add(user)
    else:
        user.username = pu.username or user.username
        user.name = pu.name or user.name
    await session.commit()
    return user


async def get_user(session, pu: PlatformUser) -> User | None:
    result = await session.execute(
        select(User).where(
            User.platform == pu.platform, User.platform_user_id == pu.user_id
        )
    )
    return result.scalar_one_or_none()


async def cmd_start(ctx: Context) -> None:
    async with ctx.deps.session_maker() as session:
        user = await upsert_user(session, ctx.user)
    await ctx.reply(f"Привет, {user.name}! Ты в игре.\n\n{HELP_TEXT}")


async def cmd_help(ctx: Context) -> None:
    await ctx.reply(HELP_TEXT)


async def cmd_whoami(ctx: Context) -> None:
    async with ctx.deps.session_maker() as session:
        user = await get_user(session, ctx.user)
    if user is None:
        await ctx.reply("Ты ещё не зарегистрирован — нажми /start.")
        return
    admin_note = " (админ)" if user.is_admin else ""
    await ctx.reply(
        f"Имя: {user.name}{admin_note}\n"
        f"Username: {user.username or '—'}\n"
        f"Платформа: {user.platform}\n"
        f"ID: {user.id}"
    )


async def cmd_cancel(ctx: Context) -> None:
    await ctx.fsm.clear()
    await ctx.reply("Действие отменено.")


def register(router: Router) -> None:
    router.command("start", cmd_start)
    router.command("help", cmd_help)
    router.command("whoami", cmd_whoami)
    router.command("cancel", cmd_cancel)
