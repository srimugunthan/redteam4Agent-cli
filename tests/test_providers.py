"""Unit tests for agentrt.providers — no real API calls, no network."""

from __future__ import annotations

import builtins
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_anthropic_response(text: str):
    """Build a mock Anthropic messages response object."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def make_openai_response(text: str):
    """Build a mock OpenAI chat completions response object."""
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def make_httpx_response(payload: dict):
    """Build a mock httpx.Response that returns *payload* from .json()."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _make_anthropic_provider(model: str = "claude-haiku-4-5", **kwargs):
    """Return an AnthropicProvider with a mocked AsyncAnthropic client.

    The mock client is returned alongside the provider for assertion purposes.
    """
    mock_client = MagicMock()
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.AsyncAnthropic.return_value = mock_client
    with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
        from agentrt.providers.anthropic import AnthropicProvider
        provider = AnthropicProvider(model, **kwargs)
    return provider, mock_client


def _make_openai_provider(model: str = "gpt-4o", **kwargs):
    """Return an OpenAIProvider with a mocked AsyncOpenAI client."""
    mock_client = MagicMock()
    mock_openai_module = MagicMock()
    mock_openai_module.AsyncOpenAI.return_value = mock_client
    with patch.dict(sys.modules, {"openai": mock_openai_module}):
        from agentrt.providers.openai import OpenAIProvider
        provider = OpenAIProvider(model, **kwargs)
    return provider, mock_client


# ===========================================================================
# AnthropicProvider tests
# ===========================================================================


class TestAnthropicProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_text(self):
        provider, mock_client = _make_anthropic_provider()
        mock_client.messages.create = AsyncMock(
            return_value=make_anthropic_response("Hello, world!")
        )

        result = await provider.complete("Say hello")

        assert result == "Hello, world!"
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_passes_system_prompt(self):
        provider, mock_client = _make_anthropic_provider()
        mock_client.messages.create = AsyncMock(return_value=make_anthropic_response("ok"))

        await provider.complete("prompt", system="You are a bot.")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs.get("system") == "You are a bot."

    @pytest.mark.asyncio
    async def test_complete_no_system_omits_key(self):
        """When system is empty, the 'system' key should NOT be included in the call."""
        provider, mock_client = _make_anthropic_provider()
        mock_client.messages.create = AsyncMock(return_value=make_anthropic_response("ok"))

        await provider.complete("prompt")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    @pytest.mark.asyncio
    async def test_complete_structured_valid_json(self):
        payload = {"name": "Alice", "age": 30}
        provider, mock_client = _make_anthropic_provider()
        mock_client.messages.create = AsyncMock(
            return_value=make_anthropic_response(json.dumps(payload))
        )

        result = await provider.complete_structured("Give me a person", schema={"type": "object"})

        assert result == payload

    @pytest.mark.asyncio
    async def test_complete_structured_fallback_on_bad_json(self):
        bad_text = "This is not JSON at all."
        provider, mock_client = _make_anthropic_provider()
        mock_client.messages.create = AsyncMock(
            return_value=make_anthropic_response(bad_text)
        )

        result = await provider.complete_structured("Give me data", schema={})

        assert result == {"raw": bad_text}


# ===========================================================================
# OpenAIProvider tests
# ===========================================================================


class TestOpenAIProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_text(self):
        provider, mock_client = _make_openai_provider(api_key="sk-test")
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_openai_response("GPT says hi")
        )

        result = await provider.complete("Say hi")

        assert result == "GPT says hi"
        mock_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_passes_system_prompt(self):
        provider, mock_client = _make_openai_provider()
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_openai_response("ok")
        )

        await provider.complete("prompt", system="Be helpful.")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "Be helpful."}
        assert messages[1] == {"role": "user", "content": "prompt"}

    @pytest.mark.asyncio
    async def test_complete_structured_valid_json(self):
        payload = {"result": 42}
        provider, mock_client = _make_openai_provider()
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_openai_response(json.dumps(payload))
        )

        result = await provider.complete_structured("Give me a number", schema={})

        assert result == payload

    @pytest.mark.asyncio
    async def test_complete_structured_fallback_on_bad_json(self):
        bad_text = "not json"
        provider, mock_client = _make_openai_provider()
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_openai_response(bad_text)
        )

        result = await provider.complete_structured("Give me data", schema={})

        assert result == {"raw": bad_text}

    def test_raises_import_error_when_openai_not_installed(self):
        """OpenAIProvider.__init__ should raise ImportError if openai is absent."""
        # Ensure the provider module is loaded so we can import the class.
        import agentrt.providers.openai  # noqa: F401

        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return real_import(name, *args, **kwargs)

        # Remove the real openai from sys.modules so the lazy import has to look it up
        saved_openai = sys.modules.pop("openai", None)
        try:
            with patch("builtins.__import__", side_effect=blocked_import):
                from agentrt.providers.openai import OpenAIProvider
                with pytest.raises(ImportError, match="openai"):
                    OpenAIProvider("gpt-4o")
        finally:
            if saved_openai is not None:
                sys.modules["openai"] = saved_openai


# ===========================================================================
# OllamaProvider tests
# ===========================================================================


def _make_ollama_mock_client(response_payload: dict):
    """Return (mock_async_client_cm, mock_post) for patching httpx.AsyncClient."""
    mock_resp = make_httpx_response(response_payload)
    mock_post = AsyncMock(return_value=mock_resp)

    mock_client_instance = MagicMock()
    mock_client_instance.post = mock_post
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    mock_async_client_cls = MagicMock(return_value=mock_client_instance)
    return mock_async_client_cls, mock_post


class TestOllamaProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_response_field(self):
        from agentrt.providers.ollama import OllamaProvider

        mock_cls, mock_post = _make_ollama_mock_client({"response": "Ollama says hello"})

        with patch("httpx.AsyncClient", mock_cls):
            provider = OllamaProvider("llama3")
            result = await provider.complete("Say hello")

        assert result == "Ollama says hello"
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_sends_correct_body(self):
        from agentrt.providers.ollama import OllamaProvider

        mock_cls, mock_post = _make_ollama_mock_client({"response": "ok"})

        with patch("httpx.AsyncClient", mock_cls):
            provider = OllamaProvider("llama3", base_url="http://localhost:11434")
            await provider.complete("test prompt")

        call_kwargs = mock_post.call_args
        # positional arg[0] is the URL
        url = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("url", "")
        body = call_kwargs.kwargs.get("json", {})
        assert "api/generate" in url
        assert body["model"] == "llama3"
        assert body["prompt"] == "test prompt"
        assert body["stream"] is False

    @pytest.mark.asyncio
    async def test_complete_structured_valid_json(self):
        from agentrt.providers.ollama import OllamaProvider

        payload = {"answer": "yes"}
        mock_cls, _ = _make_ollama_mock_client({"response": json.dumps(payload)})

        with patch("httpx.AsyncClient", mock_cls):
            provider = OllamaProvider("llama3")
            result = await provider.complete_structured("Is it yes?", schema={})

        assert result == payload

    @pytest.mark.asyncio
    async def test_complete_structured_fallback_on_bad_json(self):
        from agentrt.providers.ollama import OllamaProvider

        bad_text = "not valid json"
        mock_cls, _ = _make_ollama_mock_client({"response": bad_text})

        with patch("httpx.AsyncClient", mock_cls):
            provider = OllamaProvider("llama3")
            result = await provider.complete_structured("What?", schema={})

        assert result == {"raw": bad_text}

    @pytest.mark.asyncio
    async def test_complete_custom_base_url(self):
        from agentrt.providers.ollama import OllamaProvider

        mock_cls, mock_post = _make_ollama_mock_client({"response": "ok"})

        with patch("httpx.AsyncClient", mock_cls):
            provider = OllamaProvider("llama3", base_url="http://myserver:9999")
            await provider.complete("hi")

        url = mock_post.call_args.args[0]
        assert url.startswith("http://myserver:9999")


# ===========================================================================
# LLMProviderFactory tests
# ===========================================================================


class TestLLMProviderFactory:
    def test_create_anthropic(self):
        mock_anthropic_module = MagicMock()
        mock_anthropic_module.AsyncAnthropic.return_value = MagicMock()
        with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
            from agentrt.providers.factory import LLMProviderFactory
            from agentrt.providers.anthropic import AnthropicProvider
            provider = LLMProviderFactory.create("anthropic", "claude-haiku-4-5")
        assert isinstance(provider, AnthropicProvider)

    def test_create_openai(self):
        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI.return_value = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai_module}):
            from agentrt.providers.factory import LLMProviderFactory
            from agentrt.providers.openai import OpenAIProvider
            provider = LLMProviderFactory.create("openai", "gpt-4o")
        assert isinstance(provider, OpenAIProvider)

    def test_create_ollama(self):
        from agentrt.providers.factory import LLMProviderFactory
        from agentrt.providers.ollama import OllamaProvider
        provider = LLMProviderFactory.create("ollama", "llama3")
        assert isinstance(provider, OllamaProvider)

    def test_create_unknown_raises_value_error(self):
        from agentrt.providers.factory import LLMProviderFactory
        with pytest.raises(ValueError, match="Unknown provider"):
            LLMProviderFactory.create("unknown", "x")

    def test_create_unknown_error_lists_valid_providers(self):
        from agentrt.providers.factory import LLMProviderFactory
        with pytest.raises(ValueError, match="anthropic"):
            LLMProviderFactory.create("mystery", "x")


# ===========================================================================
# Protocol conformance tests
# ===========================================================================


def test_anthropic_satisfies_protocol():
    from agentrt.providers.base import LLMProvider

    provider, _ = _make_anthropic_provider("model")
    assert isinstance(provider, LLMProvider)


def test_openai_satisfies_protocol():
    from agentrt.providers.base import LLMProvider

    provider, _ = _make_openai_provider("model")
    assert isinstance(provider, LLMProvider)


def test_ollama_satisfies_protocol():
    from agentrt.providers.base import LLMProvider
    from agentrt.providers.ollama import OllamaProvider

    assert isinstance(OllamaProvider("model"), LLMProvider)
