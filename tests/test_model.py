"""The default offline model repairs its proposal from the gate's messages."""

from ontology_gate.cases import get_case
from ontology_gate.gate import describe
from ontology_gate.graph import MAX_REPAIRS, build_graph, run_case
from ontology_gate.model import APPROVER_MESSAGES, RepairingModel
from ontology_gate.ontology import RULE_MESSAGES

MANAGER = "Only a Manager may approve a refund."
SELF = "The approver must not be the person who requested the refund."
ONCE = "An order can be refunded only once."


def approver(turtle: str) -> str | None:
    return describe(turtle).approved_by


def test_the_first_proposal_comes_from_the_case():
    model = RepairingModel()
    case = get_case("self-approval")
    first = describe(model.propose(case, [], 0))
    assert (first.order_id, first.requested_by, first.approved_by, first.amount) == (
        "o1003",
        "priya",
        "priya",
        40,
    )


def test_a_rejected_approver_becomes_a_manager_other_than_the_requester():
    model = RepairingModel()
    assert model.managers == ["marco", "priya"]
    assert approver(model.propose(get_case("agent-approves"), [MANAGER], 1)) == "marco"
    assert approver(model.propose(get_case("self-approval"), [SELF], 1)) == "marco"


def test_nothing_changes_when_the_order_was_already_refunded():
    model = RepairingModel()
    case = get_case("duplicate-refund")
    proposals = [model.propose(case, [] if n == 0 else [ONCE], n) for n in range(3)]
    assert {approver(p) for p in proposals} == {"priya"}
    assert [describe(p).refund_id for p in proposals] == ["rf_o1001_1", "rf_o1001_2", "rf_o1001_3"]


def test_the_approver_messages_are_policy_messages():
    assert APPROVER_MESSAGES <= set(RULE_MESSAGES)


class WithholdMessages:
    """Passes no messages on, so the model never learns why it was blocked."""

    def __init__(self, model):
        self.model = model

    def propose(self, case, violations, attempt):
        return self.model.propose(case, [], attempt)


def test_with_the_messages_withheld_the_run_ends_in_three_blocks():
    graph = build_graph("correct", WithholdMessages(RepairingModel()))
    run = run_case(graph, "agent-approves")
    assert run.attempts == [("BLOCK", [MANAGER])] * MAX_REPAIRS
    assert run.escalated and run.ledger == []
    # With the messages, the same model repairs the proposal on its second attempt.
    repaired = run_case(build_graph("correct", RepairingModel()), "agent-approves")
    assert repaired.attempts == [("BLOCK", [MANAGER]), ("ALLOW", [])]
