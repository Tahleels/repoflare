import pytest

from repoflare_core.ai.factory import BobProviderConfigError, default_bob_provider
from repoflare_core.ai.fallback import FallbackBobProvider
from repoflare_core.ai.gemini import GeminiProvider
from repoflare_core.ai.openrouter import OpenRouterProvider


def _clear_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_raises_when_nothing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_env(monkeypatch)

    with pytest.raises(BobProviderConfigError):
        default_bob_provider()


def test_gemini_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")

    provider = default_bob_provider()

    assert isinstance(provider, FallbackBobProvider)
    assert isinstance(provider._providers[0], GeminiProvider)  # noqa: SLF001
    assert len(provider._providers) == 1  # noqa: SLF001


def test_openrouter_key_alone_defaults_to_free_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENROUTER_MODEL is optional — omitting it must fall back to openrouter/free, not error."""
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    provider = default_bob_provider()

    assert isinstance(provider, FallbackBobProvider)
    only_provider = provider._providers[0]  # noqa: SLF001
    assert isinstance(only_provider, OpenRouterProvider)
    assert only_provider._model == "openrouter/free"  # noqa: SLF001


def test_both_configured_gemini_is_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "some/model:free")

    provider = default_bob_provider()

    assert isinstance(provider, FallbackBobProvider)
    assert isinstance(provider._providers[0], GeminiProvider)  # noqa: SLF001
    assert isinstance(provider._providers[1], OpenRouterProvider)  # noqa: SLF001
