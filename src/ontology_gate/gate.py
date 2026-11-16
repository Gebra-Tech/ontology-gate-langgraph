"""The ontology gate: ALLOW or BLOCK one proposed refund against the knowledge base.

``gate()`` works in three steps, and the first step that finds a problem decides:

1. the door (``door.shape_errors``): the proposal is one refund with its four fields and
   nothing else;
2. the knowledge base, before any closure: the refund id is new, and the order, the requester
   and the approver are already there. This has to come first, because the OWL-RL closure types
   any object of ``forOrder`` as an Order and any approver as an Employee;
3. the policy: merge the schema, the knowledge base and the proposal, apply the OWL-RL closure
   (which includes the RDFS rules), and validate the result against the SHACL shapes. Only the
   violations the proposal introduces count: the knowledge base is validated on its own as well,
   and anything already wrong there is not the proposal's fault.
"""

from functools import lru_cache
from typing import Literal

import owlrl
from pydantic import BaseModel, ConfigDict
from pyshacl import validate
from rdflib import RDF, Graph, Namespace, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import SH

from ontology_gate.door import parse_turtle, shape_errors
from ontology_gate.ontology import (
    ID_IN_USE,
    KB_TTL,
    NO_SUCH_APPROVER,
    NO_SUCH_ORDER,
    NO_SUCH_REQUESTER,
    NS,
    RULE_MESSAGES,
    SCHEMA_TTL,
    SHAPES_TTL,
)

SHOP = Namespace(NS)


class GateResult(BaseModel):
    """What the gate decided, and the policy messages behind a BLOCK."""

    model_config = ConfigDict(frozen=True)

    decision: Literal["ALLOW", "BLOCK"]
    violations: list[str] = []


class ProposalSummary(BaseModel):
    """The fields of a proposed refund, read from its Turtle. Missing fields are None."""

    refund_id: str | None = None
    order_id: str | None = None
    requested_by: str | None = None
    approved_by: str | None = None
    amount: int | None = None


def gate(proposal_ttl: str, kb_ttl: str = KB_TTL) -> GateResult:
    """Decide whether one proposed refund may be written. Never raises on bad input."""
    errors = shape_errors(proposal_ttl)
    if errors:
        return GateResult(decision="BLOCK", violations=errors)
    proposal = parse_turtle(proposal_ttl)

    errors = _kb_errors(proposal, kb_ttl)
    if errors:
        return GateResult(decision="BLOCK", violations=errors)

    data = Graph()
    data += _kb(kb_ttl)
    data += proposal
    new = _results(_close(data)) - _kb_results(kb_ttl)
    if not new:
        return GateResult(decision="ALLOW")
    return GateResult(decision="BLOCK", violations=_ordered_messages(new))


def describe(proposal_ttl: str) -> ProposalSummary:
    """Read the refund fields out of a proposal, for logging and the ledger."""
    try:
        graph = parse_turtle(proposal_ttl)
    except Exception:
        return ProposalSummary()
    refund = next(iter(graph.subjects(RDF.type, SHOP.Refund)), None)
    if refund is None:
        return ProposalSummary()
    amount = graph.value(refund, SHOP.amount)
    return ProposalSummary(
        refund_id=_local(refund),
        order_id=_local(graph.value(refund, SHOP.forOrder)),
        requested_by=_local(graph.value(refund, SHOP.requestedBy)),
        approved_by=_local(graph.value(refund, SHOP.approvedBy)),
        amount=int(amount) if isinstance(amount, RDFLiteral) and _is_int(amount) else None,
    )


def _kb_errors(proposal: Graph, kb_ttl: str) -> list[str]:
    """The checks that must run on the knowledge base as it is, before any closure."""
    refund = next(iter(proposal.subjects(RDF.type, SHOP.Refund)))
    kb = _kb(kb_ttl)
    if (refund, None, None) in kb or (None, refund, None) in kb or (None, None, refund) in kb:
        return [ID_IN_USE]
    known = _kb_closed(kb_ttl)
    needed = (
        (SHOP.forOrder, SHOP.Order, NO_SUCH_ORDER),
        (SHOP.requestedBy, SHOP.Person, NO_SUCH_REQUESTER),
        (SHOP.approvedBy, SHOP.Person, NO_SUCH_APPROVER),
    )
    return [
        message
        for field, kind, message in needed
        if (proposal.value(refund, field), RDF.type, kind) not in known
    ]


@lru_cache(maxsize=1)
def _shapes() -> Graph:
    return parse_turtle(SHAPES_TTL)


@lru_cache(maxsize=1)
def _schema() -> Graph:
    return parse_turtle(SCHEMA_TTL)


@lru_cache(maxsize=8)
def _kb(kb_ttl: str) -> Graph:
    return parse_turtle(kb_ttl)


@lru_cache(maxsize=8)
def _kb_closed(kb_ttl: str) -> Graph:
    return _close(_kb(kb_ttl))


@lru_cache(maxsize=8)
def _kb_results(kb_ttl: str) -> frozenset[tuple[str, ...]]:
    return _results(_kb_closed(kb_ttl))


def _close(facts: Graph) -> Graph:
    """A new graph: the schema and the facts, with everything OWL-RL infers from them."""
    data = Graph()
    data += _schema()
    data += facts
    owlrl.DeductiveClosure(
        owlrl.OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False
    ).expand(data)
    return data


def _results(data: Graph) -> frozenset[tuple[str, ...]]:
    """Validate closed data and key each result so runs can be compared."""
    _conforms, report, _text = validate(data, shacl_graph=_shapes(), inference="none")
    keys = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        path = report.value(result, SH.resultPath)
        keys.add(
            (
                str(report.value(result, SH.focusNode)),
                str(path) if isinstance(path, URIRef) else "complex-path",
                str(report.value(result, SH.sourceConstraintComponent)),
                str(report.value(result, SH.value)),
                str(report.value(result, SH.resultMessage)),
            )
        )
    return frozenset(keys)


def _ordered_messages(results: frozenset[tuple[str, ...]]) -> list[str]:
    """Unique messages, in the order the policy declares its rules."""
    messages = {key[-1] for key in results}
    known = [message for message in RULE_MESSAGES if message in messages]
    return known + sorted(messages - set(known))


def _local(node: object) -> str | None:
    if node is None:
        return None
    return str(node).removeprefix(NS)


def _is_int(value: RDFLiteral) -> bool:
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True
