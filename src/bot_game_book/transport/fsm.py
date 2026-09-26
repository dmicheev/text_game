"""FSM-хранилище: в памяти (тесты) и в БД (переживает рестарты)."""

import asyncio
from typing import Any

from bot_game_book.transport.types import Update

StateKey = tuple[str, int]


class MemoryFSMStorage:
    def __init__(self) -> None:
        self._states: dict[StateKey, str | None] = {}
        self._data: dict[StateKey, dict[str, Any]] = {}

    def context_for(self, update: Update) -> "FSMContext":
        return FSMContext(self, (update.user.platform, update.user.user_id))

    def get_state(self, key: StateKey) -> str | None:
        return self._states.get(key)

    def set_state(self, key: StateKey, state: str | None) -> None:
        self._states[key] = state

    def get_data(self, key: StateKey) -> dict[str, Any]:
        return dict(self._data.get(key, {}))

    def update_data(self, key: StateKey, **values: Any) -> None:
        data = self._data.setdefault(key, {})
        data.update(values)

    def clear(self, key: StateKey) -> None:
        self._states.pop(key, None)
        self._data.pop(key, None)


class DbFsmStorage:
    """FSM в таблице fsm_states: диалоги выживают при рестарте процесса."""

    def __init__(self, session_maker) -> None:
        self._session_maker = session_maker

    async def _row_for(self, session, key: StateKey):
        from sqlalchemy import select

        from bot_game_book.models import FsmState

        result = await session.execute(
            select(FsmState).where(
                FsmState.platform == key[0], FsmState.user_id == key[1]
            )
        )
        return result.scalar_one_or_none()

    def context_for(self, update: Update) -> "FSMContext":
        return FSMContext(self, (update.user.platform, update.user.user_id))

    async def get_state(self, key: StateKey) -> str | None:
        async with self._session_maker() as session:
            row = await self._row_for(session, key)
            return row.state if row is not None else None

    async def set_state(self, key: StateKey, state: str | None) -> None:
        from bot_game_book.models import FsmState

        async with self._session_maker() as session:
            row = await self._row_for(session, key)
            if row is None:
                session.add(FsmState(platform=key[0], user_id=key[1], state=state))
            else:
                row.state = state
            await session.commit()

    async def get_data(self, key: StateKey) -> dict[str, Any]:
        async with self._session_maker() as session:
            row = await self._row_for(session, key)
            return dict(row.data) if row is not None and row.data else {}

    async def update_data(self, key: StateKey, **values: Any) -> None:
        from bot_game_book.models import FsmState

        async with self._session_maker() as session:
            row = await self._row_for(session, key)
            if row is None:
                session.add(
                    FsmState(platform=key[0], user_id=key[1], data=dict(values))
                )
            else:
                data = dict(row.data or {})
                data.update(values)
                row.data = data
            await session.commit()

    async def clear(self, key: StateKey) -> None:
        async with self._session_maker() as session:
            row = await self._row_for(session, key)
            if row is not None:
                await session.delete(row)
                await session.commit()


class FSMContext:
    """Контекст диалога конкретного пользователя (аналог FSMContext aiogram)."""

    def __init__(self, storage, key: StateKey) -> None:
        self._storage = storage
        self._key = key

    @property
    def state(self) -> str | None:
        return self._storage.get_state(self._key)

    async def get_state(self) -> str | None:
        state = self._storage.get_state(self._key)
        if asyncio.iscoroutine(state):
            state = await state
        return state

    async def set_state(self, state: str | None) -> None:
        result = self._storage.set_state(self._key, state)
        if asyncio.iscoroutine(result):
            await result

    async def get_data(self) -> dict[str, Any]:
        data = self._storage.get_data(self._key)
        if asyncio.iscoroutine(data):
            data = await data
        return data

    async def update_data(self, **values: Any) -> None:
        result = self._storage.update_data(self._key, **values)
        if asyncio.iscoroutine(result):
            await result

    async def clear(self) -> None:
        result = self._storage.clear(self._key)
        if asyncio.iscoroutine(result):
            await result
