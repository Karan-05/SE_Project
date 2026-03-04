# rl.utils

_Summary_: Utility helpers for RL modules (reproducibility + streaming stats).

## Classes
### RunningStats
Online mean/std estimator using Welford's algorithm.

Methods:
- `update(value)` — 
- `variance()` — 
- `std()` — 

## Functions
- `set_global_seeds(seed)` — Seed python, numpy, torch (if available), and hashing for reproducibility.
