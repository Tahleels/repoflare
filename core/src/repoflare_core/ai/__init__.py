"""BobProvider: the interface RepoFlare's semantic-reasoning layer is built against, plus
concrete free-tier implementations and a fallback chain. See docs/DECISIONS.md ADR-004."""

from repoflare_core.ai.factory import BobProviderConfigError, default_bob_provider
from repoflare_core.ai.fallback import FallbackBobProvider
from repoflare_core.ai.gemini import GeminiProvider
from repoflare_core.ai.openrouter import OpenRouterProvider
from repoflare_core.ai.provider import BobProvider, BobProviderError

__all__ = [
    "BobProvider",
    "BobProviderConfigError",
    "BobProviderError",
    "FallbackBobProvider",
    "GeminiProvider",
    "OpenRouterProvider",
    "default_bob_provider",
]
