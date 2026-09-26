"""Общие команды: /start, /help, /whoami, /cancel."""

from sqlalchemy import select

from bot_game_book.models import User
from bot_game_book.transport.router import Context, Router
from bot_game_book.transport.types import PlatformUser

HELP_TEXT = (
    "📖 «Письмо из Простоквашино»\n\n"
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
    await ctx.reply(
        "Действие отменено. Игры не тронуты — остановить игру можно только "
        "через /admin → «❌ Отменить игру»."
    )


async def fallback_message(ctx: Context) -> None:
    """Ответ на текст, не попавший ни в один хендлер: подсказываем, что делать."""
    from sqlalchemy import select

    from bot_game_book.models import Game, GameStatus

    async with ctx.deps.session_maker() as session:
        user = await get_user(session, ctx.user)
        if user is None:
            await ctx.reply("Нажми /start, чтобы зарегистрироваться в игре.")
            return
        result = await session.execute(
            select(Game).where(
                Game.current_player_id == user.id,
                Game.status == GameStatus.running,
            )
        )
        game = result.scalars().first()
    if game is not None:
        await ctx.reply(
            f"Сейчас твой ход в игре «{game.topic}» (глава "
            f"{game.current_chapter_idx} из {game.chapters_total}). "
            "Нажми кнопку «✍️ Пишу главу» в сообщении, которое я присылал "
            "при передаче хода."
        )
    else:
        await ctx.reply(
            "Не понял сообщение. " + HELP_TEXT
        )


def register(router: Router) -> None:
    router.command("start", cmd_start)
    router.command("help", cmd_help)
    router.command("whoami", cmd_whoami)
    router.command("cancel", cmd_cancel)
    router.message(fallback_message)
