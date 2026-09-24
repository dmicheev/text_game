"""Регистрация всех нейтральных хендлеров."""

from bot_game_book.transport.router import Router

from bot_game_book.handlers import admin, common, setup, turn


def register_all(router: Router) -> None:
    common.register(router)
    setup.register(router)
    turn.register(router)
    admin.register(router)
