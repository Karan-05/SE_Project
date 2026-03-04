"""Minimal Tower-of-Hanoi environment + helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

Move = Tuple[int, int]


def optimal_moves(n_disks: int) -> int:
    if n_disks < 0:
        raise ValueError("n_disks must be non-negative")
    return max(0, (1 << n_disks) - 1)


@dataclass
class HanoiState:
    pegs: Tuple[Tuple[int, ...], ...]
    moves_taken: int


class TowerOfHanoiEnv:
    """Pure-Python Tower-of-Hanoi simulator."""

    def __init__(self, n_disks: int, num_pegs: int = 3, goal_peg: int = 2) -> None:
        if num_pegs < 3:
            raise ValueError("Tower of Hanoi requires at least 3 pegs")
        self.n_disks = n_disks
        self.num_pegs = num_pegs
        self.goal_peg = goal_peg
        self._pegs: List[List[int]] = []
        self.moves_taken = 0
        self.reset()

    # ------------------------------------------------------------------ State helpers
    def reset(self) -> None:
        self._pegs = [list(range(self.n_disks, 0, -1))]
        while len(self._pegs) < self.num_pegs:
            self._pegs.append([])
        self.moves_taken = 0

    def state(self) -> HanoiState:
        return HanoiState(pegs=tuple(tuple(peg) for peg in self._pegs), moves_taken=self.moves_taken)

    # ------------------------------------------------------------------ Game logic
    def legal_moves(self) -> List[Move]:
        moves: List[Move] = []
        for src in range(self.num_pegs):
            if not self._pegs[src]:
                continue
            disk = self._pegs[src][-1]
            for dst in range(self.num_pegs):
                if src == dst:
                    continue
                if not self._pegs[dst] or self._pegs[dst][-1] > disk:
                    moves.append((src, dst))
        return moves

    def is_legal(self, move: Move) -> bool:
        src, dst = move
        if src < 0 or src >= self.num_pegs or dst < 0 or dst >= self.num_pegs or src == dst:
            return False
        if not self._pegs[src]:
            return False
        disk = self._pegs[src][-1]
        return not self._pegs[dst] or self._pegs[dst][-1] > disk

    def apply_move(self, move: Move) -> None:
        if not self.is_legal(move):
            raise ValueError(f"Illegal move attempted: {move}")
        src, dst = move
        disk = self._pegs[src].pop()
        self._pegs[dst].append(disk)
        self.moves_taken += 1

    def is_solved(self) -> bool:
        return len(self._pegs[self.goal_peg]) == self.n_disks and self._pegs[self.goal_peg] == sorted(
            self._pegs[self.goal_peg], reverse=True
        )

    def unsolved_disks(self) -> int:
        return self.n_disks - len(self._pegs[self.goal_peg])

    def find_disk(self, disk: int) -> int:
        for idx, peg in enumerate(self._pegs):
            if disk in peg:
                return idx
        raise ValueError(f"Disk {disk} not found in state")

    # ------------------------------------------------------------------
    @property
    def optimal_moves(self) -> int:
        return optimal_moves(self.n_disks)


__all__ = ["TowerOfHanoiEnv", "HanoiState", "Move", "optimal_moves"]
