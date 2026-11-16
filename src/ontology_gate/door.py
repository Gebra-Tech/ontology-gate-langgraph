"""The door: what a proposal may contain before the ontology gate reads it.

``shape_errors`` parses a proposal and accepts only one refund: a single subject, typed
``shop:Refund`` and nothing else, with exactly one each of ``forOrder``, ``requestedBy``,
``approvedBy`` and ``amount``, and no other triple. Anything more would be merged into the
knowledge base the gate validates against, so a proposal could, for example, make its own
approver a Manager.
"""

from rdflib import RDF, Graph, Namespace

from ontology_gate.ontology import NOT_ONE_REFUND, NOTHING_ELSE, NS, PREFIXES

SHOP = Namespace(NS)

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
