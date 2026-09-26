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
    scene_plan: str | None = None,
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
        "- ГЛАВНОЕ — никакого шаблонного текста: запретные штампы перечислены в "
        "плане, обходи их. Конкретика вместо оценок: не «тревожная атмосфера», "
        "а какая именно деталь её создаёт. Сравнения — неожиданные, из мира "
        "героев. Никакой морали в конце.\n"
        "- Каждое предложение должно проходить проверку смыслом: подлежащее "
        "способно выполнить действие сказуемого. Никаких абсурдных связок "
        "вида «вагон запил», «шкаф задумался и ушёл» — олицетворение только "
        "если образ мгновенно читается.\n"
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
    if scene_plan:
        user_parts.append(f"ПЛАН СЦЕНЫ (пиши строго по нему):\n{scene_plan}")
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


def build_scene_plan_messages(
    *,
    style_label: str,
    topic: str,
    chapter_idx: int,
    chapters_total: int,
    prev_summary: str | None,
    prev_memory: str | None,
    twist: str | None,
) -> list[dict]:
    """Стадия 1 (дешёвая): план сцены с нестандартными ходами против штампов."""
    is_first = prev_summary is None
    is_last = chapter_idx >= chapters_total
    if is_first:
        plot_rule = "первая глава: завязка, герои, конфликт"
    elif is_last:
        plot_rule = "последняя глава: развязка всех линий"
    else:
        plot_rule = "середина: не заканчивай историю, оставь развитие открытым"

    system = (
        "Ты — сценарист и литературный редактор. Составь план главы книги "
        "(не саму главу!) так, чтобы текст получился НЕшаблонным.\n"
        f"Книга: «{topic}», стиль автора: {style_label}, глава "
        f"{chapter_idx} из {chapters_total} ({plot_rule}).\n\n"
        "Требования к плану:\n"
        "- fresh_details: ровно 3 неожиданные КОНКРЕТНЫЕ детали (предметы, запахи, "
        "привычки, звук), которых не ожидаешь в такой сцене — не «треск свечи», "
        "а что-то в духе мира книги\n"
        "- cliches_to_avoid: 4 штампа, к которым обычно скатывается такая сцена "
        "(напиши их, чтобы проза их обошла)\n"
        "- необычная структура сцены: конфликт строится вокруг действия, а не "
        "разговора о чувствах\n"
        "Ответ строго в JSON с ключами: setting, characters, conflict, "
        "fresh_details (массив из 3), turn (главный поворот главы), "
        "ending_hook (как глава заканчивается), cliches_to_avoid (массив из 4)."
    )
    user_parts = [f"Тема книги: {topic}"]
    if prev_summary:
        user_parts.append(f"Резюме предыдущей главы: «{prev_summary}»")
    if prev_memory:
        user_parts.append(f"Память предыдущей главы: {prev_memory}")
    if twist:
        user_parts.append(f"Пожелание автора главы: {twist}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def format_scene_plan(plan: dict) -> str:
    lines = []
    if plan.get("setting"):
        lines.append(f"Место и время: {plan['setting']}")
    if plan.get("characters"):
        lines.append(f"Действующие: {plan['characters']}")
    if plan.get("conflict"):
        lines.append(f"Конфликт сцены: {plan['conflict']}")
    if plan.get("turn"):
        lines.append(f"Главный поворот: {plan['turn']}")
    if plan.get("ending_hook"):
        lines.append(f"Финал главы (крючок): {plan['ending_hook']}")
    for detail in plan.get("fresh_details", [])[:3]:
        lines.append(f"Неожиданная деталь: {detail}")
    avoid = plan.get("cliches_to_avoid", [])[:4]
    if avoid:
        lines.append("НЕ ИСПОЛЬЗУЙ эти штампы: " + "; ".join(avoid))
    return "\n".join(lines)


def build_critic_messages(
    *, style_card_text: str, scene_plan: str | None, variants: list[str]
) -> list[dict]:
    """Критик: выбрать лучший вариант и дать замечания."""
    listed = "\n\n".join(
        f"=== ВАРИАНТ {i + 1} ===\n{v}" for i, v in enumerate(variants)
    )
    system = (
        "Ты — строгий литературный редактор. Перед тобой "
        f"{len(variants)} варианта главы. Оцени каждый по критериям:\n"
        "- соответствие плану и манере автора;\n"
        "- отсутствие штампов и шаблонных оборотов;\n"
        "- конкретность деталей (показывает, а не рассказывает);\n"
        "- живость диалогов и динамика;\n"
        "- качество финального крючка.\n\n"
        "Выбери ЛУЧШИЙ вариант (даже если он неидеален) и составь к нему "
        "3-5 конкретных замечаний для улучшения (штампы — цитировать точно, "
        "слабые места — называть по существу, без общих слов).\n"
        'Ответ строго в JSON: {"best": <номер варианта>, '
        '"remarks": ["замечание 1", "..."]}'
    )
    user_parts = [f"МАНЕРА АВТОРА:\n{style_card_text}"]
    if scene_plan:
        user_parts.append(f"ПЛАН СЦЕНЫ:\n{scene_plan}")
    user_parts.append(f"ВАРИАНТЫ:\n\n{listed}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def build_revision_messages(
    *,
    style_card_text: str,
    scene_plan: str | None,
    chapter_text: str,
    remarks: list[str],
    words_target: int,
) -> list[dict]:
    """Финальная шлифовка выбранного варианта по замечаниям критика."""
    system = (
        "Ты — русский прозаик, мастер слова. Твоя глава прошла отбор, но редактор "
        "дал замечания. Перепиши главу, устранив ВСЕ замечания: сохрани сюжет, "
        "манеру, героев и объём, но убери штампы и усили конкретикой.\n\n"
        f"ТВОЙ ПОЧЕРК (строго соблюдай):\n{style_card_text}\n\n"
        f"Объём примерно {words_target} слов (±20%). Пиши по-русски. "
        "В тексте запрещено упоминать имя писателя и слова «стиль», «автор», "
        "«глава», «резюме», «вариант», «редактор».\n"
        "ФОРМАТ ОТВЕТА — обычный текст: первая строка «## » и название, "
        "затем пустая строка и текст главы."
    )
    user_parts = []
    if scene_plan:
        user_parts.append(f"ПЛАН СЦЕНЫ:\n{scene_plan}")
    user_parts.append(f"ЗАМЕЧАНИЯ РЕДАКТОРА (устрани каждое):\n" + "\n".join(
        f"- {r}" for r in remarks
    ))
    user_parts.append(f"ТЕКУЩАЯ ГЛАВА:\n\n{chapter_text}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def build_coherence_messages(
    *, style_card_text: str, chapter_text: str
) -> list[dict]:
    """Критик-стилист: поиск бессмысленных рывков и нелогичных конструкций."""
    system = (
        "Ты — строгий редактор-стилист. Прочти главу и найди места, где текст "
        "ТЕРЯЕТ СМЫСЛ, а не просто написан своеобразно:\n"
        "- бессмысленные скачки: новое имя/предмет возникает без объяснения и "
        "ничего не значит («ехал Митрич: своё горе, два огурца и память на "
        "лозунги» — перечисление имитирует стиль, но не значит ничего);\n"
        "- нелогичные перечисления, где предметы не связаны общей мыслью;\n"
        "- образы, которые невозможно представить;\n"
        "- фразы, после которых непонятно, кто говорит или что происходит;\n"
        "- АБСУРДНЫЕ СКАЗУЕМЫЕ: действие, которое подлежащее не может выполнить "
        "по смыслу («Вагон помолчал ровно столько, сколько молчат мужики, "
        "и запил» — запил кто? вагон?; «туман ушёл запивать чай» и т.п.). "
        "Олицетворение допустимо, только если сразу читается как приём "
        "и создаёт ясный образ.\n\n"
        "ВАЖНО: своеобразная манера, длинные фразы, гротеск и абсурд как приём — "
        "НЕ нарушение, если за ним читается смысл. Нарушение — это когда смысл "
        "потерян полностью.\n"
        'Ответ строго в JSON: {"ok": true/false, "problems": '
        '[{"quote": "точная цитата проблемного места", "why": "что не так"}]}. '
        "Если глава в порядке — ok: true и пустой problems."
    )
    user = f"МАНЕРА АВТОРА:\n{style_card_text}\n\nГЛАВА:\n{chapter_text}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_repair_messages(
    *,
    style_card_text: str,
    chapter_text: str,
    problems: list[dict],
    words_target: int,
) -> list[dict]:
    """Точечный ремонт: исправить только проблемные места, остальное не трогать."""
    listed = "\n".join(
        f"- «{p.get('quote', '')}» — {p.get('why', '')}" for p in problems
    )
    system = (
        "Ты — русский прозаик, мастер слова. Редактор нашёл в главе места, "
        "где текст теряет смысл. Исправь ТОЛЬКО эти места: убери бессмысленные "
        "рывки и нелогичные перечисления, замени их осмысленными — в той же "
        "манере автора. ВСЁ остальное перепиши дословно без изменений: сюжет, "
        "героев, порядок сцен, объём.\n\n"
        f"ТВОЙ ПОЧЕРК:\n{style_card_text}\n\n"
        f"Объём примерно {words_target} слов (±20%). Пиши по-русски.\n"
        "ФОРМАТ ОТВЕТА — обычный текст: первая строка «## » и название, "
        "затем пустая строка и текст главы."
    )
    user = f"ПРОБЛЕМНЫЕ МЕСТА (исправь каждое):\n{listed}\n\nГЛАВА:\n\n{chapter_text}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_style_card_messages(author_name: str) -> list[dict]:
    system = (
        "Ты — литературный редактор. Опиши стилевые особенности писателя 4-6 предложениями: "
        "длина фраз, лексика, тон, типичные приёмы, характерные темы, чего избегать. "
        "Пиши как инструкцию для имитации стиля, обращайся к приёмам, а не к имени. "
        "Ответ строго в JSON: {\"style_card\": \"...\"}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Писатель: {author_name}"},
    ]
