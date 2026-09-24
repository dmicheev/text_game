import re

WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:-[0-9A-Za-zА-Яа-яЁё]+)*")


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def words_of(text: str) -> list[str]:
    return WORD_RE.findall(text)


def trim_to_words(text: str, n: int) -> str:
    return " ".join(words_of(text)[:n])


def build_chapter_messages(
    *,
    style_card_text: str,
    topic: str,
    chapter_idx: int,
    chapters_total: int,
    words_target: int,
    summary_words: int,
    prev_summary: str | None,
    twist: str | None = None,
    rewrite_note: str | None = None,
) -> list[dict]:
    is_first = prev_summary is None
    is_last = chapter_idx >= chapters_total
    if is_first:
        plot_rule = "Это первая глава: задай завязку, представь главных героев и конфликт."
    elif is_last:
        plot_rule = "Это последняя глава: заверши историю, развязка всех линий."
    else:
        plot_rule = "История будет продолжена другими авторами: не заканчивай её, оставь развитие открытым."

    system = (
        "Ты — соавтор литературной игры «испорченный телефон». Пишешь главу "
        f"{chapter_idx} из {chapters_total} коллективной книги.\n\n"
        f"СТИЛЬ:\n{style_card_text}\n\n"
        "ПРАВИЛА:\n"
        f"- Объём главы примерно {words_target} слов (допуск ±20%).\n"
        "- Продолжай историю, опираясь ТОЛЬКО на тему и резюме предыдущей главы.\n"
        "- Не пересказывай предыдущие события и не ссылайся на то, чего нет в резюме.\n"
        f"- {plot_rule}\n"
        "- Пиши на русском языке, художественная проза.\n\n"
        "ОТВЕТ строго в JSON с ключами:\n"
        '{"title": "название главы", "chapter": "текст главы", "summary": "..."}\n'
        f'"summary" — резюме ИМЕННО твоей написанной главы, ровно {summary_words} слов: '
        "следующий автор увидит только его."
    )

    user_parts = [f"Тема книги: {topic}"]
    if is_first:
        user_parts.append("Это первая глава, резюме предыдущей нет — начни историю по теме.")
    else:
        user_parts.append(f"Резюме предыдущей главы: «{prev_summary}»")
    if twist:
        user_parts.append(f"Пожелание автора главы: {twist}")
    if rewrite_note:
        user_parts.append(f"Важно: {rewrite_note}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def build_style_card_messages(author_name: str) -> list[dict]:
    system = (
        "Ты — литературный редактор. Опиши стилевые особенности писателя 4-6 предложениями: "
        "длина фраз, лексика, тон, типичные приёмы, характерные темы, чего избегать. "
        "Пиши как инструкция для имитации стиля, обращайся к приёмам, а не к имени. "
        "Ответ строго в JSON: {\"style_card\": \"...\"}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Писатель: {author_name}"},
    ]
