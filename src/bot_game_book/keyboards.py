from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot_game_book.models import Game, GameStatus


def write_kb(game_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✍️ Пишу главу", callback_data=f"turn:{game_id}")
    return b.as_markup()


def twist_kb(game_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏭ Без пожелания", callback_data=f"twskip:{game_id}")
    b.button(text="✨ Сгенерировать главу", callback_data=f"gen:{game_id}")
    b.adjust(1)
    return b.as_markup()


def gen_only_kb(game_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✨ Сгенерировать главу", callback_data=f"gen:{game_id}")
    return b.as_markup()


def confirm_kb(game_id: int, can_rewrite: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Оставить", callback_data=f"ok:{game_id}")
    if can_rewrite:
        b.button(text="🔄 Переписать", callback_data=f"rw:{game_id}")
    b.adjust(2)
    return b.as_markup()


def dashboard_kb(game: Game, confirm: str | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    gid = game.id
    if confirm == "skip":
        b.button(text="⚠️ Точно передать ход?", callback_data=f"adm:{gid}:skipyes")
        b.button(text="Отмена", callback_data=f"adm:{gid}:noop")
    elif confirm == "cancel":
        b.button(text="⚠️ Точно отменить игру?", callback_data=f"adm:{gid}:cancelyes")
        b.button(text="Отмена", callback_data=f"adm:{gid}:noop")
    else:
        if game.status == GameStatus.running:
            b.button(text="🔔 Напомнить", callback_data=f"adm:{gid}:remind")
            b.button(text="⏭ Передать ход", callback_data=f"adm:{gid}:skip")
            b.button(text="⏸ Пауза", callback_data=f"adm:{gid}:pause")
            b.button(text="❌ Отменить игру", callback_data=f"adm:{gid}:cancel")
            b.adjust(2, 2)
        elif game.status == GameStatus.paused:
            b.button(text="▶️ Продолжить", callback_data=f"adm:{gid}:resume")
            b.button(text="❌ Отменить игру", callback_data=f"adm:{gid}:cancel")
            b.adjust(2)
        else:
            b.button(text="🔄 Обновить", callback_data=f"adm:{gid}:noop")
    return b.as_markup()
