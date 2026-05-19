"""Shared LLM factory for CrewAI agents.

CrewAI delegates model calls to LiteLLM under the hood, so any LiteLLM-supported
provider can be used by passing the provider-prefixed model string (e.g.,
``gemini/gemini-2.5-flash`` or ``cerebras/llama3.1-8b``) together with the
matching API key.

Provider selection is driven by ``LLM_PROVIDER`` in the environment / ``.env``:

* ``gemini``   (default) \u2192 Google AI Studio, free tier, model ``gemini-2.5-flash``.
* ``cerebras``           \u2192 Cerebras Cloud, free tier, model ``llama3.1-8b``
                           by default (sub-second responses on the wafer-scale
                           inference chips). Override with ``LLM_MODEL`` to use
                           ``cerebras/gpt-oss-120b`` or any other Cerebras model.

The factory is the single source of truth, so every agent shares one consistent
LLM instance \u2014 swapping providers is a pure env-var change.
"""

from crewai import LLM

from web3_crew.config import settings

# Default LiteLLM model identifier per provider when ``LLM_MODEL`` is empty.
# Picks intentionally favour speed + free-tier availability over peak quality.
_DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini/gemini-2.5-flash",
    # Cerebras production models as of mid-2026: ``llama3.1-8b`` and
    # ``gpt-oss-120b``. ``llama3.1-8b`` produces plain completions (no internal
    # reasoning tokens), which is the safest default for a chat / tool-using
    # agent. Users wanting stronger quality can flip to ``cerebras/gpt-oss-120b``
    # via ``LLM_MODEL``.
    "cerebras": "cerebras/llama3.1-8b",
}

# Name of the settings field holding the API key for each provider.
_API_KEY_FIELDS: dict[str, str] = {
    "gemini": "gemini_api_key",
    "cerebras": "cerebras_api_key",
}


def _resolve_provider() -> str:
    provider = (settings.llm_provider or "gemini").strip().lower()
    if provider not in _DEFAULT_MODELS:
        supported = ", ".join(sorted(_DEFAULT_MODELS))
        raise ValueError(
            f"Unsupported LLM_PROVIDER={settings.llm_provider!r}. "
            f"Supported providers: {supported}."
        )
    return provider


def _resolve_model(provider: str) -> str:
    if settings.llm_model:
        return settings.llm_model
    return _DEFAULT_MODELS[provider]


def _resolve_api_key(provider: str) -> str:
    field = _API_KEY_FIELDS[provider]
    api_key = getattr(settings, field, "")
    if not api_key:
        env_name = field.upper()
        raise ValueError(
            f"LLM_PROVIDER={provider!r} requires {env_name} to be set in the "
            f"environment / .env. Add it and retry."
        )
    return api_key


def create_llm() -> LLM:
    """Return a CrewAI ``LLM`` configured for the active provider.

    Reads :mod:`web3_crew.config.settings` for provider, model, API key, and
    temperature. Raises :class:`ValueError` with an actionable message when the
    provider is unknown or the matching API key is missing.
    """
    provider = _resolve_provider()
    model = _resolve_model(provider)
    api_key = _resolve_api_key(provider)
    return LLM(
        model=model,
        api_key=api_key,
        temperature=settings.llm_temperature,
        # Route through LiteLLM rather than CrewAI's native provider SDKs, so no
        # extra dependencies (``google-genai``, ``cerebras-cloud-sdk``, ...) are
        # required.
        is_litellm=True,
    )
