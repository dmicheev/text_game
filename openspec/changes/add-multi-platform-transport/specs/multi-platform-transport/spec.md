# Multi-Platform-Transport Specification

## Purpose

Универсальная транспортная архитектура: ядро игры (engine, llm, модели)
платформонезависимо; доставка сообщений и приём апдейтов — через адаптеры.
Поддерживаются Telegram (aiogram, long polling) и MAX (REST API
platform-api2.max.ru, long polling GET /updates). Смешанные игры: в одной
партии могут участвовать игроки из разных мессенджеров.

## Requirements

### Requirement: Нейтральный транспортный слой

**User Story:** Как разработчик, я хочу ядро игры без зависимости от
конкретного мессенджера, чтобы добавлять платформы без переписывания логики.

#### Acceptance Criteria

1. Система SHALL определять нейтральные типы: `Button(text, data)`,
   `Keyboard` (список рядов), `PlatformUser`, `IncomingMessage`,
   `IncomingCallback`
2. Каждый мессенджер SHALL реализовывать протокол `BotGateway`:
   `send_message`, `edit_message`, `delete_message`, `answer_callback`
3. Исходящие сообщения SHALL адресоваться парой (platform, chat_id);
   идентификаторы сообщений SHALL храниться как строки
4. Входящие апдейты обеих платформ SHALL нормализоваться к нейтральным
   типам до попадания в роутер
5. Универсальный роутер SHALL поддерживать: команды (`/cmd`), callback-и по
   префиксу, текстовые сообщения; с опциональной привязкой к FSM-состоянию
   (state-bound приоритетнее stateless)
6. FSM-хранилище SHALL быть платформонезависимым, с ключом
   (platform, user_id)

### Requirement: Смешанные игры

**User Story:** Как ведущий, я хочу собирать партию из игроков разных
мессенджеров в одной игре.

#### Acceptance Criteria

1. Модель User SHALL хранить `platform` + `platform_user_id` с уникальной
   парой вместо `tg_id`
2. Уведомления участникам SHALL доставляться по платформе каждого игрока
3. Дашборд ведущего SHALL хранить (platform, chat_id, message_id)
4. Отображение игрока (fmt_user) SHALL показывать платформу для различения
   участников смешанных игр
5. Существующие данные SHALL переноситься автоматической миграцией при
   старте (users.tg_id → platform='telegram', platform_user_id)

### Requirement: Адаптер MAX

**User Story:** Как игрок в MAX, я хочу играть в те же игры, что и
пользователи Telegram.

#### Acceptance Criteria

1. Адаптер SHALL работать с base URL `https://platform-api2.max.ru` и
   токеном `Authorization: <access_token>`
2. Получение апдейтов SHALL осуществляться long polling `GET /updates`
   (types=message_created,message_callback, marker)
3. Отправка: `POST /messages`; редактирование: `PUT /messages`; ответ на
   callback: `POST /answers`
4. Клавиатуры SHALL конвертироваться в attachment
   `inline_keyboard.payload.buttons` с кнопками типа `callback`
5. Ошибки доставки (HTTP 4xx/5xx, таймауты) SHALL логироваться и не ронять
   polling-цикл

### Requirement: Конфигурация и запуск

#### Acceptance Criteria

1. Список платформ SHALL задаваться конфигом `MESSENGERS`
   (запятая-separated: `telegram,max`); по умолчанию — `telegram`
2. Оба активных бота SHALL работать в одном процессе (параллельные
   polling-задачи)
3. Платформа без токена SHALL пропускаться с предупреждением в лог
4. `.env` SHALL содержать: `BOT_TOKEN` (Telegram), `MAX_ACCESS_TOKEN`,
   `MESSENGERS`
