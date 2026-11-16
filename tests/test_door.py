"""Pydantic at the door: types, and a match with the request, before the ontology gate."""

import pytest
from pydantic import ValidationError

from ontology_gate.cases import get_case
from ontology_gate.door import TOO_MUCH, WRONG_ORDER, RefundProposal, door_errors
from ontology_gate.graph import MAX_REPAIRS, build_graph, run_case
from ontology_gate.model import refund_turtle

CASE = get_case("agent-approves")  # lena, 80 on o1002


def proposal(**fields) -> str:
    values = {"order": "shop:o1002", "requester": "shop:lena", "approver": "shop:marco"}
    values |= {"amount": "80"} | fields
    return (
        "shop:rf_door a shop:Refund ;\n"
        f"    shop:forOrder {values['order']} ;\n"
        f"    shop:requestedBy {values['requester']} ;\n"
        f"    shop:approvedBy {values['approver']} ;\n"
        f"    shop:amount {values['amount']} .\n"
    )


def test_a_well_formed_proposal_for_the_request_passes():
    assert door_errors(proposal(), CASE) == []


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ({"amount": '"80"'}, "The amount is not valid: Input should be a valid integer."),
        ({"amount": "80.5"}, "The amount is not valid: Input should be a valid integer."),
        ({"amount": "true"}, "The amount is not valid: Input should be a valid integer."),
        ({"approver": '"marco"'}, "The approver is not valid: Input should be a valid string."),
        (
            {"order": "<http://example.com/o1002>"},
            "The order is not valid: Input should be a valid string.",
        ),
    ],
    ids=["amount-as-text", "amount-decimal", "amount-boolean", "approver-literal", "foreign-iri"],
)
def test_a_malformed_proposal_is_stopped_at_the_door(bad, message):
    assert door_errors(proposal(**bad), CASE) == [message]


def test_a_refund_on_another_order_is_stopped_at_the_door():
    # Lena placed o1001 too, so the gate alone would only see the order already refunded.
    assert door_errors(proposal(order="shop:o1001"), CASE) == [WRONG_ORDER]


def test_an_amount_above_the_request_is_stopped_at_the_door():
    assert door_errors(proposal(amount="90"), CASE) == [TOO_MUCH]
    assert door_errors(proposal(amount="80"), CASE) == []


def test_the_requester_must_be_the_customer_who_asked():
    case = get_case("small-refund")  # omar on o1004
    errors = door_errors(proposal(order="shop:o1004", amount="30"), case)
    assert errors == ["The requester must be the customer who made the request."]


def test_shape_errors_come_first():
    assert door_errors("", CASE) == ["The proposal must describe exactly one refund."]


def test_refund_proposal_is_frozen_and_closed():
    fields = {
        "refund_id": "rf_x",
        "order_id": "o1002",
        "requested_by": "lena",
        "approved_by": "marco",
        "amount": 80,
    }
    accepted = RefundProposal(**fields)
    with pytest.raises(ValidationError):
        accepted.amount = 5
    with pytest.raises(ValidationError):
        RefundProposal(**fields, note="extra")
    with pytest.raises(ValidationError):
        RefundProposal(**(fields | {"amount": 0}))
    with pytest.raises(ValidationError):
        RefundProposal(**(fields | {"order_id": ""}))


class OverAsking:
    """Always proposes 10 more than the customer asked for, with a valid approver."""

    def propose(self, case, violations, attempt):
        bigger = case.model_copy(update={"amount": case.amount + 10})
        return refund_turtle(f"rf_over_{attempt + 1}", bigger, "marco")


def test_the_gate_answers_block_with_the_door_messages():
    run = run_case(build_graph("correct", OverAsking()), "agent-approves")
    assert run.attempts == [("BLOCK", [TOO_MUCH])] * MAX_REPAIRS
    assert run.escalated and run.ledger == []
