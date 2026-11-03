from collections import Counter

import pytest
from langgraph.errors import GraphRecursionError

from ontology_gate.cases import DEMO_CASES
from ontology_gate.graph import MAX_REPAIRS, build_graph, run_case
from ontology_gate.ontology import RULE_MESSAGES


@pytest.fixture(scope="module")
def correct():
    return build_graph("correct")


@pytest.mark.parametrize(
    ("case", "first_violation"),
    [("agent-approves", RULE_MESSAGES[2]), ("self-approval", RULE_MESSAGES[3])],
)
def test_one_repair_then_one_refund(correct, case, first_violation):
    run = run_case(correct, case)
    assert run.attempts == [("BLOCK", [first_violation]), ("ALLOW", [])]
    assert run.state["decision"] == "ALLOW"
    assert len(run.ledger) == 1
    assert run.ledger[0]["case"] == case
    assert not run.escalated


def test_duplicate_refund_escalates_without_paying(correct):
    run = run_case(correct, "duplicate-refund")
    assert run.attempts == [("BLOCK", [RULE_MESSAGES[4]])] * MAX_REPAIRS
    assert run.escalated
    assert run.ledger == []
    assert run.state["violations"] == [RULE_MESSAGES[4]]


def test_no_order_is_refunded_twice(correct):
    paid = Counter()
    for case in DEMO_CASES:
        paid.update(entry["order_id"] for entry in run_case(correct, case).ledger)
    assert paid == {"o1002": 1, "o1003": 1}


def test_uncapped_loop_hits_the_recursion_limit():
    with pytest.raises(GraphRecursionError):
        run_case(build_graph("uncapped"), "duplicate-refund", recursion_limit=25)


def test_no_escalate_loop_also_runs_away():
    with pytest.raises(GraphRecursionError):
        run_case(build_graph("no-escalate"), "duplicate-refund", recursion_limit=25)


def test_bypass_pays_a_small_refund_without_the_gate():
    run = run_case(build_graph("bypass"), "small-refund")
    assert run.attempts == []  # the gate never ran
    assert run.state["decision"] == ""
    assert run.ledger == [{"case": "small-refund", "order_id": "o1004", "refund_id": "rf_o1004_1"}]
    # On the correct graph the same proposal is blocked: the approver is the AI agent.
    blocked = run_case(build_graph("correct"), "small-refund")
    assert blocked.attempts[0] == ("BLOCK", [RULE_MESSAGES[2]])


def test_unknown_variant_is_rejected():
    with pytest.raises(ValueError, match="unknown variant"):
        build_graph("nope")
