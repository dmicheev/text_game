from bot_game_book.llm.prompts import (
    build_chapter_messages,
    build_style_card_messages,
    build_summary_messages,
)


def make_messages(prev_summary, twist=None, rewrite_note=None, chapter_idx=2, total=6):
    return build_chapter_messages(
        style_card_text="Пиши в стиле Чехова. Короткие фразы.",
        topic="космос",
        chapter_idx=chapter_idx,
        chapters_total=total,
        words_target=300,
        prev_summary=prev_summary,
        twist=twist,
        rewrite_note=rewrite_note,
    )


def test_no_full_text_argument():
    import inspect

    params = inspect.signature(build_chapter_messages).parameters
    assert "prev_chapter_text" not in params
    assert "full_text" not in params


def test_first_chapter_sets_up_opening():
    messages = make_messages(prev_summary=None, chapter_idx=1)
    assert "первая глава" in messages[0]["content"]


def test_last_chapter_closes_story():
    messages = make_messages(prev_summary="что-то", chapter_idx=6, total=6)
    assert "заверши" in messages[0]["content"]


def test_middle_chapter_forbids_ending():
    messages = make_messages(prev_summary="собака улетела на Марс")
    user = messages[1]["content"]
    assert "«собака улетела на Марс»" in user
    assert "не заканчивай" in messages[0]["content"]


def test_twist_included():
    messages = make_messages(prev_summary="резюме", twist="пусть будет дракон")
    assert "пусть будет дракон" in messages[1]["content"]


def test_chapter_prompt_is_prose_not_json():
    messages = make_messages(prev_summary="резюме")
    system = messages[0]["content"]
    assert "JSON" not in system.replace("без JSON", "")
    assert "## " in system
    assert "художественная проза" in system
    assert "ТВОЙ ПОЧЕРК" in system


def test_summary_prompt_words_and_json():
    messages = build_summary_messages(
        chapter_text="Текст главы", topic="тема", summary_words=5
    )
    system = messages[1 - 1]["content"]
    assert "РОВНО 5 слов" in system
    assert "summary" in system
    assert "Текст главы" in messages[1]["content"]


def test_style_card_messages_shape():
    messages = build_style_card_messages("Виктор Пелевин")
    assert messages[0]["role"] == "system"
    assert "Пелевин" in messages[1]["content"]
