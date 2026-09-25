"""FallbackBobProvider: tries providers in order, falling back on BobProviderError.

Implements the "graceful fallback chain" from docs/DECISIONS.md ADR-004 (Gemini primary,
OpenRouter fallback). Raises the last provider's BobProviderError only if every provider in
the chain fails — never swallows the failure silently.
"""

from __future__ import annotations

from repoflare_core.ai.provider import BobProvider, BobProviderError


class FallbackBobProvider:
    def __init__(self, providers: list[BobProvider]) -> None:
        if not providers:
            raise ValueError("FallbackBobProvider requires at least one provider")
        self._providers = providers

    def complete(self, prompt: str) -> str:
        last_error: BobProviderError | None = None
        for provider in self._providers:
            try:
                return provider.complete(prompt)
            except BobProviderError as exc:
                last_error = exc
        assert last_error is not None  # unreachable: __init__ guarantees at least one provider
        raise last_error
