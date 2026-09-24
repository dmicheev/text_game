# Proposal: Multi-Platform Transport

## Why

Бот привязан к Telegram: aiogram зашит в notifier, keyboards, handlers и
модель User (tg_id). Нужна поддержка мессенджера MAX и устойчивость к
добавлению новых платформ без переписывания игровой логики.

## What Changes

- Новый нейтральный транспортный слой `transport/`: типы (Button, Keyboard,
  PlatformUser, IncomingMessage/Callback), протокол BotGateway, собственный
  FSM и роутер команд/callback-ов.
- Мультиплатформенный Notifier: маршрутизация по User.platform.
- Адаптеры: `adapters/telegram_adapter.py` (aiogram), `adapters/max_adapter.py`
  (REST platform-api2.max.ru, long polling GET /updates).
- Модель: User.platform + User.platform_user_id (уникальная пара), Game
  хранит dashboard_platform/dashboard_message_id (строкой). Автоматическая
  миграция старой схемы при старте (`db_migrate.py`).
- Handlers переписаны на нейтральный роутер (`handlers/`, без aiogram).
- Конфиг: MESSENGERS, MAX_ACCESS_TOKEN; обе платформы в одном процессе.

## How

- Смешанные игры: уведомления доставляются каждому игроку по его платформе,
  в смешанных партиях игрок помечается бейджем платформы ([TG]/[MAX]).
- Telegram: единая точка aiogram (Dispatcher с двумя catch-all хендлерами)
  нормализует апдейты и передаёт их нейтральному роутеру.
- MAX: httpx-клиент (POST /messages, PUT /messages, POST /answers),
  клавиатуры → attachment inline_keyboard, long polling с marker.
- Роутер: state-bound правила приоритетнее stateless; команды проходят
  сквозь FSM-диалог (семантика /cancel).
