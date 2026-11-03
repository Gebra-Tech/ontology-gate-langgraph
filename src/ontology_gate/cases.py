"""The refund requests the agent handles.

The three demo cases each hit a different rule of the policy. ``small-refund`` is a teaching
case for the ``bypass`` graph: its amount is under the shortcut threshold.
"""

from pydantic import BaseModel, ConfigDict


class Case(BaseModel):
    """One customer request for money back on an order."""

    model_config = ConfigDict(frozen=True)

    name: str
    customer: str
    order_id: str
    amount: int
    request: str


CASES: dict[str, Case] = {
    case.name: case
    for case in (
        Case(
            name="agent-approves",
            customer="lena",
            order_id="o1002",
            amount=80,
            request="Lena asks for 80 back on order o1002.",
        ),
        Case(
            name="self-approval",
            customer="priya",
            order_id="o1003",
            amount=40,
            request="Priya, who is a manager, asks for 40 back on her own order o1003.",
        ),
        Case(
            name="duplicate-refund",
            customer="lena",
            order_id="o1001",
            amount=60,
            request="Lena asks for 60 back on order o1001, which was already refunded (rf1).",
        ),
        Case(
            name="small-refund",
            customer="omar",
            order_id="o1004",
            amount=30,
            request="Omar asks for 30 back on order o1004.",
        ),
    )
}

DEMO_CASES: tuple[str, ...] = ("agent-approves", "self-approval", "duplicate-refund")


def get_case(name: str) -> Case:
    """Look up a case by name, with a clear error for a typo."""
    try:
        return CASES[name]
    except KeyError:
        raise KeyError(f"unknown case {name!r}; known cases: {', '.join(CASES)}") from None
