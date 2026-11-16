"""An experiment: the refund workflow graph as RDF, read by gebra and checked with SHACL.

The rule under test: no write is reachable from START without leaving the gate by its ALLOW
branch. gebra 0.2.0 has no rule of its own for gate ordering. Here gebra only reads the graph:
``graph_to_rdf`` turns gebra's extraction of one graph (``gebra.extract(graph, sidecar=...).ir``)
into triples, and the shapes and the queries below are this repository's.

From gebra's document it reads the entry, every edge with its branch labels, the finish nodes,
each node's effect tags and the state keys each node writes. Each node is a resource and each
edge a ``next`` statement. A node tagged ``billable`` or ``irreversible`` is typed ``Write``,
and each key a node writes is a ``writes`` statement. Each edge except the gate's ALLOW edge is
also an ``unchecked`` statement, and the ALLOW edge is an ``allow`` statement. Two things are
typed by hand, in ``BY_HAND``: which node is the gate, and which of its labels is ALLOW.

Two SHACL Core shapes, each with a property path and no recursion, validated with inference
switched off:

* the rule shape: no ``Write`` has START among its ancestors along ``unchecked`` edges;
* the obvious shape: some ancestor of the ``Write`` along ``next`` edges is the ``Gate``. It does
  not work: in a loop the gate is an ancestor of every node, so it passes the bypass and the
  defect graphs. It is kept to show that.

And three SPARQL ASK queries: a write reachable without ALLOW, the token written by a node the
ALLOW edge does not enter, and a node after the ALLOW edge, on the way to a write, that writes
the proposal.

What the experiment does not show:

* it covers eleven small graphs and one SHACL engine (pySHACL);
* the gate and its ALLOW label are typed by hand;
* the effect tags and the writes come from gebra's extraction, where they are declarations or
  gebra's inferences from a node's code; they are trusted here, not tested;
* the ``unchecked`` statements already carry the knowledge of which edge is ALLOW, so the rule
  shape is a reachability question over edges that were labelled with the answer in mind;
* the description is of the graph as declared, so a route computed at run time is invisible.

    python -m ontology_gate.graph_as_rdf     (make rdf) prints two tables, and exits non-zero
                                              if a row differs from what is expected
"""

import argparse
import sys
from pathlib import Path

import gebra
from pyshacl import validate
from rdflib import RDF, Graph, Namespace

from ontology_gate.allow_token import TOKEN_GRAPHS, sidecar_text
from ontology_gate.checks import write_sidecar
from ontology_gate.graph import build_graph

FLOW = Namespace("https://github.com/Gebra-Tech/ontology-gate-langgraph/flow#")

# The only facts typed by hand: which node is the gate, and which of its labels is ALLOW.
BY_HAND = {"gate": "gate", "allow label": "allow"}

WRITE_TAGS = {"billable", "irreversible"}

PREFIXES = f"""\
@prefix flow: <{FLOW}> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
"""

RULE_SHAPE = (
    PREFIXES
    + """
flow:RuleShape a sh:NodeShape ;
    sh:targetClass flow:Write ;
    sh:property [
        sh:path [ sh:oneOrMorePath [ sh:inversePath flow:unchecked ] ] ;
        sh:not [ sh:hasValue flow:START ] ;
        sh:message "This write is reachable from START without leaving the gate by ALLOW." ;
    ] .
"""
)

# The shape that does not work: kept to show why.
OBVIOUS_SHAPE = (
    PREFIXES
    + """
flow:ObviousShape a sh:NodeShape ;
    sh:targetClass flow:Write ;
    sh:property [
        sh:path [ sh:oneOrMorePath [ sh:inversePath flow:next ] ] ;
        sh:qualifiedValueShape [ sh:class flow:Gate ] ;
        sh:qualifiedMinCount 1 ;
        sh:message "No gate among the ancestors of this write." ;
    ] .
"""
)

WRITE_WITHOUT_ALLOW = "ASK { flow:START flow:unchecked+ ?write . ?write a flow:Write }"
TOKEN_OFF_ALLOW_EDGE = """
ASK {
    ?node flow:writes flow:allow_token .
    FILTER NOT EXISTS { ?gate a flow:Gate ; flow:allow ?node }
}"""
PROPOSAL_CHANGED_AFTER_ALLOW = """
ASK {
    ?gate a flow:Gate ; flow:allow ?after .
    ?after flow:next* ?node .
    ?node flow:writes flow:proposal ; flow:next+ ?write .
    ?write a flow:Write .
}"""


def graph_to_rdf(ir) -> Graph:
    """The workflow graph in gebra's document as triples. Only BY_HAND is added to it."""
    doc = ir.model_dump(mode="json", by_alias=True)
    rdf = Graph()
    rdf.bind("flow", FLOW)
    gate, allow = BY_HAND["gate"], BY_HAND["allow label"]

    def edge(source: str, target: str, label: str | None = None) -> None:
        rdf.add((FLOW[source], FLOW.next, FLOW[target]))
        kind = FLOW.allow if source == gate and label == allow else FLOW.unchecked
        rdf.add((FLOW[source], kind, FLOW[target]))

    for first in _as_list(doc["entry"]):
        edge("START", first)
    for item in doc["edges"]:
        if item.get("path_map"):
            for label, target in item["path_map"].items():
                edge(item["from"], target, label)
        else:
            for target in _as_list(item.get("to")):
                edge(item["from"], target)
    for last in _as_list(doc.get("finish")):
        edge(last, "END")

    rdf.add((FLOW[gate], RDF.type, FLOW.Gate))
    for node in doc["nodes"]:
        rdf.add((FLOW[node["id"]], RDF.type, FLOW.Node))
        notes = node.get("annotations") or {}
        if WRITE_TAGS & set(notes.get("effect") or []):
            rdf.add((FLOW[node["id"]], RDF.type, FLOW.Write))
        for key in notes.get("output") or []:
            rdf.add((FLOW[node["id"]], FLOW.writes, FLOW[key]))
    return rdf


def conforms(rdf: Graph, shape: str) -> bool:
    """Validate with pySHACL, inference switched off."""
    shapes = Graph().parse(data=shape, format="turtle")
    result, _report, _text = validate(rdf, shacl_graph=shapes, inference="none")
    return bool(result)


def ask(rdf: Graph, query: str) -> bool:
    return bool(rdf.query(query, initNs={"flow": FLOW}).askAnswer)


def extract(graph, sidecar: str | Path) -> Graph:
    return graph_to_rdf(gebra.extract(graph, sidecar=str(sidecar)).ir)


# The five graphs of the check matrix, each with its own sidecar.
# Expected: (obvious shape conforms, rule shape conforms, a write reachable without ALLOW).
VARIANT_ROWS = {
    "correct": ("gebra.toml", (True, True, False)),
    "bypass": ("gebra.toml", (True, False, True)),
    "defect": ("sidecars/defect.toml", (True, False, True)),
    "uncapped": ("gebra.toml", (True, True, False)),
    "no-escalate": ("gebra.toml", (True, True, False)),
}

# The token graphs of allow_token.py.
# Expected: (a write reachable without ALLOW, the token written off the ALLOW edge,
#            the proposal changed after ALLOW).
TOKEN_ROWS = {
    "correct, with token": (False, False, False),
    "bypass, with token": (True, False, False),
    "defect, with token": (True, False, False),
    "token written before the gate": (False, True, False),
    "token written before a bypass": (True, True, False),
    "proposal changed after ALLOW": (False, False, True),
}


def variant_row(variant: str, root: str | Path = ".") -> tuple[bool, bool, bool]:
    sidecar, _expected = VARIANT_ROWS[variant]
    rdf = extract(build_graph(variant), Path(root) / sidecar)
    return (
        conforms(rdf, OBVIOUS_SHAPE),
        conforms(rdf, RULE_SHAPE),
        ask(rdf, WRITE_WITHOUT_ALLOW),
    )


def token_row(name: str, directory: str | Path | None = None) -> tuple[bool, bool, bool]:
    build, write_node = TOKEN_GRAPHS[name]
    rdf = extract(build().compile(), write_sidecar(sidecar_text(write_node), directory))
    return (
        ask(rdf, WRITE_WITHOUT_ALLOW),
        ask(rdf, TOKEN_OFF_ALLOW_EDGE),
        ask(rdf, PROPOSAL_CHANGED_AFTER_ALLOW),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="directory holding gebra.toml and sidecars/")
    args = parser.parse_args(argv)
    differ = []

    header = (
        f"{'graph':14}{'obvious shape':22}{'rule shape':12}{'write reachable without ALLOW':31}"
    )
    print("the five graphs of the check matrix, each with its own sidecar")
    print(header + "as expected")
    print("-" * len(header + "as expected"))
    for variant, (_sidecar, expected) in VARIANT_ROWS.items():
        row = variant_row(variant, args.root)
        obvious, rule, reachable = row
        obvious_cell = "pass" if obvious else "violation"
        if obvious and reachable:
            obvious_cell = "pass, which is wrong"
        print(
            f"{variant:14}{obvious_cell:22}{'pass' if rule else 'violation':12}"
            f"{_yes(reachable):31}{_yes(row == expected)}"
        )
        if row != expected:
            differ.append(variant)

    print()
    header = (
        f"{'graph':32}{'write reachable without ALLOW':31}{'token written off the ALLOW edge':34}"
        f"{'proposal changed after ALLOW':30}"
    )
    print("the token graphs, each with a sidecar that declares the token")
    print(header + "as expected")
    print("-" * len(header + "as expected"))
    for name, expected in TOKEN_ROWS.items():
        row = token_row(name)
        cells = "".join(
            f"{_yes(value):{width}}" for value, width in zip(row, (31, 34, 30), strict=True)
        )
        print(f"{name:32}{cells}{_yes(row == expected)}")
        if row != expected:
            differ.append(name)

    if differ:
        print("\nrows that differ from what is expected: " + ", ".join(differ))
        return 1
    print("\nevery row is as expected")
    return 0


def _as_list(value) -> list[str]:
    if value is None:
        return []
    return [item for item in (value if isinstance(value, list) else [value]) if item]


def _yes(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    sys.exit(main())
