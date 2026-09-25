"""GeminiProvider: BobProvider backed by the Gemini API free tier (primary provider — see
docs/DECISIONS.md ADR-004).

Endpoint, auth, and request/response shape verified against
https://ai.google.dev/api/generate-content on 2026-09-26. `_DEFAULT_MODEL` reflects the
model that documentation page recommended on that date — Gemini's flash-tier model naming
has moved before and will again, so treat this default as a convenience, not a guarantee;
override via the `model` constructor argument if it stops working.
"""

from __future__ import annotations

import httpx

from repoflare_core.ai.provider import BobProviderError

_DEFAULT_MODEL = "gemini-3.8-flash"
_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_TIMEOUT_SECONDS = 30.0


class GeminiProvider:
    def __init__(
        self, api_key: str, model: str = _DEFAULT_MODEL, client: httpx.Client | None = None
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=_TIMEOUT_SECONDS)

    def complete(self, prompt: str) -> str:
        try:
            response = self._client.post(
                _ENDPOINT_TEMPLATE.format(model=self._model),
                params={"key": self._api_key},
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BobProviderError(f"Gemini request failed: {exc}") from exc

        data = response.json()
        try:
            text: str = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise BobProviderError(f"Gemini response missing expected fields: {data}") from exc
        return text
