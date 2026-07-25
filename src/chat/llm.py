"""Provider-agnostic LLM client. Swap providers by implementing this
interface - nothing else in src/chat/ imports a provider SDK directly.

Providers implemented: Anthropic, Google Gemini (direct API or via Vertex
AI), NVIDIA NIM (OpenAI-compatible endpoint). `default_client()` builds a
fallback chain from whichever provider env vars are set, so a provider
outage/quota error doesn't take the whole chat down mid-demo.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.observability.logging import get_logger, log

logger = get_logger()


@dataclass
class LlmResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    provider: str = "unknown"


class LlmClient(ABC):
    provider_name: str = "unknown"

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LlmResponse:
        ...

    def complete_vision(self, image_bytes: bytes, prompt: str, max_tokens: int = 4096) -> LlmResponse:
        """Vision-capable completion: image + text prompt -> text response.
        Used by the scanned-PDF OCR adapter. Not every provider supports
        vision (e.g. the NIM model configured here doesn't) - those raise
        NotImplementedError, which FallbackLlmClient treats like any other
        failure and skips to the next provider in the chain."""
        raise NotImplementedError(f"{self.provider_name} does not implement complete_vision")


class AnthropicClient(LlmClient):
    provider_name = "anthropic"

    def __init__(self, model: str | None = None):
        import anthropic
        self.model = model or os.environ.get("CHAT_MODEL", "claude-sonnet-4-5")
        self._client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LlmResponse:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LlmResponse(
            text=text,
            model=self.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            provider=self.provider_name,
        )

    def complete_vision(self, image_bytes: bytes, prompt: str, max_tokens: int = 4096) -> LlmResponse:
        import base64
        b64 = base64.b64encode(image_bytes).decode()
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LlmResponse(
            text=text, model=self.model,
            input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
            provider=self.provider_name,
        )


class VertexGeminiClient(LlmClient):
    """Google Gemini via Vertex AI (google-genai SDK, vertexai=True mode).
    Requires GOOGLE_APPLICATION_CREDENTIALS (service account json) or
    application-default-login, plus VERTEX_PROJECT / VERTEX_LOCATION."""
    provider_name = "vertex_gemini"

    def __init__(self, model: str | None = None):
        from google import genai
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
        self._client = genai.Client(
            vertexai=True,
            project=os.environ.get("VERTEX_PROJECT"),
            location=os.environ.get("VERTEX_LOCATION", "us-central1"),
        )

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LlmResponse:
        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        usage = resp.usage_metadata
        return LlmResponse(
            text=resp.text or "",
            model=self.model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            provider=self.provider_name,
        )

    def complete_vision(self, image_bytes: bytes, prompt: str, max_tokens: int = 4096) -> LlmResponse:
        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        usage = resp.usage_metadata
        return LlmResponse(
            text=resp.text or "", model=self.model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            provider=self.provider_name,
        )


class GeminiClient(LlmClient):
    """Google Gemini via the direct Generative Language API (Google AI
    Studio key), not Vertex - no GCP project/service-account needed, just
    GEMINI_API_KEY. Simpler to set up than VertexGeminiClient below."""
    provider_name = "gemini_api"

    def __init__(self, model: str | None = None):
        from google import genai
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
        self._client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LlmResponse:
        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        usage = resp.usage_metadata
        return LlmResponse(
            text=resp.text or "",
            model=self.model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            provider=self.provider_name,
        )

    def complete_vision(self, image_bytes: bytes, prompt: str, max_tokens: int = 4096) -> LlmResponse:
        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        usage = resp.usage_metadata
        return LlmResponse(
            text=resp.text or "", model=self.model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            provider=self.provider_name,
        )


class NvidiaNimClient(LlmClient):
    """NVIDIA NIM - OpenAI-compatible endpoint, used here as a fallback
    provider. Requires NVIDIA_NIM_API_KEY; NVIDIA_NIM_BASE_URL defaults to
    NVIDIA's hosted NIM catalog endpoint."""
    provider_name = "nvidia_nim"

    def __init__(self, model: str | None = None):
        from openai import OpenAI
        self.model = model or os.environ.get("NIM_MODEL", "meta/llama-3.1-8b-instruct")
        self._client = OpenAI(
            base_url=os.environ.get("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            api_key=os.environ.get("NVIDIA_NIM_API_KEY"),
        )

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LlmResponse:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        choice = resp.choices[0]
        usage = resp.usage
        return LlmResponse(
            text=choice.message.content or "",
            model=self.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            provider=self.provider_name,
        )


class FallbackLlmClient(LlmClient):
    """Tries each client in order; on failure (timeout, rate limit, auth,
    quota) logs the failure and moves to the next. Raises only if every
    client in the chain fails."""
    provider_name = "fallback_chain"

    def __init__(self, clients: list[LlmClient]):
        if not clients:
            raise ValueError("FallbackLlmClient needs at least one client")
        self._clients = clients

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LlmResponse:
        last_error: Exception | None = None
        for client in self._clients:
            try:
                return client.complete(system, user, max_tokens=max_tokens)
            except Exception as e:
                last_error = e
                log(logger, "warning", f"LLM provider failed, falling back: {e}",
                    provider=client.provider_name, error=f"{type(e).__name__}: {e}")
        raise RuntimeError(f"All LLM providers in the fallback chain failed. Last error: {last_error}")

    def complete_vision(self, image_bytes: bytes, prompt: str, max_tokens: int = 4096) -> LlmResponse:
        last_error: Exception | None = None
        for client in self._clients:
            try:
                return client.complete_vision(image_bytes, prompt, max_tokens=max_tokens)
            except Exception as e:
                last_error = e
                log(logger, "warning", f"Vision-capable LLM provider failed, falling back: {e}",
                    provider=client.provider_name, error=f"{type(e).__name__}: {e}")
        raise RuntimeError(f"All LLM providers in the fallback chain failed vision OCR. Last error: {last_error}")


def default_client() -> LlmClient:
    """Builds the fallback chain from whichever provider env vars are set.
    Priority: Gemini (direct API) -> Vertex Gemini -> NVIDIA NIM -> Anthropic.
    Only providers with the required credentials present are included.
    (Direct Gemini is preferred over Vertex when both are configured since
    it needs no GCP project/service-account setup.)"""
    chain: list[LlmClient] = []

    if os.environ.get("GEMINI_API_KEY"):
        chain.append(GeminiClient())
    elif os.environ.get("VERTEX_PROJECT"):
        chain.append(VertexGeminiClient())
    if os.environ.get("NVIDIA_NIM_API_KEY"):
        chain.append(NvidiaNimClient())
    if os.environ.get("ANTHROPIC_API_KEY"):
        chain.append(AnthropicClient())

    if not chain:
        raise RuntimeError(
            "No LLM provider configured. Set GEMINI_API_KEY, VERTEX_PROJECT "
            "(+ GOOGLE_APPLICATION_CREDENTIALS), NVIDIA_NIM_API_KEY, and/or "
            "ANTHROPIC_API_KEY in .env."
        )
    if len(chain) == 1:
        return chain[0]
    return FallbackLlmClient(chain)
