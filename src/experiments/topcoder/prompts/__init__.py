"""Prompt utilities shared across Universal Topcoder agents."""

from .universal_agent import (
    ArtifactRequest,
    STRICT_JSON_CONTRACT,
    UNIVERSAL_AGENT_PROMPT,
    build_universal_agent_prompt,
    parse_universal_agent_response,
)

__all__ = [
    "ArtifactRequest",
    "STRICT_JSON_CONTRACT",
    "UNIVERSAL_AGENT_PROMPT",
    "build_universal_agent_prompt",
    "parse_universal_agent_response",
]
