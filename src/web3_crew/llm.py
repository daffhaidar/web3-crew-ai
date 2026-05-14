"""Shared LLM factory for CrewAI agents.

CrewAI delegates model calls to LiteLLM under the hood, so any LiteLLM-supported
provider can be used by passing the provider-prefixed model string (e.g.,
``gemini/gemini-1.5-pro``) together with the matching API key.

This project targets Google Gemini (``gemini-2.5-pro``) and reads its
configuration from ``web3_crew.config.settings`` so every agent shares a single,
consistent LLM instance.
"""

from crewai import LLM

from web3_crew.config import settings


def create_llm() -> LLM:
    """Return a CrewAI ``LLM`` configured for Google Gemini via LiteLLM.

    The model identifier and API key are read from :mod:`web3_crew.config.settings`,
    which loads them from environment variables / ``.env``. Defaults to
    ``gemini/gemini-2.5-pro``.
    """
    return LLM(
        model=settings.llm_model,
        api_key=settings.gemini_api_key,
        temperature=settings.llm_temperature,
        # Route through LiteLLM rather than CrewAI's native Google Gen AI SDK
        # provider, so no extra dependencies (e.g. ``google-genai``) are needed.
        is_litellm=True,
    )
