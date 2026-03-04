# decomposition.runners.run_rl_integration

_Summary_: Integrate decomposition strategies with hardened RL environments.

## Classes
### StrategyAwareAgent
No class docstring.

Methods:
- `act(env, observation)` — 
- `_ctx_from_meta(meta)` — 

### MetaStrategyAgent
No class docstring.

Methods:
- `__init__(strategy_weights)` — 
- `act(env, observation)` — 

## Functions
- `_load_env_config(config_path, horizon)` — 
- `rollout_agent(env, agent, episodes, base_seed)` — 
- `load_strategy_weights(report)` — 
- `run_rl_decomposition(seed, episodes, horizon, config_path)` — 
- `parse_args()` — 
- `main()` —
