# Workflow RL Summary

## Compared Methods

always_direct, always_decompose, heuristic_threshold, contextual_bandit, double_dqn, dueling_double_dqn

## Main Metrics

              agent  success_rate  avg_reward  avg_prompt_tokens  avg_completion_tokens  avg_steps  avg_total_tokens
   always_decompose          0.00   -6.960000            14400.0                 4800.0      24.00           19200.0
      always_direct          0.00   -7.180000            28800.0                24000.0      24.00           52800.0
  contextual_bandit          0.56    7.949074            12168.0                 8758.0      14.68           20926.0
         double_dqn          0.04  -10.542662             5728.0                 3744.0       7.12            9472.0
 dueling_double_dqn          0.16   -6.941564             6920.0                 4770.0       8.32           11690.0
heuristic_threshold          0.72   11.033820            12004.0                 9490.0      15.24           21494.0

## Ablation Metrics

               scenario  success_rate  avg_reward  avg_prompt_tokens  avg_completion_tokens  avg_steps  avg_total_tokens
      no_action_masking           0.0  -15.344696             5590.0                 3955.0        7.9            9545.0
      no_budget_penalty           0.0  -13.480451             6290.0                 3955.0        7.9           10245.0
  no_deep_decomposition           0.0  -11.434783             4700.0                 3230.0        5.7            7930.0
    no_retrieval_action           0.1  -10.825221             4760.0                 3380.0        6.0            8140.0
no_uncertainty_features           0.0  -11.857601             4670.0                 3105.0        5.9            7775.0
     no_verifier_action           0.0  -11.744472             2780.0                 1680.0        3.8            4460.0

**Best raw success:** heuristic_threshold

**Best fixed-budget success:** heuristic_threshold

## Failure Modes

SOLVING: 29, PLANNING: 32, ABANDONED: 51, FINAL_REVIEW: 1