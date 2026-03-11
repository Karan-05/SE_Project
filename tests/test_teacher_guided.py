from __future__ import annotations

import numpy as np

from src.rl.teacher_guided import OverrideClassifier, map_action_to_macro
from src.rl.aegis_state import AegisMacroOption
from src.rl.workflow_env import WorkflowAction


def test_map_action_to_macro_respects_allowed() -> None:
    macro = map_action_to_macro(WorkflowAction.RUN_TESTS, [AegisMacroOption.VERIFY, AegisMacroOption.REPAIR])
    assert macro == AegisMacroOption.VERIFY


def test_override_classifier_trains() -> None:
    clf = OverrideClassifier(feature_dim=4, lr=0.1)
    x = np.array([1.0, 0.5, -0.2, 0.1], dtype=np.float32)
    before = clf.predict(x)
    clf.update(x, 1.0)
    after = clf.predict(x)
    assert after > before
