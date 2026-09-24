import pytest

from bot_game_book.llm.prompts import count_words, trim_to_words
from bot_game_book.llm.validator import (
    ChapterValidationError,
    chapter_in_range,
    parse_chapter_json,
    validate_summary,
)


def test_count_words_russian():
    assert count_words("собака улетела на Марс") == 4
    assert count_words("Привет, мир! Как дела?") == 4
    assert count_words("кое-что из жизни") == 3
    assert count_words("") == 0


def test_trim_to_words():
    assert trim_to_words("один два три четыре пять", 3) == "один два три"
    assert trim_to_words("один два", 5) == "один два"


def test_validate_summary_exact():
    assert validate_summary("раз два три четыре пять", 5)
    assert not validate_summary("раз два три", 5)


def test_chapter_in_range():
    text = " ".join(["слово"] * 300)
    assert chapter_in_range(text, 300)
    assert chapter_in_range(text, 350)
    assert not chapter_in_range(text, 500)


def test_parse_chapter_json_ok():
    draft = parse_chapter_json(
        {"title": "Т", "chapter": "Текст", "summary": "с одно"}
    )
    assert draft.title == "Т"
    assert draft.summary == "с одно"


def test_parse_chapter_json_missing_key():
    with pytest.raises(ChapterValidationError):
        parse_chapter_json({"title": "Т", "chapter": "Текст"})


def test_parse_chapter_json_empty_field():
    with pytest.raises(ChapterValidationError):
        parse_chapter_json({"title": "Т", "chapter": "   ", "summary": "с"})
