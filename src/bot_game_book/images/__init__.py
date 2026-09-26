"""Генерация иллюстраций к главам: промпт через LLM + картинка через провайдера."""

import logging
import urllib.parse

import httpx

from bot_game_book.llm.provider import LLMError, LLMProvider

logger = logging.getLogger(__name__)


class IllustrationError(Exception):
    pass


def build_illustration_messages(style_label: str, chapter_text: str) -> list[dict]:
    system = (
        "Ты — художник-иллюстратор книг. По тексту главы составь промпт для "
        "генерации одной иллюстрации на английском языке: главная сцена, герои, "
        "настроение, художественная манера (book illustration). "
        "Стиль книги: подбери визуальную манеру под автора "
        f"(«{style_label}»), например: винтажная гравюра, акварель, тушь, "
        "мрачный офорт и т.п. Без текста и надписей на изображении, без водяных знаков.\n"
        'Ответ строго в JSON: {"image_prompt": "..."} — 25-40 слов на английском.'
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Глава (фрагмент):\n{chapter_text[:3000]}",
        },
    ]


class PollinationsImages:
    """Бесплатный провайдер без ключа: image.pollinations.ai (flux)."""

    name = "pollinations"

    def __init__(self, base_url: str = "https://image.pollinations.ai") -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0, follow_redirects=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(self, prompt: str) -> bytes:
        params = {"width": 1024, "height": 1024, "model": "flux", "nologo": "true"}
        url = f"{self._base}/prompt/{urllib.parse.quote(prompt, safe='')}"
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise IllustrationError(f"pollinations failed: {e}") from e
        if not response.content:
            raise IllustrationError("pollinations returned empty image")
        return response.content


class ZAIImages:
    """Z.AI: POST /images/generations (glm-image), затем скачивание URL."""

    name = "zai"

    def __init__(self, api_base: str, api_key: str, model: str = "glm-image") -> None:
        self._url = api_base.rstrip("/") + "/images/generations"
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(timeout=180.0, follow_redirects=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(self, prompt: str) -> bytes:
        try:
            response = await self._client.post(
                self._url,
                json={"model": self._model, "prompt": prompt, "size": "1280x1280"},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            image_url = response.json()["data"][0]["url"]
            image = await self._client.get(image_url)
            image.raise_for_status()
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise IllustrationError(f"zai images failed: {e}") from e
        if not image.content:
            raise IllustrationError("zai images returned empty image")
        return image.content


class NoImages:
    """Заглушка: иллюстрации отключены конфигом."""

    name = "none"

    async def aclose(self) -> None:
        return None

    async def generate(self, prompt: str) -> bytes | None:
        return None


def create_images_provider(settings) -> object:
    provider = settings.images_provider.strip().lower()
    if provider == "none":
        return NoImages()
    if provider == "zai":
        return ZAIImages(settings.llm_api_base, settings.llm_api_key)
    return PollinationsImages(settings.image_api_base)


class Illustrator:
    """Промпт (fast LLM) + картинка (провайдер)."""

    def __init__(self, images, llm: LLMProvider, fast_model: str | None = None) -> None:
        self._images = images
        self._llm = llm
        self._fast_model = fast_model

    async def illustrate(self, style_label: str, chapter_text: str) -> tuple[bytes, str]:
        raw = await self._llm.chat_json(
            build_illustration_messages(style_label, chapter_text),
            temperature=0.5,
            model=self._fast_model,
        )
        prompt = str(raw.get("image_prompt", "")).strip()
        if not prompt:
            raise LLMError("empty image_prompt")
        image = await self._images.generate(prompt)
        if not image:
            raise IllustrationError("image provider disabled")
        return image, prompt
