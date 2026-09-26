import asyncio
import time

from bot_game_book.llm.prompts import (
    build_chapter_messages,
    build_coherence_messages,
    build_critic_messages,
    build_repair_messages,
    build_revision_messages,
    build_scene_plan_messages,
    build_style_card_messages,
    build_summary_messages,
    count_words,
    format_scene_plan,
    trim_to_words,
)
from bot_game_book.llm.provider import LLMError, LLMProvider
from bot_game_book.llm.validator import (
    ChapterDraft,
    ChapterValidationError,
    chapter_in_range,
    parse_prose_chapter,
)


class _Progress:
    """Прогресс конвейера: стадии + тикер таймера, пока стадия выполняется."""

    def __init__(self, on_stage, tick_seconds: int = 15) -> None:
        self._on_stage = on_stage
        self._tick_seconds = tick_seconds
        self._started = time.monotonic() if on_stage else None
        self._current: str | None = None
        self._task: asyncio.Task | None = None

    async def report(self, text: str) -> None:
        if self._on_stage is None:
            return
        self._current = text
        await self._emit()

    async def _emit(self) -> None:
        elapsed = int(time.monotonic() - (self._started or 0))
        try:
            await self._on_stage(f"🌀 {self._current} · прошло {elapsed} с")
        except Exception:
            pass

    def start(self) -> None:
        if self._on_stage is not None and self._task is None:
            self._task = asyncio.create_task(self._ticker())

    async def _ticker(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._tick_seconds)
                if self._current:
                    await self._emit()
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


class ChapterGenerator:
    """План → семплирование N вариантов → критик → шлифовка → резюме."""

    def __init__(
        self,
        provider: LLMProvider,
        fast_model: str | None = None,
        variants: int = 1,
    ) -> None:
        self._provider = provider
        self._fast_model = fast_model
        self._variants = max(1, variants)

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

    async def _make_scene_plan(
        self,
        *,
        style_label: str,
        topic: str,
        chapter_idx: int,
        chapters_total: int,
        prev_summary: str | None,
        prev_memory: str | None,
        twist: str | None,
    ) -> str | None:
        """Стадия 1: дешёвый план сцены с анти-штамповыми ходами."""
        messages = build_scene_plan_messages(
            style_label=style_label,
            topic=topic,
            chapter_idx=chapter_idx,
            chapters_total=chapters_total,
            prev_summary=prev_summary,
            prev_memory=prev_memory,
            twist=twist,
        )
        try:
            raw = await self._provider.chat_json(
                messages, temperature=0.8, model=self._fast_model
            )
            return format_scene_plan(raw) or None
        except LLMError:
            return None

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
        style_label: str | None = None,
        on_stage=None,
    ) -> ChapterDraft:
        progress = _Progress(on_stage)
        progress.start()
        temp = 0.85 if temperature is None else temperature
        try:
            return await self._generate_chapter_inner(
                style_card_text=style_card_text,
                topic=topic,
                chapter_idx=chapter_idx,
                chapters_total=chapters_total,
                words_target=words_target,
                summary_words=summary_words,
                prev_summary=prev_summary,
                prev_memory=prev_memory,
                twist=twist,
                rewrite_note=rewrite_note,
                temp=temp,
                style_label=style_label,
                progress=progress,
            )
        finally:
            await progress.stop()

    async def _generate_chapter_inner(
        self,
        *,
        style_card_text: str,
        topic: str,
        chapter_idx: int,
        chapters_total: int,
        words_target: int,
        summary_words: int,
        prev_summary: str | None,
        prev_memory: str | None,
        twist: str | None,
        rewrite_note: str | None,
        temp: float,
        style_label: str | None,
        progress: _Progress,
    ) -> ChapterDraft:
        await progress.report("📐 Составляю план сцены со свежими деталями")
        scene_plan = await self._make_scene_plan(
            style_label=style_label or "современная литература",
            topic=topic,
            chapter_idx=chapter_idx,
            chapters_total=chapters_total,
            prev_summary=prev_summary,
            prev_memory=prev_memory,
            twist=twist,
        )
        messages = build_chapter_messages(
            style_card_text=style_card_text,
            topic=topic,
            chapter_idx=chapter_idx,
            chapters_total=chapters_total,
            words_target=words_target,
            prev_summary=prev_summary,
            prev_memory=prev_memory,
            scene_plan=scene_plan,
            twist=twist,
            rewrite_note=rewrite_note,
        )

        variants = await self._sample_variants(
            messages, temp, chapter_idx, progress=progress
        )
        draft = await self._critique_and_revise(
            variants=variants,
            scene_plan=scene_plan,
            style_card_text=style_card_text,
            words_target=words_target,
            temp=temp,
            chapter_idx=chapter_idx,
            progress=progress,
        )
        draft = await self._coherence_pass(
            draft=draft,
            style_card_text=style_card_text,
            words_target=words_target,
            temp=temp,
            chapter_idx=chapter_idx,
            progress=progress,
        )
        await progress.report("🔗 Готовлю резюме для следующего автора")

        if not chapter_in_range(draft.chapter, words_target):
            try:
                retry = await self._generate_prose(messages, temp, chapter_idx)
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

    async def _sample_variants(
        self, messages: list[dict], temp: float, chapter_idx: int, progress=None
    ) -> list[ChapterDraft]:
        """Параллельное семплирование вариантов с разбросом температур."""
        progress = progress or _Progress(None)
        await progress.report(
            f"✍️ Пишу {self._variants} варианта главы — самый долгий шаг"
            if self._variants > 1
            else "✍️ Пишу главу"
        )
        temps = [temp]
        for i in range(1, self._variants):
            temps.append(min(1.1, max(0.5, temp + (0.08 if i % 2 else -0.08))))
        tasks = [
            asyncio.create_task(self._generate_prose(messages, t, chapter_idx))
            for t in temps
        ]
        variants: list[ChapterDraft] = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            try:
                draft = await coro
                variants.append(draft)
            except Exception:
                if len(tasks) == self._variants and not variants:
                    first_error = None
            done += 1
            await progress.report(f"✍️ Готово вариантов: {done}/{len(tasks)}")
        if not variants:
            raise LLMError("no chapter variants generated")
        return variants

    async def _critique_and_revise(
        self,
        *,
        variants: list[ChapterDraft],
        scene_plan: str | None,
        style_card_text: str,
        words_target: int,
        temp: float,
        chapter_idx: int,
        progress=None,
    ) -> ChapterDraft:
        """Критик выбирает лучший вариант и даёт замечания; затем шлифовка."""
        progress = progress or _Progress(None)
        draft = variants[0]
        if len(variants) < 2:
            return draft
        await progress.report("🕵️ Критик сравнивает варианты")
        try:
            critic_raw = await self._provider.chat_json(
                build_critic_messages(
                    style_card_text=style_card_text,
                    scene_plan=scene_plan,
                    variants=[v.chapter for v in variants],
                ),
                temperature=0.3,
            )
            best_idx = int(critic_raw.get("best", 1)) - 1
            if 0 <= best_idx < len(variants):
                draft = variants[best_idx]
            remarks = [
                str(r).strip()
                for r in critic_raw.get("remarks", [])
                if str(r).strip()
            ][:5]
        except (LLMError, ValueError, TypeError):
            return draft
        if not remarks:
            return draft
        await progress.report("✨ Шлифую лучший вариант по замечаниям")
        try:
            revision = await self._generate_prose(
                build_revision_messages(
                    style_card_text=style_card_text,
                    scene_plan=scene_plan,
                    chapter_text=f"## {draft.title}\n\n{draft.chapter}",
                    remarks=remarks,
                    words_target=words_target,
                ),
                temp,
                chapter_idx,
            )
            if chapter_in_range(
                revision.chapter, words_target
            ) or not chapter_in_range(draft.chapter, words_target):
                return revision
        except (LLMError, ChapterValidationError):
            pass
        return draft

    async def _coherence_pass(
        self,
        *,
        draft: ChapterDraft,
        style_card_text: str,
        words_target: int,
        temp: float,
        chapter_idx: int,
        progress=None,
    ) -> ChapterDraft:
        """Критик-стилист: бессмысленные рывки → точечный ремонт."""
        progress = progress or _Progress(None)
        await progress.report("🧐 Проверяю связность смысла")
        try:
            raw = await self._provider.chat_json(
                build_coherence_messages(
                    style_card_text=style_card_text,
                    chapter_text=f"## {draft.title}\n\n{draft.chapter}",
                ),
                temperature=0.2,
            )
            problems = [p for p in raw.get("problems", []) if isinstance(p, dict)]
            if raw.get("ok", True) or not problems:
                return draft
        except LLMError:
            return draft
        await progress.report("🔧 Чиню проблемные места")
        try:
            repaired = await self._generate_prose(
                build_repair_messages(
                    style_card_text=style_card_text,
                    chapter_text=f"## {draft.title}\n\n{draft.chapter}",
                    problems=problems[:5],
                    words_target=words_target,
                ),
                temp,
                chapter_idx,
            )
            if chapter_in_range(
                repaired.chapter, words_target
            ) or not chapter_in_range(draft.chapter, words_target):
                return repaired
        except (LLMError, ChapterValidationError):
            pass
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
