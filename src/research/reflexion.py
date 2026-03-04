"""Reflexion-style planner/executor interfaces with lightweight controllers."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence, Tuple


@dataclass
class Plan:
    steps: List[str]
    reflections: List[str] = field(default_factory=list)


@dataclass
class ExecutionResult:
    success_score: float
    tokens_used: int
    strategy: str
    repaired: bool = False


@dataclass
class VerificationResult:
    success: bool
    reason: str = ""


class Planner(Protocol):
    def build_plan(self, task: Dict[str, object], reflections: Sequence[str]) -> Plan:
        ...


class Executor(Protocol):
    def execute(self, task: Dict[str, object], plan: Plan, strategy: str) -> ExecutionResult:
        ...


class Verifier(Protocol):
    def verify(self, task: Dict[str, object], execution: ExecutionResult) -> VerificationResult:
        ...


class Memory(Protocol):
    def recall(self, task_id: str) -> List[str]:
        ...

    def store(self, task_id: str, reflection: str) -> None:
        ...


@dataclass
class StrategySpec:
    name: str
    weight: float


class StrategyRegistry:
    """Catalog of available strategies and their weights."""

    def __init__(self, specs: Sequence[StrategySpec]):
        self.specs = list(specs)

    def default(self) -> StrategySpec:
        return self.specs[0]

    def all(self) -> Sequence[StrategySpec]:
        return self.specs


class RLController(Protocol):
    def choose(self, registry: StrategyRegistry) -> StrategySpec:
        ...

    def record(self, strategy: str, success: bool) -> None:
        ...


class Monitor(Protocol):
    def record(self, task_id: str, outcome: "TaskOutcome") -> None:
        ...

    def metrics(self) -> Dict[str, object]:
        ...


class SimplePlanner:
    def build_plan(self, task: Dict[str, object], reflections: Sequence[str]) -> Plan:
        steps = [
            f"Understand task: {task.get('title') or task.get('id')}",
            "Draft approach",
            "Validate outputs",
        ]
        if reflections:
            steps.insert(1, "Apply reflections: " + "; ".join(reflections))
        return Plan(steps=steps, reflections=list(reflections))


class SimpleExecutor:
    def execute(self, task: Dict[str, object], plan: Plan, strategy: str) -> ExecutionResult:
        complexity = float(task.get("complexity", 1.0))
        strategy_bonus = 1.5 if strategy == "deep_research" else 1.0
        reflection_bonus = 0.5 * len(plan.reflections)
        score = strategy_bonus + reflection_bonus
        tokens_used = 200 + 50 * len(plan.steps)
        return ExecutionResult(success_score=score, tokens_used=tokens_used, strategy=strategy)


class SimpleVerifier:
    def verify(self, task: Dict[str, object], execution: ExecutionResult) -> VerificationResult:
        target = float(task.get("complexity", 1.0))
        success = execution.success_score >= target
        reason = "" if success else "insufficient_detail"
        return VerificationResult(success=success, reason=reason)


class ReflectionMemory:
    def __init__(self):
        self._store: Dict[str, List[str]] = {}

    def recall(self, task_id: str) -> List[str]:
        return list(self._store.get(task_id, []))

    def store(self, task_id: str, reflection: str) -> None:
        self._store.setdefault(task_id, []).append(reflection)


class BanditRLController:
    def __init__(self, *, epsilon: float = 0.2):
        self.epsilon = epsilon
        self.stats: Dict[str, Tuple[int, int]] = {}
        self._random = random.Random(42)

    def choose(self, registry: StrategyRegistry) -> StrategySpec:
        if not self.stats:
            for spec in registry.all():
                self.stats[spec.name] = (0, 0)
        if self._random.random() < self.epsilon:
            return self._random.choice(list(registry.all()))
        best_name = registry.default().name
        best_score = float("-inf")
        for spec in registry.all():
            success, attempts = self.stats.get(spec.name, (0, 0))
            score = success / attempts if attempts else 0.0
            if score > best_score:
                best_score = score
                best_name = spec.name
        return next(spec for spec in registry.all() if spec.name == best_name)

    def record(self, strategy: str, success: bool) -> None:
        success_count, attempts = self.stats.get(strategy, (0, 0))
        self.stats[strategy] = (success_count + (1 if success else 0), attempts + 1)


@dataclass
class TaskOutcome:
    task_id: str
    success: bool
    attempts: int
    failure_reason: str = ""
    tokens_used: int = 0
    repairs_applied: int = 0


class MetricsMonitor:
    def __init__(self):
        self.outcomes: List[TaskOutcome] = []

    def record(self, task_id: str, outcome: TaskOutcome) -> None:
        self.outcomes.append(outcome)

    def metrics(self) -> Dict[str, object]:
        total = len(self.outcomes)
        successes = sum(1 for outcome in self.outcomes if outcome.success)
        repairs = sum(1 for outcome in self.outcomes if outcome.repairs_applied > 0)
        total_attempts = sum(outcome.attempts for outcome in self.outcomes)
        token_cost = sum(outcome.tokens_used for outcome in self.outcomes)
        failure_taxonomy: Dict[str, int] = {}
        for outcome in self.outcomes:
            if not outcome.failure_reason:
                continue
            failure_taxonomy[outcome.failure_reason] = failure_taxonomy.get(outcome.failure_reason, 0) + 1
        pass_rate = successes / total if total else 0.0
        return {
            "pass_rate": pass_rate,
            "avg_attempts": (total_attempts / total) if total else 0.0,
            "token_cost": token_cost,
            "failure_taxonomy": failure_taxonomy,
            "repair_rate": repairs / total if total else 0.0,
            "gate_pass_rate": 1.0 if pass_rate >= 0.6 else 0.0,
        }


@dataclass
class ReflexionConfig:
    enable_memory: bool = True
    enable_rl: bool = True
    enable_repair: bool = True
    max_attempts: int = 3


class ReflexionLoop:
    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        verifier: Verifier,
        memory: Memory,
        registry: StrategyRegistry,
        rl_controller: RLController,
        monitor: Monitor,
        config: ReflexionConfig,
    ):
        self.planner = planner
        self.executor = executor
        self.verifier = verifier
        self.memory = memory
        self.registry = registry
        self.rl = rl_controller
        self.monitor = monitor
        self.config = config

    def run_task(self, task: Dict[str, object]) -> TaskOutcome:
        task_id = str(task.get("id", "task"))
        reflections = self.memory.recall(task_id) if self.config.enable_memory else []
        attempts = 0
        tokens_used = 0
        repairs = 0
        failure_reason = ""
        while attempts < self.config.max_attempts:
            attempts += 1
            plan = self.planner.build_plan(task, reflections)
            strategy_spec = (
                self.rl.choose(self.registry) if self.config.enable_rl else self.registry.default()
            )
            execution = self.executor.execute(task, plan, strategy_spec.name)
            tokens_used += execution.tokens_used
            verification = self.verifier.verify(task, execution)
            self.rl.record(strategy_spec.name, verification.success)
            if verification.success:
                outcome = TaskOutcome(
                    task_id=task_id,
                    success=True,
                    attempts=attempts,
                    failure_reason="",
                    tokens_used=tokens_used,
                    repairs_applied=repairs,
                )
                self.monitor.record(task_id, outcome)
                return outcome
            failure_reason = verification.reason or "unknown_failure"
            if self.config.enable_memory:
                self.memory.store(task_id, f"Attempt {attempts}: {failure_reason}")
            if not self.config.enable_repair:
                break
            repairs += 1
            reflections.append(f"Retry focusing on {failure_reason}")
        outcome = TaskOutcome(
            task_id=task_id,
            success=False,
            attempts=attempts,
            failure_reason=failure_reason or "max_attempts",
            tokens_used=tokens_used,
            repairs_applied=repairs,
        )
        self.monitor.record(task_id, outcome)
        return outcome


def run_reflexion_experiment(
    tasks: Sequence[Dict[str, object]],
    config: ReflexionConfig,
    *,
    seed: int = 42,
) -> Dict[str, object]:
    planner = SimplePlanner()
    executor = SimpleExecutor()
    verifier = SimpleVerifier()
    memory = ReflectionMemory()
    registry = StrategyRegistry(
        [StrategySpec("rapid_plan", 1.0), StrategySpec("deep_research", 1.5)]
    )
    rl_controller = BanditRLController(epsilon=0.2)
    monitor = MetricsMonitor()
    loop = ReflexionLoop(planner, executor, verifier, memory, registry, rl_controller, monitor, config)
    random.Random(seed).shuffle(tasks := list(tasks))
    for task in tasks:
        loop.run_task(task)
    metrics = monitor.metrics()
    metrics.update(
        {
            "memory_enabled": config.enable_memory,
            "rl_enabled": config.enable_rl,
            "repair_enabled": config.enable_repair,
        }
    )
    return metrics
