"""The door: what a proposal may contain before the ontology gate reads it.

``shape_errors`` parses a proposal and accepts only one refund: a single subject, typed
``shop:Refund`` and nothing else, with exactly one each of ``forOrder``, ``requestedBy``,
``approvedBy`` and ``amount``, and no other triple. Anything more would be merged into the
knowledge base the gate validates against, so a proposal could, for example, make its own
approver a Manager. ``gate()`` calls it first.

``door_errors`` is Pydantic at the door, run by the ``door`` node of the graph. It adds two
steps to ``shape_errors``: the fields must have the right types (``RefundProposal``), and the
refund must match the request it answers (same order, same requester, and no more than the
customer asked for). The gate never sees the request, so only the door can check that.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError
from rdflib import RDF, Graph, Literal, Namespace, URIRef

from ontology_gate.cases import Case
from ontology_gate.ontology import NOT_ONE_REFUND, NOTHING_ELSE, NS, PREFIXES

SHOP = Namespace(NS)

WRONG_ORDER = "The refund must be for the order in the request."
WRONG_REQUESTER = "The requester must be the customer who made the request."
TOO_MUCH = "The amount must not be more than the customer asked for."

Name = Annotated[StrictStr, Field(min_length=1)]


class RefundProposal(BaseModel):
    """The fields of one proposed refund, typed. Names are local names in the shop namespace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    refund_id: Name
    order_id: Name
    requested_by: Name
    approved_by: Name
    amount: Annotated[StrictInt, Field(gt=0)]


# How a message names each field of RefundProposal.
LABELS = {
    "refund_id": "refund id",
    "order_id": "order",
    "requested_by": "requester",
    "approved_by": "approver",
    "amount": "amount",
}

# The four fields a refund has once each, with the policy message for a refund that lacks one.
# The messages are those of the matching SHACL rules, in the order the shapes declare them.
FIELDS = {
    SHOP.amount: "A refund needs an amount of at most 1000.",
    SHOP.forOrder: "Name the order this refund is for.",
    SHOP.requestedBy: "A refund needs a requester.",
    SHOP.approvedBy: "A refund needs an approver.",
}


def parse_turtle(ttl: str) -> Graph:
    """Parse Turtle that uses the shop prefixes. Raises on invalid Turtle."""
    graph = Graph()
    graph.parse(data=PREFIXES + ttl, format="turtle")
    return graph


def shape_errors(proposal_ttl: str) -> list[str]:
    """Policy messages for a proposal that is not one refund with its four fields. Never raises.

    An empty list means the proposal has exactly the accepted shape.
    """
    try:
        graph = parse_turtle(proposal_ttl)
    except Exception as error:  # rdflib raises several unrelated types on bad Turtle
        lines = str(error).strip().splitlines()
        detail = lines[0] if lines else type(error).__name__
        return [f"The proposal is not valid Turtle: {detail}"]

    refunds = set(graph.subjects(RDF.type, SHOP.Refund))
    if not refunds:
        return [NOT_ONE_REFUND]
    if len(set(graph.subjects())) != 1:
        return [NOTHING_ELSE]
    [refund] = refunds
    if set(graph.objects(refund, RDF.type)) != {SHOP.Refund}:
        return [NOTHING_ELSE]
    if set(graph.predicates(refund)) - {RDF.type} - FIELDS.keys():
        return [NOTHING_ELSE]
    if any(len(set(graph.objects(refund, field))) > 1 for field in FIELDS):
        return [NOTHING_ELSE]
    return [message for field, message in FIELDS.items() if graph.value(refund, field) is None]


def read_proposal(proposal_ttl: str) -> RefundProposal:
    """The typed fields of a proposal that passed ``shape_errors``. Raises ValidationError."""
    graph = parse_turtle(proposal_ttl)
    [refund] = graph.subjects(RDF.type, SHOP.Refund)
    amount = graph.value(refund, SHOP.amount)
    return RefundProposal.model_validate(
        {
            "refund_id": _name(refund),
            "order_id": _name(graph.value(refund, SHOP.forOrder)),
            "requested_by": _name(graph.value(refund, SHOP.requestedBy)),
            "approved_by": _name(graph.value(refund, SHOP.approvedBy)),
            "amount": amount.toPython() if isinstance(amount, Literal) else None,
        }
    )


def case_errors(proposal: RefundProposal, case: Case) -> list[str]:
    """Messages for a refund that does not answer the request it was proposed for."""
    errors = []
    if proposal.order_id != case.order_id:
        errors.append(WRONG_ORDER)
    if proposal.requested_by != case.customer:
        errors.append(WRONG_REQUESTER)
    if proposal.amount > case.amount:
        errors.append(TOO_MUCH)
    return errors


def door_errors(proposal_ttl: str, case: Case) -> list[str]:
    """Everything the door finds wrong with a proposal for this case. Never raises."""
    errors = shape_errors(proposal_ttl)
    if errors:
        return errors
    try:
        proposal = read_proposal(proposal_ttl)
    except ValidationError as error:
        return [
            f"The {LABELS[str(detail['loc'][0])]} is not valid: {detail['msg']}."
            for detail in error.errors()
        ]
    return case_errors(proposal, case)


def _name(node: object) -> str | None:
    """The local name of a shop IRI, or None for anything else."""
    if isinstance(node, URIRef) and str(node).startswith(NS):
        return str(node).removeprefix(NS)
    return None
