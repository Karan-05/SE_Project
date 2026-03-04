# providers.llm

_Summary_: LLM provider stub with deterministic budgeting + cache-aware responses.

## Classes
### LLMResponse
No class docstring.

Methods:
- `to_json()` — 
- `from_json(payload)` — 

## Functions
- `_mock_mode()` — 
- `_read_budget(env_name)` — 
- `_hash_payload(payload)` — 
- `_mock_completion(prompt, model)` — 
- `_estimate_tokens(prompt, extra)` — 
- `_predict_latency(tokens)` — 
- `_update_budgets(tokens, elapsed, caller)` — 
- `_token_limit()` — 
- `_time_limit()` — 
- `_budget_available(tokens, elapsed)` — 
- `get_usage()` — Return global token/time usage per caller.
- `call(prompt, model, max_tokens, temperature, caller, **kwargs)` — Call the configured LLM provider (mocked by default) with budgeting.
