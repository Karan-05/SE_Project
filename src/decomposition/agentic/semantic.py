"""Semantic prompt/repair configuration for real-repo strategies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class SemanticVariantConfig:
    """Bundle of semantic features to toggle per strategy variant."""

    name: str
    require_checklist: bool = False
    enable_repair_critic: bool = False
    schema_reminders: bool = False
    require_skip_rationale: bool = True
    emphasize_contract: bool = True
    highlight_support_policy: bool = True
    require_semantic_summary: bool = True


BASELINE = SemanticVariantConfig(
    name="baseline",
    require_checklist=False,
    enable_repair_critic=False,
    schema_reminders=False,
    require_skip_rationale=False,
    emphasize_contract=True,
    highlight_support_policy=True,
    require_semantic_summary=False,
)

CHECKLIST = SemanticVariantConfig(
    name="checklist",
    require_checklist=True,
    enable_repair_critic=False,
    schema_reminders=False,
)

CRITIC = SemanticVariantConfig(
    name="critic",
    require_checklist=True,
    enable_repair_critic=True,
    schema_reminders=False,
)

FULL = SemanticVariantConfig(
    name="semantic_full",
    require_checklist=True,
    enable_repair_critic=True,
    schema_reminders=True,
)


VARIANT_BY_STRATEGY: Dict[str, SemanticVariantConfig] = {
    "contract_first": FULL,
    "contract_first_semantic": FULL,
    "contract_first_checklist": CHECKLIST,
    "contract_first_baseline": BASELINE,
    "failure_mode_first": FULL,
    "failure_mode_first_semantic": FULL,
    "failure_mode_first_baseline": BASELINE,
    "failure_mode_first_checklist": CHECKLIST,
    "contract_first_critic": CRITIC,
    "failure_mode_first_critic": CRITIC,
}


def get_semantic_config(strategy_name: str) -> SemanticVariantConfig:
    """Return the semantic configuration for the requested strategy."""

    return VARIANT_BY_STRATEGY.get(strategy_name, FULL)


__all__ = ["SemanticVariantConfig", "get_semantic_config"]
