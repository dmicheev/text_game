"""Тесты двухстадийной генерации: проза + двойное резюме (summary/memory)."""

import pytest

from bot_game_book.llm.generation import ChapterGenerator
from bot_game_book.llm.validator import ChapterValidationError, parse_prose_chapter


class FakeProvider:
    def __init__(
        self,
        prose: str = "",
        summaries: list[dict] | None = None,
    ) -> None:
        self.prose = prose
        self.summaries = list(summaries or [])
        self.text_calls: list[dict] = []
        self.json_calls: list[dict] = []

    async def chat_text(self, messages, temperature=0.8, model=None):
        self.text_calls.append(
            {"temperature": temperature, "model": model, "messages": messages}
        )
        return self.prose

    async def chat_json(self, messages, temperature=0.8, model=None):
        self.json_calls.append({"model": model})
        if self.summaries:
            self._last = self.summaries.pop(0)
        return dict(getattr(self, "_last", {"summary": "", "memory": ""}))


class TestParseProseChapter:
    def test_title_and_body(self):
        draft = parse_prose_chapter("## Ночь на постоялом дворе\n\nШёл дождь...", 2)
        assert draft.title == "Ночь на постоялом дворе"
        assert draft.chapter == "Шёл дождь..."
        assert draft.summary == ""

    def test_title_without_marker(self):
        draft = parse_prose_chapter("Просто заголовок\n\nТекст", 3)
        assert draft.title == "Просто заголовок"
        assert draft.chapter == "Текст"

    def test_no_title_fallback(self):
        draft = parse_prose_chapter("Текст без названия одной строкой", 5)
        assert draft.title == "Глава 5"

    def test_empty_body_raises(self):
        with pytest.raises(ChapterValidationError):
            parse_prose_chapter("## Только заголовок", 1)


class TestTwoStageGeneration:
    async def test_prose_then_dual_summary_fast_model(self):
        provider = FakeProvider(
            prose="## Глава первая\n\n" + "слово " * 300,
            summaries=[
                {
                    "summary": "принц нашёл письмо в саду",
                    "memory": "Герой Аркадий нашёл письмо; письмо писала Эмма; интрига письма не раскрыта",
                }
            ],
        )
        generator = ChapterGenerator(provider, fast_model="glm-5.3-flash")
        draft = await generator.generate_chapter(
            style_card_text="Карточка стиля",
            topic="тема",
            chapter_idx=1,
            chapters_total=4,
            words_target=300,
            summary_words=5,
            prev_summary=None,
            temperature=0.9,
        )
        assert draft.title == "Глава первая"
        assert len(draft.chapter.split()) == 300
        assert len(provider.text_calls) == 1
        assert provider.text_calls[0]["temperature"] == 0.9
        assert provider.json_calls[0]["model"] == "glm-5.3-flash"
        assert draft.summary == "принц нашёл письмо в саду"
        assert "Аркадий" in draft.memory

    async def test_summary_retry_then_trim_memory_fallback(self):
        provider = FakeProvider(
            prose="## X\n\n" + "слово " * 200,
            summaries=[
                {"summary": "ну точно слишком длинное резюме тут", "memory": "мем1"},
                {"summary": "короче но не то совсем", "memory": "мем2"},
                {"summary": "третья попытка", "memory": "мем3"},
            ],
        )
        generator = ChapterGenerator(provider, fast_model="fast")
        draft = await generator.generate_chapter(
            style_card_text="карточка",
            topic="тема",
            chapter_idx=2,
            chapters_total=4,
            words_target=200,
            summary_words=2,
            prev_summary="было",
        )
        assert len(provider.json_calls) == 3
        words = draft.summary.split()
        assert len(words) == 2  # принудительная обрезка
        assert draft.memory == "мем3"  # память валидна — используется последняя

    async def test_memory_passed_into_next_chapter_prompt(self):
        provider = FakeProvider(
            prose="## X\n\n" + "слово " * 200,
            summaries=[{"summary": "а б в г", "memory": "Аркадий и Эмма в саду"}],
        )
        generator = ChapterGenerator(provider)
        await generator.generate_chapter(
            style_card_text="карточка",
            topic="тема",
            chapter_idx=3,
            chapters_total=4,
            words_target=200,
            summary_words=4,
            prev_summary="резюме прошлой",
            prev_memory="Аркадий нашёл письмо, Эмма молчит",
        )
        user_prompt = provider.text_calls[0]["messages"][1]["content"]
        assert "Аркадий нашёл письмо, Эмма молчит" in user_prompt
        assert "ПОДРОБНАЯ ПАМЯТЬ" in user_prompt

    async def test_wordcount_violation_retries_prose_once(self):
        provider = FakeProvider(
            prose="## X\n\n" + "слово " * 50,
            summaries=[{"summary": "итог", "memory": "память"}],
        )
        # проза вернётся той же — ретрай не улучшит, но не упадёт
        generator = ChapterGenerator(provider)
        draft = await generator.generate_chapter(
            style_card_text="карточка",
            topic="тема",
            chapter_idx=1,
            chapters_total=3,
            words_target=200,
            summary_words=1,
            prev_summary=None,
        )
        assert len(provider.text_calls) == 2  # исходный + ретрай объёма
        assert draft.summary
