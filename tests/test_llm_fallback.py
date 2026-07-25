import pytest

from src.chat.llm import FallbackLlmClient, LlmClient, LlmResponse


class _Fails(LlmClient):
    provider_name = "fails"

    def complete(self, system, user, max_tokens=1024):
        raise RuntimeError("simulated provider failure")


class _Works(LlmClient):
    provider_name = "works"

    def complete(self, system, user, max_tokens=1024):
        return LlmResponse(text="ok", model="fake-model", input_tokens=1, output_tokens=1, provider=self.provider_name)


def test_fallback_moves_to_next_provider_on_failure():
    chain = FallbackLlmClient([_Fails(), _Works()])
    resp = chain.complete("sys", "user")
    assert resp.provider == "works"
    assert resp.text == "ok"


def test_fallback_raises_when_all_providers_fail():
    chain = FallbackLlmClient([_Fails(), _Fails()])
    with pytest.raises(RuntimeError):
        chain.complete("sys", "user")


def test_fallback_requires_at_least_one_client():
    with pytest.raises(ValueError):
        FallbackLlmClient([])
