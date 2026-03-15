from src.decomposition.real_repo.contract_graph import (
    build_contract_graph,
    choose_next_clause,
    update_from_run,
)
from src.decomposition.real_repo.contracts import ContractCoverageResult, ContractItem
from src.decomposition.real_repo.witnesses import SemanticWitness


def make_contract_items():
    return [
        ContractItem(id="C1", description="Return 200", category="http"),
        ContractItem(id="C2", description="Filter billing items", category="http"),
    ]


def test_contract_graph_tracks_satisfaction_and_regressions():
    items = make_contract_items()
    graph = build_contract_graph(items)
    coverage = ContractCoverageResult(
        total=2,
        satisfied_ids=["C1"],
        unsatisfied_ids=["C2"],
        categories={"http": 1},
        coverage=0.5,
        failing_cases=["Billing API::filter bills"],
    )
    witness = SemanticWitness(
        test_case="Billing API::filter bills",
        message="AssertionError: expected 0 to equal 2",
        category="assertion",
    )
    update_from_run(graph, coverage, [witness], round_index=0)
    assert graph.nodes["C1"].status == "satisfied"
    assert graph.nodes["C1"].satisfied_round == 0
    assert graph.nodes["C2"].status == "unsatisfied"

    regression = ContractCoverageResult(
        total=2,
        satisfied_ids=[],
        unsatisfied_ids=["C1", "C2"],
        categories={"http": 2},
        coverage=0.0,
        failing_cases=["Billing API::filter bills", "Challenge::status code"],
    )
    update_from_run(graph, regression, [witness], round_index=1)
    assert graph.nodes["C1"].status == "regressed"
    assert graph.nodes["C1"].regressed_round == 1


def test_choose_next_clause_prioritizes_regressions():
    items = make_contract_items()
    graph = build_contract_graph(items)
    first = ContractCoverageResult(
        total=2,
        satisfied_ids=["C1"],
        unsatisfied_ids=["C2"],
        categories={"http": 1},
        coverage=0.5,
        failing_cases=["Billing API::filter bills"],
    )
    update_from_run(graph, first, [SemanticWitness(test_case="Billing API::filter bills")], round_index=0)
    regression = ContractCoverageResult(
        total=2,
        satisfied_ids=[],
        unsatisfied_ids=["C1", "C2"],
        categories={"http": 2},
        coverage=0.0,
        failing_cases=["Billing API::filter bills"],
    )
    witnesses = [
        SemanticWitness(test_case="Billing API::filter bills", message="AssertionError"),
        SemanticWitness(test_case="Billing API::filter bills", message="AssertionError again"),
    ]
    update_from_run(graph, regression, witnesses, round_index=1)
    clause = choose_next_clause(graph)
    assert clause == "C1"
    assert graph.active_clause_id == "C1"
