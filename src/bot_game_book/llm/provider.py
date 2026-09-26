import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def parse_json_content(content: str) -> dict:
    cleaned = content.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid json from llm: {e}") from e
    if not isinstance(parsed, dict):
        raise LLMError("llm response is not an object")
    return parsed


class LLMProvider:
    def __init__(self, api_base: str, api_key: str, model: str) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(timeout=180.0)

    async def aclose(self) -> None:
        await self._client.close()

    async def _post(self, payload: dict) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            response = await self._client.post(
                f"{self._api_base}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"llm request failed: {e}") from e
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"unexpected llm response shape: {e}") from e
        if not content:
            raise LLMError("empty llm content")
        return content

    async def chat_text(
        self, messages: list[dict], temperature: float = 0.8, model: str | None = None
    ) -> str:
        """Обычный текстовый ответ (без response_format) — для прозы."""
        payload = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
        }
        return await self._post(payload)

    async def chat_json(
        self, messages: list[dict], temperature: float = 0.8, model: str | None = None
    ) -> dict:
        payload = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        content = await self._post(payload)
        try:
            return parse_json_content(content)
        except LLMError:
            retry = await self._post(payload)
            return parse_json_content(retry)
