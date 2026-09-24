import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import update

from bot_game_book.config import get_settings
from bot_game_book.db import get_session_maker, init_db
from bot_game_book.engine.orchestrator import TurnOrchestrator
from bot_game_book.llm.generation import ChapterGenerator
from bot_game_book.llm.provider import LLMProvider
from bot_game_book.models import User
from bot_game_book.notifier import Notifier
from bot_game_book.seed_loader import seed_style_cards
from bot_game_book.telegram.handlers import admin, common, setup, turn


async def amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
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

    bot = Bot(settings.bot_token, default=DefaultBotProperties())
    notifier = Notifier(bot)
    provider = LLMProvider(
        settings.llm_api_base, settings.llm_api_key, settings.llm_model
    )
    generator = ChapterGenerator(provider)
    orchestrator = TurnOrchestrator(notifier)

    dp = Dispatcher(storage=MemoryStorage())
    dp["session_maker"] = session_maker
    dp["generator"] = generator
    dp["orchestrator"] = orchestrator
    dp["notifier"] = notifier
    dp.include_routers(common.router, setup.router, turn.router, admin.router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(orchestrator.check_deadlines, "interval", seconds=60)
    scheduler.start()

    await orchestrator.recover_running()
    await bot.delete_webhook(drop_pending_updates=True)
    logging.getLogger(__name__).info("bot started (long polling)")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await provider.aclose()
        await bot.session.close()


def main() -> None:
    asyncio.run(amain())
