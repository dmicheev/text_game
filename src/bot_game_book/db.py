from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot_game_book.config import get_settings
from bot_game_book.models import Base

_engine = None
_session_maker: async_sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, echo=False)
    return _engine


def get_session_maker() -> async_sessionmaker:
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_maker


async def init_db() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
