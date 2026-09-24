from dataclasses import dataclass

from bot_game_book.llm.prompts import count_words


class ChapterValidationError(Exception):
    pass


@dataclass
class ChapterDraft:
    title: str
    chapter: str
    summary: str


def parse_chapter_json(raw: dict) -> ChapterDraft:
    try:
        title = str(raw["title"]).strip()
        chapter = str(raw["chapter"]).strip()
        summary = str(raw["summary"]).strip()
    except KeyError as e:
        raise ChapterValidationError(f"missing key: {e}") from e
    if not title or not chapter or not summary:
        raise ChapterValidationError("empty field in chapter draft")
    return ChapterDraft(title=title, chapter=chapter, summary=summary)


def validate_summary(summary: str, expected_words: int) -> bool:
    return count_words(summary) == expected_words


def chapter_in_range(text: str, target_words: int) -> bool:
    return abs(count_words(text) - target_words) <= 0.2 * target_words
