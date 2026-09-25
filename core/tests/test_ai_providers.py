from typing import Any

import httpx
import pytest

from repoflare_core.ai.fallback import FallbackBobProvider
from repoflare_core.ai.gemini import GeminiProvider
from repoflare_core.ai.openrouter import NotAFreeModelError, OpenRouterProvider
from repoflare_core.ai.provider import BobProviderError


def _client_returning(json_body: dict[str, Any], status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_raising_transport_error() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


class _StubProvider:
    def __init__(self, result: str | None = None, error: str | None = None) -> None:
        self._result = result
        self._error = error

    def complete(self, prompt: str) -> str:
        if self._error is not None:
            raise BobProviderError(self._error)
        assert self._result is not None
        return self._result


# -- GeminiProvider -----------------------------------------------------------------


def test_gemini_extracts_text_from_response() -> None:
    client = _client_returning(
        {"candidates": [{"content": {"parts": [{"text": "hello from gemini"}]}}]}
    )
    provider = GeminiProvider(api_key="k", client=client)

    assert provider.complete("hi") == "hello from gemini"


def test_gemini_raises_on_http_error() -> None:
    client = _client_returning({"error": "bad"}, status_code=500)
    provider = GeminiProvider(api_key="k", client=client)

    with pytest.raises(BobProviderError):
        provider.complete("hi")


def test_gemini_raises_on_malformed_response() -> None:
    client = _client_returning({"unexpected": "shape"})
    provider = GeminiProvider(api_key="k", client=client)

    with pytest.raises(BobProviderError):
        provider.complete("hi")


def test_gemini_raises_on_transport_error() -> None:
    provider = GeminiProvider(api_key="k", client=_client_raising_transport_error())

    with pytest.raises(BobProviderError):
        provider.complete("hi")


# -- OpenRouterProvider -------------------------------------------------------------


def test_openrouter_defaults_to_free_router_model() -> None:
    provider = OpenRouterProvider(api_key="k", client=_client_returning({}))

    assert provider._model == "openrouter/free"  # noqa: SLF001


def test_openrouter_rejects_non_free_model() -> None:
    with pytest.raises(NotAFreeModelError):
        OpenRouterProvider(api_key="k", model="openai/gpt-5")


def test_openrouter_accepts_free_suffixed_model() -> None:
    # must not raise
    OpenRouterProvider(api_key="k", model="some/model:free", client=_client_returning({}))


def test_openrouter_extracts_content_from_response() -> None:
    client = _client_returning({"choices": [{"message": {"content": "hello from openrouter"}}]})
    provider = OpenRouterProvider(api_key="k", model="some/model:free", client=client)

    assert provider.complete("hi") == "hello from openrouter"


def test_openrouter_raises_on_http_error() -> None:
    client = _client_returning({"error": "bad"}, status_code=429)
    provider = OpenRouterProvider(api_key="k", model="some/model:free", client=client)

    with pytest.raises(BobProviderError):
        provider.complete("hi")


def test_openrouter_raises_on_malformed_response() -> None:
    client = _client_returning({"unexpected": "shape"})
    provider = OpenRouterProvider(api_key="k", model="some/model:free", client=client)

    with pytest.raises(BobProviderError):
        provider.complete("hi")


# -- FallbackBobProvider --------------------------------------------------------------


def test_fallback_uses_first_provider_when_it_succeeds() -> None:
    primary = _StubProvider(result="primary answer")
    secondary = _StubProvider(result="secondary answer")

    result = FallbackBobProvider([primary, secondary]).complete("hi")

    assert result == "primary answer"


def test_fallback_falls_through_to_second_provider_on_failure() -> None:
    primary = _StubProvider(error="primary down")
    secondary = _StubProvider(result="secondary answer")

    result = FallbackBobProvider([primary, secondary]).complete("hi")

    assert result == "secondary answer"


def test_fallback_raises_last_error_when_all_providers_fail() -> None:
    primary = _StubProvider(error="primary down")
    secondary = _StubProvider(error="secondary down too")

    with pytest.raises(BobProviderError, match="secondary down too"):
        FallbackBobProvider([primary, secondary]).complete("hi")


def test_fallback_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FallbackBobProvider([])
