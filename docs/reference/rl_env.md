# rl.env

_Summary_: Hardened Gymnasium environments for competitive coding marketplaces.

## Classes
### EnvConfig
No class docstring.

### TaskSlate
No class docstring.

### PendingTask
No class docstring.

### AgentState
No class docstring.

### _EnvironmentCore
No class docstring.

Methods:
- `__init__(processed_dir, rl_config, env_config)` — 
- `_determine_task_features()` — 
- `_coerce_skill_vector(raw)` — 
- `_sample_skill()` — 
- `_sample_slate()` — 
- `_new_agent_state()` — 
- `_compose_observation(state, slate)` — 
- `_progress_state(state, current_step)` — 
- `_start_task(state, task_meta, features, current_step)` — 
- `_resolve_task(state, pending)` — 
- `_win_probability(state, task_vec, task_meta)` — 
- `_rival_penalty()` — 

### CompetitionEnv
Single-agent environment with capacity, fatigue, rivals, and deadlines.

Methods:
- `__init__(processed_dir, rl_config, env_config)` — 
- `reset(seed=, options=)` — 
- `step(action)` — 
- `_info(state)` — 
- `render(mode)` — 

### MultiAgentCompetitionEnv
Wrapper that simulates multiple policies simultaneously over shared markets.

Methods:
- `__init__(agent_names, processed_dir, rl_config, env_config, seed)` — 
- `reset(seed)` — 
- `step(actions)` — 
- `_multi_info()` —
