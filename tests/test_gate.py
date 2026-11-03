import pytest

from ontology_gate.gate import describe, gate
from ontology_gate.ontology import KB_TTL, RULE_MESSAGES


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
        (refund(amount=1500), RULE_MESSAGES[0]),
        (refund(amount=None), RULE_MESSAGES[0]),
        (refund(order=None), RULE_MESSAGES[1]),
        (refund(approver="shopbot"), RULE_MESSAGES[2]),
        (refund(approver="lena", requester="omar"), RULE_MESSAGES[2]),
        (refund(order="o1003", requester="priya", approver="priya", amount=40), RULE_MESSAGES[3]),
        (refund(order="o1001"), RULE_MESSAGES[4]),
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
    assert second.violations == [RULE_MESSAGES[4]]


def test_invalid_turtle_blocks_without_raising():
    result = gate("shop:rf_test a shop:Refund ; shop:forOrder")
    assert result.decision == "BLOCK"
    assert result.violations[0].startswith("The proposal is not valid Turtle")


def test_a_proposal_must_describe_exactly_one_refund():
    assert gate("").violations == ["The proposal must describe exactly one refund."]
    two = refund() + refund().replace("rf_test", "rf_other")
    assert gate(two).decision == "BLOCK"


def test_describe_reads_the_refund_fields():
    summary = describe(refund(approver="shopbot"))
    assert summary.refund_id == "rf_test"
    assert summary.order_id == "o1002"
    assert summary.approved_by == "shopbot"
    assert summary.amount == 80
    assert describe("not turtle").refund_id is None
