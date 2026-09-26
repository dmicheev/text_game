# Project Context

## Overview

Многопользовательская игра «Письмо из Простоквашино» (механика «испорченный
телефон») — мессенджер-бот (Telegram + MAX).
Игроки по очереди «пишут» главы книги с помощью LLM. Каждый следующий автор видит
только короткое резюме (N слов) предыдущей главы — дрейф сюжета является
смыслом игры. Полный текст книги скрыт от всех до финала.

## Tech Stack

- Python 3.12+, aiogram 3 (long polling), APScheduler
- SQLAlchemy 2 (async, asyncpg) + PostgreSQL 17 (Docker)
- LLM: OpenAI-совместимый API через httpx (провайдер сменяемый через конфиг)
- uv (менеджмент зависимостей), pytest
- Seed данных: YAML → идемпотентный upsert при старте

## Conventions

- Состояние игры ТОЛЬКО в БД (переживает рестарты), никаких состояний в памяти
  кроме FSM диалогов aiogram (MemoryStorage)
- Машина состояний: LOBBY/CONFIGURING → RUNNING → PAUSED → FINISHED/CANCELLED;
  ход: AWAIT_PLAYER → AWAIT_LLM → AWAIT_CONFIRM
- Пропуск хода — единый код-путь `TurnOrchestrator.skip_turn()` для таймаута
  и ручного пропуска админом
- Полный текст глав никому не отправляется до финала (кроме автора своей главы)
- Код без комментариев, аннотации типов, async/await везде
- callback_data компактный (≤64 байта): `prefix:game_id:action`

## Architecture

```
presentation/telegram  хендлеры, FSM-визард, inline-клавиатуры, admin-дашборд
core/engine            TurnOrchestrator, BookCompiler, машина состояний
llm                    провайдер-адаптер, промпт-шаблоны, валидатор ответа
scheduler              напоминания и таймауты ходов (APScheduler)
notifier               отправка сообщений, редактирование дашборда
db                     модели SQLAlchemy, seed-загрузчик
```

## Development Workflow

- Тестирование: запуск вручную на рабочем Mac (`uv run bot`), Postgres в Docker
- Prod (позже): VPS + тот же docker compose
- OpenSpec: изменения через proposals, спеки — источник правды
