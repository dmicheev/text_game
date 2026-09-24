# Tasks

- [x] 1. Транспортный слой: нейтральные типы, протокол BotGateway, FSM, роутер
- [x] 2. Модели: User.platform + platform_user_id, Game.dashboard_platform; миграция БД
- [x] 3. Нейтральные keyboards + мультиплатформенный Notifier
- [x] 4. Адаптер Telegram (aiogram → BotGateway + polling)
- [x] 5. Адаптер MAX (REST-клиент + long polling + конвертация клавиатур/апдейтов)
- [x] 6. Handlers: переписать common/setup/turn/admin на нейтральный роутер
- [x] 7. main.py: сборка платформ по конфигу, параллельный запуск
- [x] 8. Тесты: транспорт, роутер/FSM, нотификатор, MAX-адаптер
- [x] 9. README и .env.example
