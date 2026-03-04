"""Strategy implementations for the Tower-of-Hanoi benchmark."""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

from .env import Move, TowerOfHanoiEnv


def estimate_tokens(*chunks: object) -> int:
    text = " ".join(str(chunk) for chunk in chunks if chunk)
    tokens = len(text.split())
    return max(1, tokens)


class BaseStrategy(ABC):
    name = "base"

    def __init__(self, token_budget: Optional[int] = None) -> None:
        self.token_budget = token_budget
        self.token_used = 0
        self._rng = random.Random()
        self._n_disks = 0

    def reset(self, n_disks: int, seed: Optional[int] = None, goal_peg: int = 2) -> None:
        self._n_disks = n_disks
        if seed is not None:
            self._rng.seed(seed)
        self.token_used = 0

    def _consume_tokens(self, *chunks: object) -> int:
        delta = estimate_tokens(*chunks)
        self.token_used += delta
        return delta

    @abstractmethod
    def select_move(self, env: TowerOfHanoiEnv) -> Move:
        """Return the next legal move."""


def _generate_plan(n: int, source: int, target: int, aux: int) -> List[Move]:
    if n <= 0:
        return []
    plan = _generate_plan(n - 1, source, aux, target)
    plan.append((source, target))
    plan.extend(_generate_plan(n - 1, aux, target, source))
    return plan


class FullDecompositionStrategy(BaseStrategy):
    name = "full_decomposition"

    def reset(self, n_disks: int, seed: Optional[int] = None, goal_peg: int = 2) -> None:
        super().reset(n_disks, seed=seed, goal_peg=goal_peg)
        aux_candidates = [idx for idx in range(3) if idx not in {0, goal_peg}]
        aux = aux_candidates[0]
        self._plan = _generate_plan(n_disks, 0, goal_peg, aux)

    def select_move(self, env: TowerOfHanoiEnv) -> Move:
        if not self._plan:
            legal = env.legal_moves()
            if not legal:
                raise RuntimeError("No legal moves available")
            return legal[0]
        move = self._plan.pop(0)
        self._consume_tokens(f"Execute planned move {move}", f"remaining={len(self._plan)}")
        return move


class SelectThenDecomposeStrategy(BaseStrategy):
    name = "select_then_decompose"

    def __init__(self, token_budget: Optional[int] = None, chunk_size: int = 16, greedy_threshold: int = 3) -> None:
        super().__init__(token_budget=token_budget)
        self.chunk_size = chunk_size
        self.greedy_threshold = greedy_threshold
        self._current_chunk: List[Move] = []
        self._plan: List[Move] = []
        self._cursor = 0
        self._goal_peg = 2

    def reset(self, n_disks: int, seed: Optional[int] = None, goal_peg: int = 2) -> None:
        super().reset(n_disks, seed=seed, goal_peg=goal_peg)
        aux_candidates = [idx for idx in range(3) if idx not in {0, goal_peg}]
        aux = aux_candidates[0]
        self._plan = _generate_plan(n_disks, 0, goal_peg, aux)
        self._cursor = 0
        self._current_chunk = []
        self._goal_peg = goal_peg

    def _refill_chunk(self) -> bool:
        remaining = len(self._plan) - self._cursor
        if remaining <= 0:
            return False
        size = min(self.chunk_size, remaining)
        token_cost = estimate_tokens(f"plan {size} moves with {remaining} remaining")
        if self.token_budget is not None and self.token_used + token_cost > self.token_budget:
            return False
        self._consume_tokens(f"plan {size} moves", f"remaining={remaining}")
        self._current_chunk = self._plan[self._cursor : self._cursor + size]
        self._cursor += size
        return True

    def _fallback_move(self, env: TowerOfHanoiEnv) -> Move:
        target = self._goal_peg
        for disk in range(1, self._n_disks + 1):
            disk_peg = env.find_disk(disk)
            if disk_peg == target:
                continue
            candidate = (disk_peg, target)
            if env.is_legal(candidate):
                self._consume_tokens(f"fallback move disk {disk}")
                return candidate
        legal = env.legal_moves()
        if not legal:
            raise RuntimeError("No legal moves available for fallback")
        self._consume_tokens("fallback default")
        return legal[0]

    def select_move(self, env: TowerOfHanoiEnv) -> Move:
        unsolved = env.unsolved_disks()
        if unsolved == 0:
            legal = env.legal_moves()
            if not legal:
                raise RuntimeError("Puzzle already solved")
            return legal[0]
        if unsolved <= self.greedy_threshold and not self._current_chunk:
            return self._fallback_move(env)
        if not self._current_chunk:
            planned = self._refill_chunk()
            if not planned:
                return self._fallback_move(env)
        move = self._current_chunk.pop(0)
        if not env.is_legal(move):
            return self._fallback_move(env)
        self._consume_tokens("execute chunked move")
        return move


class NoDecompositionStrategy(BaseStrategy):
    name = "no_decomposition"

    def select_move(self, env: TowerOfHanoiEnv) -> Move:
        legal = env.legal_moves()
        if not legal:
            raise RuntimeError("No legal moves available")
        move = self._rng.choice(legal)
        self._consume_tokens("guess move")
        return move


STRATEGY_FACTORIES: Dict[str, Callable[[Optional[int]], BaseStrategy]] = {
    FullDecompositionStrategy.name: lambda budget=None: FullDecompositionStrategy(token_budget=budget),
    SelectThenDecomposeStrategy.name: lambda budget=None: SelectThenDecomposeStrategy(token_budget=budget),
    NoDecompositionStrategy.name: lambda budget=None: NoDecompositionStrategy(token_budget=budget),
}


__all__ = [
    "BaseStrategy",
    "FullDecompositionStrategy",
    "SelectThenDecomposeStrategy",
    "NoDecompositionStrategy",
    "STRATEGY_FACTORIES",
    "estimate_tokens",
]
