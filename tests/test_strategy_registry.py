from src.decomposition.registry import STRATEGIES, get_strategy


def test_registry_contains_all_strategies():
    expected = {
        "contract_first",
        "pattern_skeleton",
        "failure_mode_first",
        "multi_view",
        "semantic_diff",
        "role_decomposed",
        "simulation_trace",
    }
    assert expected.issubset(set(STRATEGIES.keys()))
    assert get_strategy("contract_first").name == "contract_first"
