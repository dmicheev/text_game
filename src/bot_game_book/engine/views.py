from datetime import datetime, timezone

from bot_game_book.models import Chapter, Game, GamePlayer, GameStatus, User

PLATFORM_LABELS = {"telegram": "TG", "max": "MAX"}


def fmt_user(user: User) -> str:
    base = f"@{user.username}" if user.username else user.name
    label = PLATFORM_LABELS.get(user.platform)
    return f"{base} [{label}]" if label else base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fmt_delta(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours >= 1:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


STATUS_ICONS = {
    GameStatus.configuring: "⚙️",
    GameStatus.running: "🟢",
    GameStatus.paused: "⏸",
    GameStatus.finished: "🏁",
    GameStatus.cancelled: "❌",
}


def turn_prompt(game: Game, prev_summary: str | None) -> str:
    lines = [
        f"📖 Твой ход! Глава {game.current_chapter_idx} из {game.chapters_total}",
        f"Книга: «{game.topic}»",
        f"Стиль: {game.style_label}",
        "",
    ]
    if prev_summary:
        lines.append(f"Резюме предыдущей главы: «{prev_summary}»")
        lines.append("(Полный текст предыдущих глав скрыт — таков смысл игры)")
    else:
        lines.append("Это первая глава — задай завязку по теме.")
    lines += [
        "",
        f"⏳ На ход даётся {game.turn_timeout_hours} ч, иначе ход перейдёт дальше.",
    ]
    return "\n".join(lines)


def turn_assigned_note(game: Game) -> str:
    return f"✍️ Жду твою главу {game.current_chapter_idx}/{game.chapters_total}. Дедлайн через {game.turn_timeout_hours} ч."


def dashboard_text(game: Game, players: list[GamePlayer], now: datetime) -> str:
    lines = [
        f"📚 «{game.topic}» — игра #{game.id}",
        f"Стиль: {game.style_label}",
        f"Статус: {STATUS_ICONS.get(game.status, '•')} {game.status.value}",
        f"Глава: {min(game.current_chapter_idx, game.chapters_total)} из {game.chapters_total}"
        f" (написано: {game.current_chapter_idx - 1})",
    ]
    current_player = next(
        (p for p in players if p.user_id == game.current_player_id), None
    )
    if current_player is not None:
        silent = ""
        if game.turn_assigned_at is not None and game.status == GameStatus.running:
            assigned = game.turn_assigned_at
            if assigned.tzinfo is None:
                assigned = assigned.replace(tzinfo=timezone.utc)
            silent = f" — молчит {fmt_delta(int((now - assigned).total_seconds()))}"
        lines.append(f"Сейчас пишет: {fmt_user(current_player.user)}{silent}")
    queue = " ".join(
        ("▶️" if p.user_id == game.current_player_id else "•") + fmt_user(p.user)
        for p in players
    )
    lines += ["", f"Очередь: {queue}"]
    if game.consecutive_skips:
        lines.append(f"Пропусков подряд: {game.consecutive_skips}")
    return "\n".join(lines)


def chapter_preview(draft_title: str, draft_body: str, words_target: int) -> str:
    return "\n".join(
        [
            "Вот твоя глава (видна только тебе):",
            "",
            f"«{draft_title}»",
            "",
            draft_body,
            "",
            f"Объём: ~{words_target} слов было заказано.",
            "✅ Оставить — глава сохранится, ход перейдёт дальше, "
            "и тебе придёт 🎨 иллюстрация к ней.",
        ]
    )


def summaries_chain(chapters: list[Chapter], label_by_author: dict[int, str]) -> str:
    lines = ["🔗 Цепочка резюме (как дрейфовал сюжет):"]
    for ch in chapters:
        lines.append(f"{ch.idx}. «{ch.summary}» — {label_by_author.get(ch.author_user_id, '?')}")
    return "\n".join(lines)
