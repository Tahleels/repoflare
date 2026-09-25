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
    may be configured; at least one is required. OPENROUTER_MODEL is optional and defaults
    to OpenRouter's official `openrouter/free` router (see ai/openrouter.py) — OpenRouter
    is never used with a paid model, by construction."""
    providers: list[BobProvider] = []

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        providers.append(GeminiProvider(api_key=gemini_key))

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        openrouter_model = os.environ.get("OPENROUTER_MODEL")
        providers.append(
            OpenRouterProvider(api_key=openrouter_key, model=openrouter_model)
            if openrouter_model
            else OpenRouterProvider(api_key=openrouter_key)
        )

    if not providers:
        raise BobProviderConfigError(
            "No AI provider configured — set GEMINI_API_KEY and/or OPENROUTER_API_KEY "
            "in your environment (see .env.example)."
        )
    return FallbackBobProvider(providers)
