"""OpenRouterProvider: BobProvider fallback backed by an OpenRouter free-tier model (see
docs/DECISIONS.md ADR-004).

Endpoint and OpenAI-compatible chat-completions schema verified against
https://openrouter.ai/docs/quickstart on 2026-09-26.

Default model is `openrouter/free` — OpenRouter's official Free Models Router (released
2026-02-01, verified via https://openrouter.ai/docs/guides/routing/routers/free-router):
it always routes to a $0-cost model internally, so it can't silently start hitting a paid
model even as individual free models rotate in and out. A specific `provider/model:free`
id may still be passed instead, but the constructor hard-rejects anything that isn't
`openrouter/free` or doesn't end in `:free` — this project must only ever call free-tier
OpenRouter models, no exceptions.
"""

from __future__ import annotations

import httpx

from repoflare_core.ai.provider import BobProviderError

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT_SECONDS = 30.0
_DEFAULT_MODEL = "openrouter/free"
_FREE_ROUTER_MODEL = "openrouter/free"
_FREE_SUFFIX = ":free"


class NotAFreeModelError(ValueError):
    """Raised when a non-free OpenRouter model id is passed — this project must only ever
    call free-tier models."""


class OpenRouterProvider:
    def __init__(
        self, api_key: str, model: str = _DEFAULT_MODEL, client: httpx.Client | None = None
    ) -> None:
        if model != _FREE_ROUTER_MODEL and not model.endswith(_FREE_SUFFIX):
            raise NotAFreeModelError(
                f"{model!r} is not a free-tier OpenRouter model id — must be "
                f"{_FREE_ROUTER_MODEL!r} or end with {_FREE_SUFFIX!r}"
            )
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
