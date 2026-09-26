"""Тесты двухстадийной генерации: проза + двойное резюме (summary/memory)."""

import pytest

from bot_game_book.llm.generation import ChapterGenerator
from bot_game_book.llm.validator import ChapterValidationError, parse_prose_chapter


class FakeProvider:
    def __init__(
        self,
        prose: str = "",
        prosequence: list[str] | None = None,
        summaries: list[dict] | None = None,
        plans: list[dict] | None = None,
        critics: list[dict] | None = None,
        coherences: list[dict] | None = None,
    ) -> None:
        self.prose = prose
        self.prose_queue = list(prosequence or [])
        self.summaries = list(summaries or [])
        self.plans = list(plans or [])
        self.critics = list(critics or [])
        self.coherences = list(coherences or [])
        self.text_calls: list[dict] = []
        self.json_calls: list[dict] = []

    async def chat_text(self, messages, temperature=0.8, model=None):
        self.text_calls.append(
            {"temperature": temperature, "model": model, "messages": messages}
        )
        if self.prose_queue:
            return self.prose_queue.pop(0)
        return self.prose

    async def chat_json(self, messages, temperature=0.8, model=None):
        kind = _call_kind(messages)
        self.json_calls.append({"model": model, "kind": kind})
        if kind == "plan":
            return self.plans.pop(0) if self.plans else {}
        if kind == "critic":
            return self.critics.pop(0) if self.critics else {}
        if kind == "coherence":
            return self.coherences.pop(0) if self.coherences else {"ok": True, "problems": []}
        if self.summaries:
            self._last = self.summaries.pop(0)
        return dict(getattr(self, "_last", {"summary": "", "memory": ""}))


def _call_kind(messages: list[dict]) -> str:
    system = messages[0]["content"]
    if "сценарист" in system:
        return "plan"
    if "редактор-стилист" in system:
        return "coherence"
    if "литературный редактор" in system and "ВАРИАНТ" in messages[1]["content"]:
        return "critic"
    return "summary"


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
    async def test_plan_first_then_prose_and_dual_summary(self):
        provider = FakeProvider(
            prose="## Глава первая\n\n" + "слово " * 300,
            plans=[
                {
                    "setting": "канцелярия",
                    "characters": "Аким, бухгалтерша",
                    "conflict": "печать исчезла",
                    "fresh_details": ["гусь под столом", "скрепки-змея", "запах валерьянки"],
                    "turn": "печать ожила",
                    "ending_hook": "штамп в темноте",
                    "cliches_to_avoid": ["тревожная тишина", "сердце сжалось"],
                }
            ],
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
            chapter_idx=2,
            chapters_total=4,
            words_target=300,
            summary_words=5,
            prev_summary="прошлое",
            prev_memory="память прошлой главы",
            temperature=0.9,
            style_label="Гоголь",
        )
        assert draft.title == "Глава первая"
        # стадия 1: план на быстрой модели
        assert provider.json_calls[0]["kind"] == "plan"
        assert provider.json_calls[0]["model"] == "glm-5.3-flash"
        # стадия 2: план вошёл в промпт прозы (вместе с анти-штампами)
        user_prompt = provider.text_calls[0]["messages"][1]["content"]
        assert "ПЛАН СЦЕНЫ" in user_prompt
        assert "гусь под столом" in user_prompt
        assert "тревожная тишина" in user_prompt
        assert "память прошлой главы" in user_prompt
        # стадия 3: резюме + память на быстрой модели
        assert provider.json_calls[1]["kind"] == "coherence"
        assert provider.json_calls[1]["model"] is None  # главный модель
        assert provider.json_calls[2]["kind"] == "summary"
        assert provider.json_calls[2]["model"] == "glm-5.3-flash"
        assert draft.summary == "принц нашёл письмо в саду"
        assert "Аркадий" in draft.memory

    async def test_sampling_critic_revision_pipeline(self):
        good = "## Хорошая глава\n\n" + "слово " * 300
        provider = FakeProvider(
            prosequence=[
                "## Плохой вариант один\n\n" + "слово " * 300,
                good,
                "## Плохой вариант три\n\n" + "слово " * 300,
                "## Хорошая глава (шлифовка)\n\n" + "слово " * 300,
            ],
            plans=[
                {
                    "setting": "сцена",
                    "conflict": "конфликт",
                    "fresh_details": ["деталь"],
                    "cliches_to_avoid": ["штамп"],
                }
            ],
            critics=[{"best": 2, "remarks": ["штамп «тревожная тишина»", "финал слабый"]}],
            summaries=[{"summary": "а б в г", "memory": "мем"}],
        )
        generator = ChapterGenerator(provider, variants=3)
        draft = await generator.generate_chapter(
            style_card_text="карточка",
            topic="тема",
            chapter_idx=2,
            chapters_total=4,
            words_target=300,
            summary_words=4,
            prev_summary="было",
        )
        # 3 семпла + 1 шлифовка по замечаниям
        assert len(provider.text_calls) == 4
        kinds = [c["kind"] for c in provider.json_calls]
        assert kinds == ["plan", "critic", "coherence", "summary"]
        # критик выбрал вариант 2; финал — результат шлифовки
        assert draft.title == "Хорошая глава (шлифовка)"
        revision_prompt = provider.text_calls[3]["messages"][1]["content"]
        assert "замечани" in revision_prompt.lower()
        assert "тревожная тишина" in revision_prompt

    async def test_critic_failure_keeps_first_variant(self):
        provider = FakeProvider(
            prosequence=[
                "## A\n\n" + "слово " * 200,
                "## B\n\n" + "слово " * 200,
            ],
            critics=[{}],  # некорректный JSON-ответ критика
            summaries=[{"summary": "а б в г", "memory": "мем"}],
        )
        generator = ChapterGenerator(provider, variants=2)
        draft = await generator.generate_chapter(
            style_card_text="карточка",
            topic="тема",
            chapter_idx=1,
            chapters_total=3,
            words_target=200,
            summary_words=4,
            prev_summary=None,
        )
        # без замечаний — нет шлифовки
        assert len(provider.text_calls) == 2
        assert draft.title == "A"

    async def test_coherence_critic_repairs_nonsense(self):
        provider = FakeProvider(
            prosequence=[
                "## Глава\n\n" + "слово " * 200,  # единственный семпл
                "## Глава\n\n" + "слово " * 200 + " и починенный смысл",  # ремонт
            ],
            coherences=[
                {
                    "ok": False,
                    "problems": [
                        {
                            "quote": "своё горе, два огурца и память на лозунги",
                            "why": "перечисление ничего не значит",
                        }
                    ],
                }
            ],
            summaries=[{"summary": "а б в г", "memory": "мем"}],
        )
        generator = ChapterGenerator(provider, variants=1)
        draft = await generator.generate_chapter(
            style_card_text="карточка",
            topic="тема",
            chapter_idx=1,
            chapters_total=3,
            words_target=200,
            summary_words=4,
            prev_summary=None,
        )
        kinds = [c["kind"] for c in provider.json_calls]
        assert kinds == ["plan", "coherence", "summary"]
        # ремёмнтная проза содержит исправление
        assert "починенный смысл" in draft.chapter
        repair_prompt = provider.text_calls[1]["messages"][1]["content"]
        assert "два огурца" in repair_prompt

    async def test_coherence_ok_no_repair(self):
        provider = FakeProvider(
            prose="## Глава\n\n" + "слово " * 200,
            coherences=[{"ok": True, "problems": []}],
            summaries=[{"summary": "а б в г", "memory": "мем"}],
        )
        generator = ChapterGenerator(provider, variants=1)
        await generator.generate_chapter(
            style_card_text="карточка",
            topic="тема",
            chapter_idx=1,
            chapters_total=3,
            words_target=200,
            summary_words=4,
            prev_summary=None,
        )
        # нет проблем — только одна проза, без ремонта
        assert len(provider.text_calls) == 1

    async def test_plan_failure_falls_back_to_prose(self):
        provider = FakeProvider(
            prose="## X\n\n" + "слово " * 200,
            plans=[],
            summaries=[{"summary": "а б в г", "memory": "мем"}],
        )
        generator = ChapterGenerator(provider)
        draft = await generator.generate_chapter(
            style_card_text="карточка",
            topic="тема",
            chapter_idx=1,
            chapters_total=3,
            words_target=200,
            summary_words=4,
            prev_summary=None,
        )
        # план не удался (пустой JSON) — проза всё равно написана
        user_prompt = provider.text_calls[0]["messages"][1]["content"]
        assert "ПЛАН СЦЕНЫ" not in user_prompt
        assert draft.summary == "а б в г"

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
        # 1 план + коhерент-критик + 3 попытки резюме
        assert len(provider.json_calls) == 5
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
