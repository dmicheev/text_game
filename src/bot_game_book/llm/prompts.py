"""Промпты двухстадийной генерации: проза главы + резюме."""

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
    prev_summary: str | None,
    prev_memory: str | None = None,
    twist: str | None = None,
    rewrite_note: str | None = None,
) -> list[dict]:
    is_first = prev_summary is None
    is_last = chapter_idx >= chapters_total
    if is_first:
        plot_rule = "Это первая глава: задай завязку, представь главных героев и конфликт."
    elif is_last:
        plot_rule = "Это последняя глава: заверши историю, развяжи все линии."
    else:
        plot_rule = "История будет продолжена другими авторами: не заканчивай её, оставь развитие открытым."

    system = (
        "Ты — русский прозаик, мастер слова. Ты пишешь главу "
        f"{chapter_idx} из {chapters_total} коллективного романа.\n\n"
        f"ТВОЙ ПОЧЕРК (строго соблюдай):\n{style_card_text}\n\n"
        "ТРЕБОВАНИЯ К ГЛАВЕ:\n"
        "- Это художественная проза, а не пересказ: сцены, диалоги, живые детали, "
        "динамика образа. Показывай, а не рассказывай.\n"
        f"- Объём примерно {words_target} слов (допуск ±20%).\n"
        "- Продолжай историю, опираясь ТОЛЬКО на тему и резюме предыдущей главы. "
        "Не пересказывай её и не ссылайся на то, чего в резюме нет.\n"
        f"- {plot_rule}\n"
        "- Пиши по-русски. В тексте главы ЗАПРЕЩЕНО упоминать имя писателя, "
        "а также слова «стиль», «автор», «глава», «резюме».\n\n"
        "ФОРМАТ ОТВЕТА — обычный текст, без JSON и без пояснений:\n"
        "Первая строка: «## » и название главы. Затем пустая строка и сам текст главы."
    )

    user_parts = [f"Тема книги: {topic}"]
    if is_first:
        user_parts.append("Это первая глава, резюме предыдущей нет — начни историю по теме.")
    else:
        user_parts.append(f"Резюме предыдущей главы: «{prev_summary}»")
        if prev_memory:
            user_parts.append(
                f"ПОДРОБНАЯ ПАМЯТЬ предыдущей главы (герои, имена, детали — "
                f"сохраняй преемственность): {prev_memory}"
            )
    if twist:
        user_parts.append(f"Пожелание автора главы: {twist}")
    if rewrite_note:
        user_parts.append(f"Важно: {rewrite_note}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def build_summary_messages(
    *, chapter_text: str, topic: str, summary_words: int
) -> list[dict]:
    system = (
        "Ты — литературный редактор. По написанной главе готовишь два резюме.\n"
        f"1. summary — короткое: РОВНО {summary_words} слов, главное событие "
        "и самый важный поворот. Следующий автор увидит только его.\n"
        "2. memory — развёрнутая память для продолжения: 40-60 слов, "
        "обязательно с именами и описанием главных героев, связями между ними, "
        "ключевыми деталями и открытой интригой. По memory следующий автор "
        "сможет бесшовно продолжить историю.\n"
        "Без вступлений и кавычек. Ответ строго в JSON: "
        '{"summary": "...", "memory": "..."}'
    )
    user = f"Тема книги: {topic}\n\nГлава:\n{chapter_text}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
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
