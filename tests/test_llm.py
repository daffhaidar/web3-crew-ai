"""Unit tests for the multi-provider LLM factory.

These tests pin the contract that swapping providers is a pure env-var change,
and that missing or invalid configuration fails fast with an actionable message
instead of a downstream 401 / KeyError at call time.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from web3_crew import llm as llm_module


def _fake_settings(**overrides):
    """Build a minimal stand-in for :data:`web3_crew.config.settings`.

    The real ``Settings`` object exposes many fields; the LLM factory only
    reads a handful, so a ``SimpleNamespace`` keeps tests independent of
    unrelated fields and avoids triggering pydantic validation when
    individual fields are intentionally invalid.
    """
    defaults = {
        "llm_provider": "gemini",
        "gemini_api_key": "test-gemini-key",
        "cerebras_api_key": "",
        "llm_model": "",
        "llm_temperature": 0.2,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestProviderResolution:
    """``_resolve_provider`` normalises case / whitespace and rejects unknowns."""

    def test_default_provider_is_gemini(self, monkeypatch):
        monkeypatch.setattr(llm_module, "settings", _fake_settings())
        assert llm_module._resolve_provider() == "gemini"

    def test_provider_is_lowercased(self, monkeypatch):
        monkeypatch.setattr(
            llm_module, "settings", _fake_settings(llm_provider="CEREBRAS")
        )
        assert llm_module._resolve_provider() == "cerebras"

    def test_provider_whitespace_is_stripped(self, monkeypatch):
        monkeypatch.setattr(
            llm_module, "settings", _fake_settings(llm_provider="  gemini  ")
        )
        assert llm_module._resolve_provider() == "gemini"

    def test_empty_provider_falls_back_to_gemini(self, monkeypatch):
        monkeypatch.setattr(
            llm_module, "settings", _fake_settings(llm_provider="")
        )
        assert llm_module._resolve_provider() == "gemini"

    def test_unknown_provider_raises_with_supported_list(self, monkeypatch):
        monkeypatch.setattr(
            llm_module, "settings", _fake_settings(llm_provider="anthropic")
        )
        with pytest.raises(ValueError) as exc:
            llm_module._resolve_provider()
        msg = str(exc.value)
        assert "anthropic" in msg
        # Error message must enumerate supported providers so the user can fix
        # their config without grepping source.
        assert "gemini" in msg
        assert "cerebras" in msg


class TestModelResolution:
    """``_resolve_model`` honours explicit overrides and otherwise picks a default."""

    def test_default_gemini_model(self, monkeypatch):
        monkeypatch.setattr(llm_module, "settings", _fake_settings())
        assert llm_module._resolve_model("gemini") == "gemini/gemini-2.5-flash"

    def test_default_cerebras_model(self, monkeypatch):
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(llm_provider="cerebras", cerebras_api_key="csk-x"),
        )
        assert llm_module._resolve_model("cerebras") == "cerebras/llama3.1-8b"

    def test_explicit_model_override_wins(self, monkeypatch):
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(
                llm_provider="cerebras",
                cerebras_api_key="csk-x",
                llm_model="cerebras/gpt-oss-120b",
            ),
        )
        assert llm_module._resolve_model("cerebras") == "cerebras/gpt-oss-120b"

    def test_explicit_model_works_across_providers(self, monkeypatch):
        # The factory does not enforce provider-prefix matching on LLM_MODEL,
        # so power-users can target whatever LiteLLM understands.
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(
                llm_provider="gemini", llm_model="gemini/gemini-2.5-pro"
            ),
        )
        assert llm_module._resolve_model("gemini") == "gemini/gemini-2.5-pro"


class TestApiKeyResolution:
    """Each provider must have its own key; missing key fails fast."""

    def test_gemini_key_resolved(self, monkeypatch):
        monkeypatch.setattr(
            llm_module, "settings", _fake_settings(gemini_api_key="gk-123")
        )
        assert llm_module._resolve_api_key("gemini") == "gk-123"

    def test_cerebras_key_resolved(self, monkeypatch):
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(llm_provider="cerebras", cerebras_api_key="csk-456"),
        )
        assert llm_module._resolve_api_key("cerebras") == "csk-456"

    def test_missing_gemini_key_raises(self, monkeypatch):
        monkeypatch.setattr(
            llm_module, "settings", _fake_settings(gemini_api_key="")
        )
        with pytest.raises(ValueError) as exc:
            llm_module._resolve_api_key("gemini")
        assert "GEMINI_API_KEY" in str(exc.value)

    def test_missing_cerebras_key_raises(self, monkeypatch):
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(llm_provider="cerebras", cerebras_api_key=""),
        )
        with pytest.raises(ValueError) as exc:
            llm_module._resolve_api_key("cerebras")
        assert "CEREBRAS_API_KEY" in str(exc.value)


class TestCreateLLM:
    """End-to-end factory: builds the CrewAI ``LLM`` with the right wiring."""

    def test_create_llm_default_gemini(self, monkeypatch):
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(gemini_api_key="gk-xyz", llm_temperature=0.3),
        )
        instance = llm_module.create_llm()
        assert instance.model == "gemini/gemini-2.5-flash"
        assert instance.api_key == "gk-xyz"
        assert instance.temperature == 0.3
        assert instance.is_litellm is True

    def test_create_llm_cerebras_default_model(self, monkeypatch):
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(
                llm_provider="cerebras",
                cerebras_api_key="csk-xyz",
                gemini_api_key="",  # explicitly empty \u2014 must NOT be required
            ),
        )
        instance = llm_module.create_llm()
        assert instance.model == "cerebras/llama3.1-8b"
        assert instance.api_key == "csk-xyz"
        assert instance.is_litellm is True

    def test_create_llm_cerebras_with_override(self, monkeypatch):
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(
                llm_provider="cerebras",
                cerebras_api_key="csk-xyz",
                llm_model="cerebras/gpt-oss-120b",
            ),
        )
        instance = llm_module.create_llm()
        assert instance.model == "cerebras/gpt-oss-120b"

    def test_create_llm_missing_key_for_active_provider_raises(self, monkeypatch):
        # Cerebras is active but only the Gemini key is set \u2014 must not silently
        # fall back, must raise so the misconfig is surfaced at boot.
        monkeypatch.setattr(
            llm_module,
            "settings",
            _fake_settings(
                llm_provider="cerebras",
                gemini_api_key="gk-xyz",
                cerebras_api_key="",
            ),
        )
        with pytest.raises(ValueError, match="CEREBRAS_API_KEY"):
            llm_module.create_llm()

    def test_create_llm_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setattr(
            llm_module, "settings", _fake_settings(llm_provider="openai")
        )
        with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
            llm_module.create_llm()
