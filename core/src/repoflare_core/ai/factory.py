"""default_bob_provider: builds the configured BobProvider fallback chain from environment
variables (see .env.example at the repo root for the expected names).

Kept separate from provider.py/fallback.py so those stay pure and independently testable
without touching os.environ — this is the one place environment-variable wiring happens.
"""

from __future__ import annotations

import os

from repoflare_core.ai.fallback import FallbackBobProvider
from repoflare_core.ai.gemini import GeminiProvider
from repoflare_core.ai.openrouter import OpenRouterProvider
from repoflare_core.ai.provider import BobProvider


class BobProviderConfigError(RuntimeError):
    """Raised when no usable provider can be configured from the environment."""


def default_bob_provider() -> BobProvider:
    """Gemini primary, OpenRouter fallback — see docs/DECISIONS.md ADR-004. Either or both
    may be configured; at least one is required."""
    providers: list[BobProvider] = []

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        providers.append(GeminiProvider(api_key=gemini_key))

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    openrouter_model = os.environ.get("OPENROUTER_MODEL")
    if openrouter_key and openrouter_model:
        providers.append(OpenRouterProvider(api_key=openrouter_key, model=openrouter_model))

    if not providers:
        raise BobProviderConfigError(
            "No AI provider configured — set GEMINI_API_KEY, or both OPENROUTER_API_KEY "
            "and OPENROUTER_MODEL, in your environment (see .env.example)."
        )
    return FallbackBobProvider(providers)
