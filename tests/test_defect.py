"""The defect graph pays the refund before the gate has seen it."""

from collections import Counter

import pytest

from ontology_gate.graph import MAX_REPAIRS, build_graph, run_case
from ontology_gate.ontology import RULE_MESSAGES


@pytest.fixture(scope="module")
def defect():
    return build_graph("defect")


def test_duplicate_refund_is_paid_on_every_blocked_attempt(defect):
    run = run_case(defect, "duplicate-refund")
    assert run.attempts == [("BLOCK", [RULE_MESSAGES[4]])] * MAX_REPAIRS
    assert run.escalated
    assert [entry["order_id"] for entry in run.ledger] == ["o1001"] * 3
    assert [entry["refund_id"] for entry in run.ledger] == [
        "rf_o1001_1",
        "rf_o1001_2",
        "rf_o1001_3",
    ]


def test_blocked_proposal_was_already_paid(defect):
    run = run_case(defect, "agent-approves")
    assert [decision for decision, _ in run.attempts] == ["BLOCK", "ALLOW"]
    assert Counter(entry["order_id"] for entry in run.ledger) == {"o1002": 2}
    # The first entry is the proposal the gate blocked: the AI agent approved it.
    assert run.ledger[0]["refund_id"] == "rf_o1002_1"


def test_correct_graph_pays_the_same_cases_once():
    correct = build_graph("correct")
    assert run_case(correct, "duplicate-refund").ledger == []
    assert len(run_case(correct, "agent-approves").ledger) == 1
