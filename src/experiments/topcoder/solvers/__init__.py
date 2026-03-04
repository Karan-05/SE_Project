"""Solver registry for the Universal Task Solver."""
from __future__ import annotations

from .base import BaseSolver, SolverContext, SolverResult
from .algo_coding import AlgoCodingSolver
from .design_doc import ArchitectureDocSolver, DesignDocSolver
from .repo_patch import RepoPatchSolver
from .data_etl import DataETLSolver

__all__ = [
    "BaseSolver",
    "SolverContext",
    "SolverResult",
    "AlgoCodingSolver",
    "ArchitectureDocSolver",
    "DesignDocSolver",
    "RepoPatchSolver",
    "DataETLSolver",
]
