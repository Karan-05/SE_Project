# rl.agents

_Summary_: Baseline and RL agents for the CompetitionEnv.

## Classes
### BaseAgent
No class docstring.

Methods:
- `act(env, observation)` — 
- `observe(*_)` — 

### RandomAgent
No class docstring.

Methods:
- `act(env, observation)` — 

### GreedyPrizeAgent
No class docstring.

Methods:
- `act(env, observation)` — 

### SkillMatchAgent
No class docstring.

Methods:
- `act(env, observation)` — 

### BanditConfig
No class docstring.

### ContextualBanditAgent
No class docstring.

Methods:
- `__init__(obs_dim, task_dim, config)` — 
- `act(env, observation)` — 
- `observe(reward, env)` — 

### DQN
No class docstring.

Methods:
- `__init__(input_dim, output_dim)` — 
- `forward(x)` — 

### DQNConfig
No class docstring.

### DQNAgent
No class docstring.

Methods:
- `__init__(obs_dim, action_dim, config)` — 
- `act(env, observation)` — 
- `remember(obs, action, reward, next_obs, done)` — 
- `learn()` — 

## Functions
- `_task_matrix(env, observation)` —
