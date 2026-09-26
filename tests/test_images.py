"""Тесты иллюстраций: промпт, провайдеры, интеграция с Notifier."""

import httpx
import pytest

from bot_game_book.images import (
    IllustrationError,
    Illustrator,
    PollinationsImages,
    ZAIImages,
    build_illustration_messages,
)
from bot_game_book.notifier import Notifier


class TestPromptBuilder:
    def test_prompt_shape(self):
        messages = build_illustration_messages("Гоголь", "Текст главы про печать")
        assert messages[0]["role"] == "system"
        assert "image_prompt" in messages[0]["content"]
        assert "Гоголь" in messages[0]["content"]
        assert "Текст главы" in messages[1]["content"]


class TestPollinations:
    async def test_generate_bytes_and_params(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=b"fakejpegbytes")

        provider = PollinationsImages(base_url="https://img.test")
        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5
        )
        image = await provider.generate("vintage engraving of a seal")
        assert image == b"fakejpegbytes"
        url = str(requests[0].url)
        assert "/prompt/vintage%20engraving%20of%20a%20seal" in url
        assert "model=flux" in url
        assert "nologo=true" in url

    async def test_http_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        provider = PollinationsImages(base_url="https://img.test")
        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5
        )
        with pytest.raises(IllustrationError):
            await provider.generate("x")


class TestZAIImages:
    async def test_generate_downloads_url(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path.endswith("/images/generations"):
                return httpx.Response(200, json={"data": [{"url": "https://img.test/file.jpg"}]})
            return httpx.Response(200, content=b"jpegdata")

        provider = ZAIImages("https://api.test/v4", "key")
        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5
        )
        image = await provider.generate("cat")
        assert image == b"jpegdata"
        assert calls[0].url.path.endswith("/images/generations")
        assert calls[0].headers["Authorization"] == "Bearer key"
        assert calls[1].url.path == "/file.jpg"


class FakeLLM:
    def __init__(self, result: dict) -> None:
        self._result = result
        self.calls = 0

    async def chat_json(self, messages, temperature=0.5, model=None):
        self.calls += 1
        return self._result


class FakeImages:
    async def generate(self, prompt: str) -> bytes:
        return b"img-" + prompt.encode()


class TestIllustrator:
    async def test_prompt_then_image(self):
        llm = FakeLLM({"image_prompt": "dark etching, bureaucrat and a seal"})
        illustrator = Illustrator(FakeImages(), llm, fast_model="fast")
        image, prompt = await illustrator.illustrate("Гоголь", "глава")
        assert prompt == "dark etching, bureaucrat and a seal"
        assert image == b"img-dark etching, bureaucrat and a seal"
        assert llm.calls == 1


class TestNotifierPhoto:
    async def test_send_photo_routes_by_platform(self):
        class FakeGateway:
            platform = "max"

            def __init__(self) -> None:
                self.photos = []

            async def send_photo(self, chat_id, image, caption=None):
                self.photos.append((chat_id, image, caption))
                return "1"

        gw = FakeGateway()
        notifier = Notifier({"max": gw})

        class U:
            platform = "max"
            platform_user_id = 42
            id = 7

        await notifier.send_photo_user(U(), b"bytes", "подпись")  # type: ignore[arg-type]
        assert gw.photos == [(42, b"bytes", "подпись")]
