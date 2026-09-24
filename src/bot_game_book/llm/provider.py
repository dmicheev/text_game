import json
import re

import httpx


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
        self._client = httpx.AsyncClient(timeout=120.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_json(self, messages: list[dict], temperature: float = 0.8) -> dict:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
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
        try:
            return parse_json_content(content)
        except LLMError:
            retry = await self._raw_chat(messages, temperature)
            return parse_json_content(retry)

    async def _raw_chat(self, messages: list[dict], temperature: float) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            response = await self._client.post(
                f"{self._api_base}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise LLMError(f"llm retry failed: {e}") from e
