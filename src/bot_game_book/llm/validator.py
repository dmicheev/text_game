from dataclasses import dataclass

from bot_game_book.llm.prompts import count_words


class ChapterValidationError(Exception):
    pass


@dataclass
class ChapterDraft:
    title: str
    chapter: str
    summary: str
    memory: str = ""


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


def parse_prose_chapter(text: str, chapter_idx: int) -> ChapterDraft:
    """Разбор прозаического ответа: '## Название' + текст главы (без резюме)."""
    cleaned = text.strip()
    if cleaned.startswith("#"):
        first_line, _, body = cleaned.partition("\n")
        title = first_line.lstrip("#").strip()
    else:
        lines = cleaned.split("\n", 1)
        title = lines[0].strip() if len(lines) > 1 else ""
        body = cleaned if len(lines) == 1 else lines[1]
    body = body.strip()
    if not title:
        title = f"Глава {chapter_idx}"
    if not body:
        raise ChapterValidationError("empty chapter body")
    return ChapterDraft(title=title[:200], chapter=body, summary="")


def validate_summary(summary: str, expected_words: int) -> bool:
    return count_words(summary) == expected_words


def chapter_in_range(text: str, target_words: int) -> bool:
    return abs(count_words(text) - target_words) <= 0.2 * target_words
