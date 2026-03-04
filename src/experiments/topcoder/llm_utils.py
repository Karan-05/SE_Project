"""Helpers to detect LLM availability for experiment guardrails."""
from __future__ import annotations

import os
from typing import Tuple

TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in TRUE_VALUES


def _provider_credentials_present(provider: str) -> Tuple[bool, str]:
    lower = provider.lower()
    if lower == "openai":
        if os.getenv("OPENAI_API_KEY"):
            return True, "env:OPENAI_API_KEY"
        return False, "missing_config"
    if lower == "azure_openai":
        required = ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"]
        if all(os.getenv(name) for name in required):
            return True, "env:AZURE_OPENAI_API_KEY"
        return False, "missing_config"
    if lower == "anthropic":
        if os.getenv("ANTHROPIC_API_KEY"):
            return True, "env:ANTHROPIC_API_KEY"
        return False, "missing_config"
    if lower == "mock":
        explicit = _env_truthy("DECOMP_LLM_EXPLICIT", "0") or _env_truthy("DECOMP_MOCK_MODE", "0")
        if explicit:
            return True, "mock"
        return False, "missing_config"
    return False, "unsupported_provider"


def llm_available() -> Tuple[bool, str]:
    """Return whether an LLM provider (mock or real) is configured."""

    if _env_truthy("DECOMP_DISABLE_LLM", "0"):
        return False, "disabled_via_env"
    provider = os.getenv("DECOMP_LLM_PROVIDER") or os.getenv("LLM_PROVIDER") or ""
    if not provider:
        provider = "mock"
    available, reason = _provider_credentials_present(provider)
    return available, reason


__all__ = ["llm_available"]
