"""Платформонезависимое FSM-хранилище (в памяти процесса)."""

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


class FSMContext:
    """Контекст диалога конкретного пользователя (аналог FSMContext aiogram)."""

    def __init__(self, storage: MemoryFSMStorage, key: StateKey) -> None:
        self._storage = storage
        self._key = key

    @property
    def state(self) -> str | None:
        return self._storage.get_state(self._key)

    async def get_state(self) -> str | None:
        return self._storage.get_state(self._key)

    async def set_state(self, state: str | None) -> None:
        self._storage.set_state(self._key, state)

    async def get_data(self) -> dict[str, Any]:
        return self._storage.get_data(self._key)

    async def update_data(self, **values: Any) -> None:
        self._storage.update_data(self._key, **values)

    async def clear(self) -> None:
        self._storage.clear(self._key)
