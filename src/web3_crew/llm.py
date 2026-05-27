"""Shared LLM factory for CrewAI agents.

CrewAI delegates model calls to LiteLLM under the hood, so any LiteLLM-supported
provider can be used by passing the provider-prefixed model string (e.g.,
``gemini/gemini-2.5-flash``, ``cerebras/llama3.1-8b``, or ``openai/Qwen/Qwen2-72B-Instruct``) 
together with the matching API key.

Provider selection is driven by ``LLM_PROVIDER`` in the environment / ``.env``:

* ``gemini``   (default) -> Google AI Studio, free tier, model ``gemini-2.5-flash``.
* ``cerebras``           -> Cerebras Cloud, free tier, model ``llama3.1-8b``.
* ``openai``             -> Custom vLLM / OpenAI compatible endpoint.
"""

import os
from crewai import LLM
from web3_crew.config import settings

# Default LiteLLM model identifier per provider when ``LLM_MODEL`` is empty.
_DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini/gemini-2.5-flash",
    "cerebras": "cerebras/llama3.1-8b",
    "openai": "openai/Qwen/Qwen2-72B-Instruct",
}

# Name of the environment variable holding the API key for each provider.
_API_KEY_FIELDS: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "openai": "OPENAI_API_KEY",
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
    env_name = _API_KEY_FIELDS[provider]
    # Check settings first (for backward compatibility), fallback to os.getenv
    api_key = getattr(settings, env_name.lower(), None) or os.getenv(env_name, "")
    
    if not api_key:
        raise ValueError(
            f"LLM_PROVIDER={provider!r} requires {env_name} to be set in the "
            f"environment / .env. Add it and retry."
        )
    return api_key


def create_llm() -> LLM:
    """Return a CrewAI ``LLM`` configured for the active provider.

    Reads provider, model, API key, and temperature. Raises ValueError 
    with an actionable message when the provider is unknown or key is missing.
    """
    provider = _resolve_provider()
    model = _resolve_model(provider)
    api_key = _resolve_api_key(provider)
    
    # Inject OPENAI_API_BASE dynamically for custom vLLM endpoints
    base_url = os.getenv("OPENAI_API_BASE") if provider == "openai" else None

    return LLM(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=settings.llm_temperature,
        # Route through LiteLLM rather than CrewAI's native provider SDKs
        is_litellm=True,
    )