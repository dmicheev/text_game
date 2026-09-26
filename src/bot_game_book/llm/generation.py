from bot_game_book.llm.prompts import (
    build_chapter_messages,
    build_style_card_messages,
    build_summary_messages,
    count_words,
    trim_to_words,
)
from bot_game_book.llm.provider import LLMError, LLMProvider
from bot_game_book.llm.validator import (
    ChapterDraft,
    ChapterValidationError,
    chapter_in_range,
    parse_prose_chapter,
)


class ChapterGenerator:
    """Двухстадийная генерация: проза (LLM_MODEL) + резюме (LLM_MODEL_FAST)."""

    def __init__(self, provider: LLMProvider, fast_model: str | None = None) -> None:
        self._provider = provider
        self._fast_model = fast_model

    async def _generate_prose(
        self, messages: list[dict], temperature: float, chapter_idx: int
    ) -> ChapterDraft:
        raw = await self._provider.chat_text(messages, temperature=temperature)
        return parse_prose_chapter(raw, chapter_idx)

    async def _generate_summary(
        self, chapter_text: str, topic: str, summary_words: int
    ) -> tuple[str, str]:
        """(короткое резюме для игроков, развёрнутая память для генерации)."""
        messages = build_summary_messages(
            chapter_text=chapter_text, topic=topic, summary_words=summary_words
        )
        last_summary = ""
        last_memory = ""
        for _ in range(3):
            raw = await self._provider.chat_json(
                messages, temperature=0.2, model=self._fast_model
            )
            last_summary = str(raw.get("summary", "")).strip()
            last_memory = str(raw.get("memory", "")).strip()
            if last_summary and count_words(last_summary) == summary_words and last_memory:
                return last_summary, last_memory
        memory = last_memory or trim_to_words(chapter_text, 60)
        return trim_to_words(last_summary, summary_words), memory

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
        prev_memory: str | None = None,
        twist: str | None = None,
        rewrite_note: str | None = None,
        temperature: float | None = None,
    ) -> ChapterDraft:
        temp = 0.85 if temperature is None else temperature
        messages = build_chapter_messages(
            style_card_text=style_card_text,
            topic=topic,
            chapter_idx=chapter_idx,
            chapters_total=chapters_total,
            words_target=words_target,
            prev_summary=prev_summary,
            prev_memory=prev_memory,
            twist=twist,
            rewrite_note=rewrite_note,
        )
        draft = await self._generate_prose(messages, temp, chapter_idx)

        if not chapter_in_range(draft.chapter, words_target):
            retry_messages = messages + [
                {
                    "role": "system",
                    "content": (
                        f"Предыдущая попытка вышла за объём: было "
                        f"{count_words(draft.chapter)} слов, нужно около "
                        f"{words_target} (±20%). Напиши главу заново, "
                        "сохранив манеру и сюжетный ход."
                    ),
                }
            ]
            try:
                retry = await self._generate_prose(retry_messages, temp, chapter_idx)
                if abs(count_words(retry.chapter) - words_target) < abs(
                    count_words(draft.chapter) - words_target
                ):
                    draft = retry
            except (LLMError, ChapterValidationError):
                pass

        draft.summary, draft.memory = await self._generate_summary(
            draft.chapter, topic, summary_words
        )
        return draft

    async def generate_style_card(self, author_name: str) -> str:
        messages = build_style_card_messages(author_name)
        raw = await self._provider.chat_json(
            messages, temperature=0.7, model=self._fast_model
        )
        card = str(raw.get("style_card", "")).strip()
        if not card:
            raise LLMError("empty style card")
        return card
