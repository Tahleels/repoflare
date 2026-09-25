"""OpenRouterProvider: BobProvider fallback backed by an OpenRouter free-tier model (see
docs/DECISIONS.md ADR-004).

Endpoint and OpenAI-compatible chat-completions schema verified against
https://openrouter.ai/docs/quickstart on 2026-09-26. Unlike GeminiProvider, this class has
NO default model: OpenRouter's own documentation warns free models "rotate out without
warning," so shipping a hardcoded free-model id here would likely be wrong within days —
pass a current one (check https://openrouter.ai/models?max_price=0) via config instead.
"""

from __future__ import annotations

import httpx

from repoflare_core.ai.provider import BobProviderError

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT_SECONDS = 30.0


class OpenRouterProvider:
    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=_TIMEOUT_SECONDS)

    def complete(self, prompt: str) -> str:
        try:
            response = self._client.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "messages": [{"role": "user", "content": prompt}]},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BobProviderError(f"OpenRouter request failed: {exc}") from exc

        data = response.json()
        try:
            content: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise BobProviderError(f"OpenRouter response missing expected fields: {data}") from exc
        return content
