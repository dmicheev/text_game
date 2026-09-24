import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import update

from bot_game_book.adapters.max_adapter import MaxClient, MaxGateway, run_max_polling
from bot_game_book.adapters.telegram_adapter import (
    TelegramGateway,
    run_telegram_polling,
)
from bot_game_book.config import get_settings
from bot_game_book.db import get_session_maker, init_db
from bot_game_book.engine.orchestrator import TurnOrchestrator
from bot_game_book.handlers.registry import register_all
from bot_game_book.llm.generation import ChapterGenerator
from bot_game_book.llm.provider import LLMProvider
from bot_game_book.models import User
from bot_game_book.notifier import Notifier
from bot_game_book.seed_loader import seed_style_cards
from bot_game_book.transport.gateway import BotGateway
from bot_game_book.transport.router import Deps, Router


async def _bootstrap_db(settings) -> None:
    await init_db()
    session_maker = get_session_maker()
    async with session_maker() as session:
        count = await seed_style_cards(session, settings.seed_path)
        admins = settings.admin_username_set
        if admins:
            await session.execute(
                update(User).where(User.username.in_(admins)).values(is_admin=True)
            )
            await session.commit()
        logging.getLogger(__name__).info("seeded %s style cards", count)


def build_router(session_maker, generator, orchestrator, notifier, settings) -> Router:
    router = Router()
    deps = Deps(
        session_maker=session_maker,
        orchestrator=orchestrator,
        generator=generator,
        notifier=notifier,
        settings=settings,
    )
    router._deps = deps  # noqa: SLF001
    register_all(router)
    return router


async def amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    await _bootstrap_db(settings)
    session_maker = get_session_maker()

    provider = LLMProvider(
        settings.llm_api_base, settings.llm_api_key, settings.llm_model
    )
    generator = ChapterGenerator(provider)
    gateways: dict[str, BotGateway] = {}
    polling_tasks: list[asyncio.Task] = []
    cleanup = []

    messengers = settings.messenger_list
    _telegram_bot: Bot | None = None
    if "telegram" in messengers:
        if settings.bot_token and settings.bot_token != "TEST:TOKEN":
            _telegram_bot = Bot(settings.bot_token, default=DefaultBotProperties())
            gateways["telegram"] = TelegramGateway(_telegram_bot)
            cleanup.append(_telegram_bot.session.close)
        else:
            logging.getLogger(__name__).warning(
                "BOT_TOKEN not set — telegram transport disabled"
            )

    if "max" in messengers:
        if settings.max_access_token:
            client = MaxClient(settings.max_access_token, settings.max_api_base)
            gateways["max"] = MaxGateway(client)
            cleanup.append(client.aclose)
        else:
            logging.getLogger(__name__).warning(
                "MAX_ACCESS_TOKEN not set — max transport disabled"
            )

    if not gateways:
        raise SystemExit("no messenger transport configured (check MESSENGERS/tokens)")

    notifier = Notifier(gateways)
    orchestrator = TurnOrchestrator(notifier)
    router = build_router(session_maker, generator, orchestrator, notifier, settings)
    deps: Deps = router._deps  # noqa: SLF001

    scheduler = AsyncIOScheduler()
    scheduler.add_job(orchestrator.check_deadlines, "interval", seconds=60)
    scheduler.start()

    await orchestrator.recover_running()

    if "telegram" in gateways:
        polling_tasks.append(
            asyncio.create_task(
                run_telegram_polling(
                    _telegram_bot, gateways["telegram"], router, deps  # type: ignore[arg-type]
                )
            )
        )
    if "max" in gateways:
        polling_tasks.append(
            asyncio.create_task(
                run_max_polling(gateways["max"], router, deps)  # type: ignore[arg-type]
            )
        )

    logging.getLogger(__name__).info(
        "bot started (platforms: %s)", ", ".join(gateways)
    )
    try:
        await asyncio.gather(*polling_tasks)
    finally:
        scheduler.shutdown(wait=False)
        for task in polling_tasks:
            task.cancel()
        await provider.aclose()
        for close in cleanup:
            try:
                await close()
            except Exception:
                pass


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
