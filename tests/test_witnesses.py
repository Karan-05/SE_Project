from src.decomposition.real_repo.contracts import ContractItem
from src.decomposition.real_repo.witnesses import (
    extract_mocha_witnesses,
    link_witnesses_to_contract,
    witness_signature,
)


def test_extract_mocha_witnesses_parses_expected_actual():
    log = """
      1) Challenge Handler
           should filter active projects:
         AssertionError: expected 404 to equal 200
          + expected - actual
          -404
          +200
    """
    record = {"name": "tests", "status": "fail", "stderr": log}
    witnesses = extract_mocha_witnesses([record])
    assert len(witnesses) == 1
    witness = witnesses[0]
    assert witness.test_case == "Challenge Handler::should filter active projects"
    assert witness.expected == "200"
    assert witness.actual == "404"
    assert witness.category == "assertion"


def test_witness_linking_prefers_contract_tests():
    witness_log = """
      1) Billing API
           enforces category filter:
         AssertionError: expected 0 to equal 2
    """
    witnesses = extract_mocha_witnesses([{"name": "tests", "status": "fail", "stderr": witness_log}])
    items = [
        ContractItem(id="C1", description="Filter active projects", category="api", tests=("Challenge Handler::should filter active projects",)),
        ContractItem(id="C2", description="Billing API category filter", category="api", tests=("Billing API::enforces category filter",)),
    ]
    mapping = link_witnesses_to_contract(items, witnesses)
    assert len(mapping["C2"]) == 1
    assert witnesses[0].linked_contract_ids == ["C2"]


def test_witness_signature_stable_for_same_values():
    record = {
        "name": "tests",
        "status": "fail",
        "stderr": "AssertionError: expected foo to equal bar",
    }
    witnesses = extract_mocha_witnesses([record])
    sig_one = witness_signature(witnesses[0])
    sig_two = witness_signature(witnesses[0])
    assert sig_one == sig_two
