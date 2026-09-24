"""Нейтральные клавиатуры: список рядов кнопок с callback-data."""

from bot_game_book.models import Game, GameStatus
from bot_game_book.transport.types import Button, Keyboard


def write_kb(game_id: int) -> Keyboard:
    return [[Button("✍️ Пишу главу", f"turn:{game_id}")]]


def twist_kb(game_id: int) -> Keyboard:
    return [
        [Button("⏭ Без пожелания", f"twskip:{game_id}")],
        [Button("✨ Сгенерировать главу", f"gen:{game_id}")],
    ]


def gen_only_kb(game_id: int) -> Keyboard:
    return [[Button("✨ Сгенерировать главу", f"gen:{game_id}")]]


def confirm_kb(game_id: int, can_rewrite: bool) -> Keyboard:
    row = [Button("✅ Оставить", f"ok:{game_id}")]
    if can_rewrite:
        row.append(Button("🔄 Переписать", f"rw:{game_id}"))
    return [row]


def dashboard_kb(game: Game, confirm: str | None = None) -> Keyboard:
    gid = game.id
    if confirm == "skip":
        return [
            [Button("⚠️ Точно передать ход?", f"adm:{gid}:skipyes")],
            [Button("Отмена", f"adm:{gid}:noop")],
        ]
    if confirm == "cancel":
        return [
            [Button("⚠️ Точно отменить игру?", f"adm:{gid}:cancelyes")],
            [Button("Отмена", f"adm:{gid}:noop")],
        ]
    if game.status == GameStatus.running:
        return [
            [
                Button("🔔 Напомнить", f"adm:{gid}:remind"),
                Button("⏭ Передать ход", f"adm:{gid}:skip"),
            ],
            [
                Button("⏸ Пауза", f"adm:{gid}:pause"),
                Button("❌ Отменить игру", f"adm:{gid}:cancel"),
            ],
        ]
    if game.status == GameStatus.paused:
        return [
            [
                Button("▶️ Продолжить", f"adm:{gid}:resume"),
                Button("❌ Отменить игру", f"adm:{gid}:cancel"),
            ]
        ]
    return [[Button("🔄 Обновить", f"adm:{gid}:noop")]]
