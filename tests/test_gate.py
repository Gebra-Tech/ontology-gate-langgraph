import re

import pytest

from ontology_gate.door import FIELDS
from ontology_gate.gate import describe, gate
from ontology_gate.ontology import KB_TTL, RULE_MESSAGES, SHAPE_MESSAGES, SHAPES_TTL

CAP = "A refund needs an amount of at most 1000."
NO_ORDER = "Name the order this refund is for."
MANAGER = "Only a Manager may approve a refund."
SELF = "The approver must not be the person who requested the refund."
ONCE = "An order can be refunded only once."


def refund(
    *,
    order: str | None = "o1002",
    requester: str = "lena",
    approver: str = "priya",
    amount: int | None = 80,
) -> str:
    lines = ["shop:rf_test a shop:Refund"]
    if order is not None:
        lines.append(f"shop:forOrder shop:{order}")
    lines.append(f"shop:requestedBy shop:{requester}")
    lines.append(f"shop:approvedBy shop:{approver}")
    if amount is not None:
        lines.append(f"shop:amount {amount}")
    return " ;\n    ".join(lines) + " .\n"


def test_valid_refund_is_allowed():
    result = gate(refund())
    assert result.decision == "ALLOW"
    assert result.violations == []


@pytest.mark.parametrize(
    ("proposal", "message"),
    [
        (refund(amount=1500), CAP),
        (refund(amount=None), CAP),
        (refund(order=None), NO_ORDER),
        (refund(approver="shopbot"), MANAGER),
        (refund(approver="omar"), MANAGER),
        (refund(order="o1003", requester="priya", approver="priya", amount=40), SELF),
        (refund(order="o1001"), ONCE),
    ],
    ids=["over-cap", "no-amount", "no-order", "agent", "customer", "self", "duplicate"],
)
def test_each_rule_blocks_with_its_own_message(proposal, message):
    result = gate(proposal)
    assert result.decision == "BLOCK"
    assert result.violations == [message]


def test_kb_violations_are_not_charged_to_the_proposal():
    # A knowledge base that already breaks the policy: rf9 was approved by the AI agent.
    broken_kb = KB_TTL + (
        "shop:rf9 a shop:Refund ; shop:forOrder shop:o1004 ; shop:requestedBy shop:omar ;\n"
        "    shop:approvedBy shop:shopbot ; shop:amount 5000 .\n"
    )
    assert gate(refund(), kb_ttl=broken_kb).decision == "ALLOW"
    # The duplicate rule still fires for a second refund on that same order.
    second = gate(refund(order="o1004", requester="omar"), kb_ttl=broken_kb)
    assert second.violations == [ONCE]


def test_invalid_turtle_blocks_without_raising():
    result = gate("shop:rf_test a shop:Refund ; shop:forOrder")
    assert result.decision == "BLOCK"
    assert result.violations[0].startswith("The proposal is not valid Turtle")


def test_a_proposal_must_describe_exactly_one_refund():
    assert gate("").violations == ["The proposal must describe exactly one refund."]
    two = refund() + refund().replace("rf_test", "rf_other")
    assert gate(two).violations == ["The proposal may describe one refund and nothing else."]


@pytest.mark.parametrize(
    "proposal",
    [
        refund().replace("a shop:Refund", "a shop:Refund , shop:Order"),
        refund().replace(" .\n", ' ;\n    shop:note "urgent" .\n'),
        refund().replace("shop:amount 80", "shop:amount 80 , 90"),
        refund().replace("shop:amount 80", "shop:amount [ shop:value 80 ]"),
    ],
    ids=["second-type", "other-property", "two-amounts", "nested-node"],
)
def test_the_door_accepts_one_refund_and_nothing_else(proposal):
    assert gate(proposal).violations == ["The proposal may describe one refund and nothing else."]


def test_unknown_people_are_blocked_before_the_closure():
    assert gate(refund(approver="bob")).violations == ["The approver does not exist."]
    assert gate(refund(requester="zoe")).violations == ["The requester does not exist."]


def test_messages_agree_with_the_shapes():
    declared = re.findall(r'sh:message "([^"]+)"', SHAPES_TTL)
    assert tuple(declared) == SHAPE_MESSAGES
    assert set(FIELDS.values()) <= set(SHAPE_MESSAGES)
    assert len(set(RULE_MESSAGES)) == len(RULE_MESSAGES)


def test_describe_reads_the_refund_fields():
    summary = describe(refund(approver="shopbot"))
    assert summary.refund_id == "rf_test"
    assert summary.order_id == "o1002"
    assert summary.approved_by == "shopbot"
    assert summary.amount == 80
    assert describe("not turtle").refund_id is None


GATE_HOLES = {
    "reused-id": (
        refund(order="o1001", amount=60).replace("rf_test", "rf1"),
        "The refund id is already in use.",
    ),
    "extra-fact": (
        "shop:shopbot a shop:Manager .\n" + refund(approver="shopbot"),
        "The proposal may describe one refund and nothing else.",
    ),
    "no-approver": (
        refund().replace("    shop:approvedBy shop:priya ;\n", ""),
        "A refund needs an approver.",
    ),
    "unknown-order": (refund(order="o9999"), "The order does not exist."),
    "not-the-customer": (
        refund(order="o1002", requester="omar"),
        "The requester must be the customer who placed the order.",
    ),
    "negative-amount": (refund(amount=-500), "The amount must be above 0."),
    "untyped-second-refund": (
        refund()
        + "shop:rf_other shop:forOrder shop:o1004 ; shop:requestedBy shop:omar ;\n"
        + "    shop:approvedBy shop:marco ; shop:amount 30 .\n",
        "The proposal may describe one refund and nothing else.",
    ),
}


@pytest.mark.parametrize(("proposal", "message"), GATE_HOLES.values(), ids=GATE_HOLES.keys())
def test_gate_holes_are_closed(proposal, message):
    result = gate(proposal)
    assert result.decision == "BLOCK"
    assert result.violations == [message]
