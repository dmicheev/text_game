from bot_game_book.llm.prompts import (
    build_chapter_messages,
    build_style_card_messages,
    count_words,
    trim_to_words,
)
from bot_game_book.llm.provider import LLMError, LLMProvider
from bot_game_book.llm.validator import (
    ChapterDraft,
    ChapterValidationError,
    chapter_in_range,
    parse_chapter_json,
    validate_summary,
)


class ChapterGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def generate_chapter(
        self,
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
    ) -> ChapterDraft:
        messages = build_chapter_messages(
            style_card_text=style_card_text,
            topic=topic,
            chapter_idx=chapter_idx,
            chapters_total=chapters_total,
            words_target=words_target,
            summary_words=summary_words,
            prev_summary=prev_summary,
            twist=twist,
            rewrite_note=rewrite_note,
        )
        draft = parse_chapter_json(
            await self._provider.chat_json(messages, temperature=0.8)
        )

        def score(d: ChapterDraft) -> tuple[bool, bool]:
            return (
                validate_summary(d.summary, summary_words),
                chapter_in_range(d.chapter, words_target),
            )

        if score(draft) != (True, True):
            messages = messages + [
                {
                    "role": "system",
                    "content": (
                        "Предыдущая попытка была неточной: резюме должно содержать ровно "
                        f"{summary_words} слов (сейчас {count_words(draft.summary)}), "
                        f"объём главы — около {words_target} слов "
                        f"(сейчас {count_words(draft.chapter)}). Исправь и верни ответ снова в JSON."
                    ),
                }
            ]
            try:
                retry = parse_chapter_json(
                    await self._provider.chat_json(messages, temperature=0.8)
                )
                if score(retry) > score(draft):
                    draft = retry
            except (LLMError, ChapterValidationError):
                pass
        draft.summary = trim_to_words(draft.summary, summary_words)
        return draft

    async def generate_style_card(self, author_name: str) -> str:
        messages = build_style_card_messages(author_name)
        raw = await self._provider.chat_json(messages, temperature=0.7)
        card = str(raw.get("style_card", "")).strip()
        if not card:
            raise LLMError("empty style card")
        return card
