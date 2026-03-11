# AEGIS-RL Empirical Triage

Date: 2026-03-06

## 1. Current Best-Performing Method
- **HeuristicThreshold baseline** is dominant: success rate ≈ **0.68**, avg reward ≈ **+9.5** (25 episodes).
- All AEGIS variants trail badly: best RL variant so far is `aegis_no_graph` with success ≈ **0.28** and reward ≈ **-7.3**.

## 2. Does AEGIS-RL beat flat workflow Double DQN?
- Barely: `aegis_full` success ≈ **0.14** vs. `baseline_dueling_dqn` ≈ **0.08**.
- Both are far below the heuristic baseline and even the contextual bandit (0.16). Hierarchy has not produced a compelling win.

## 3. Action Utilization
- Manager still leans on mid-cost actions: `direct_solve` ≈ **22%**, `decompose*` ≈ **27%**, `research_context` ≈ **11%**.
- Critical escalations under-used: `verify` ≈ **8%**, `submit` ≈ **2.6%**, `repair` ≈ **5%**, `abandon` ≈ **12%** (likely premature exits).
- Even with masking/stagnation logic, uncertainty-reducing steps are only ~1/3 of actions.

## 4. Reward Characteristics
- Average episodic rewards remain negative (e.g., `aegis_full` ≈ -17) indicating either sparse success bonuses or excessive penalties.
- Reward shaping signals (progress delta, escalation bonuses) appear too weak relative to baseline step/token costs; logging shows little differentiation for useful escalations.
- Constraint penalties are tiny (~0.08) and do not drive learning.

## 5. Is Hierarchy Worth Keeping?
- Full hierarchy (0.14 success) narrowly beats “no hierarchy” (0.12) but loses to “no graph” (0.28).
- Hierarchy currently adds complexity without tangible gains beyond flat contextual bandit.
- Unless training can be stabilized (warm-start, reduced action space, curriculum), the headline method should probably be a simplified or flat controller.
