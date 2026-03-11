"""Model/strategy matrix helpers for real evaluation sweeps."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ModelStrategy:
    """Pairing of an LLM provider/model with a decomposition strategy."""

    label: str
    strategy_name: str
    provider: str
    model: str
    temperature: float = 0.2
    max_calls: Optional[int] = None
    max_tokens: Optional[int] = None


def build_matrix(
    strategies: Sequence[str],
    *,
    provider: str,
    model: str,
    temperature: float = 0.2,
) -> List[ModelStrategy]:
    entries: List[ModelStrategy] = []
    for strategy in strategies:
        entries.append(
            ModelStrategy(
                label=f"{strategy}:{model}",
                strategy_name=strategy,
                provider=provider,
                model=model,
                temperature=temperature,
            )
        )
    return entries


def default_matrix(strategies: Sequence[str] | None = None) -> List[ModelStrategy]:
    return build_matrix(
        strategies or ["contract_first"],
        provider="default",
        model="mock-model",
    )
