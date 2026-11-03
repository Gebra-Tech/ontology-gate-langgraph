"""The ontology gate: ALLOW or BLOCK one proposed refund against the knowledge base.

``gate()`` merges the schema, the knowledge base and the proposal, applies the OWL-RL closure
(which includes the RDFS rules), and validates the result against the SHACL policy. It reports
only the violations the proposal introduces: the knowledge base is validated on its own as
well, and anything already wrong there is not the proposal's fault.
"""

from functools import lru_cache
from typing import Literal

import owlrl
from pydantic import BaseModel, ConfigDict
from pyshacl import validate
from rdflib import RDF, Graph, Namespace, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import SH

from ontology_gate.ontology import KB_TTL, NS, PREFIXES, RULE_MESSAGES, SCHEMA_TTL, SHAPES_TTL

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
    try:
        proposal = _parse(proposal_ttl)
    except Exception as error:  # rdflib raises several unrelated types on bad Turtle
        lines = str(error).strip().splitlines()
        detail = lines[0] if lines else type(error).__name__
        return GateResult(
            decision="BLOCK", violations=[f"The proposal is not valid Turtle: {detail}"]
        )

    refunds = set(proposal.subjects(RDF.type, SHOP.Refund))
    if len(refunds) != 1:
        return GateResult(
            decision="BLOCK",
            violations=["The proposal must describe exactly one refund."],
        )

    before = _kb_results(kb_ttl)
    data = _parse(kb_ttl)
    data += proposal
    after = _results(data)
    new = after - before
    if not new:
        return GateResult(decision="ALLOW")
    return GateResult(decision="BLOCK", violations=_ordered_messages(new))


def describe(proposal_ttl: str) -> ProposalSummary:
    """Read the refund fields out of a proposal, for logging and the ledger."""
    try:
        graph = _parse(proposal_ttl)
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


def _parse(ttl: str) -> Graph:
    graph = Graph()
    graph.parse(data=PREFIXES + ttl, format="turtle")
    return graph


@lru_cache(maxsize=1)
def _shapes() -> Graph:
    return _parse(SHAPES_TTL)


@lru_cache(maxsize=1)
def _schema() -> Graph:
    return _parse(SCHEMA_TTL)


@lru_cache(maxsize=8)
def _kb_results(kb_ttl: str) -> frozenset[tuple[str, ...]]:
    return _results(_parse(kb_ttl))


def _results(facts: Graph) -> frozenset[tuple[str, ...]]:
    """Close the facts under the schema, validate, and key each result so runs can be compared."""
    data = Graph()
    data += _schema()
    data += facts
    owlrl.DeductiveClosure(
        owlrl.OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False
    ).expand(data)
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
