"""The experiment: the workflow graph as RDF, read by gebra and checked with SHACL."""

from pathlib import Path

import pytest
from rdflib import RDF

from ontology_gate.graph import build_graph
from ontology_gate.graph_as_rdf import (
    BY_HAND,
    FLOW,
    TOKEN_ROWS,
    VARIANT_ROWS,
    extract,
    main,
    token_row,
    variant_row,
)

ROOT = Path(__file__).resolve().parents[1]

# The brief's tables, written out here so a change in the module cannot move them.
EXPECTED_VARIANTS = {
    "correct": (True, True, False),
    "bypass": (True, False, True),
    "defect": (True, False, True),
    "uncapped": (True, True, False),
    "no-escalate": (True, True, False),
}
EXPECTED_TOKENS = {
    "correct, with token": (False, False, False),
    "bypass, with token": (True, False, False),
    "defect, with token": (True, False, False),
    "token written before the gate": (False, True, False),
    "token written before a bypass": (True, True, False),
    "proposal changed after ALLOW": (False, False, True),
}


def test_the_expected_rows_are_the_tables():
    assert {name: row for name, (_, row) in VARIANT_ROWS.items()} == EXPECTED_VARIANTS
    assert TOKEN_ROWS == EXPECTED_TOKENS


@pytest.mark.parametrize("variant", EXPECTED_VARIANTS)
def test_variant_rows(variant):
    assert variant_row(variant, ROOT) == EXPECTED_VARIANTS[variant]


@pytest.mark.parametrize("name", EXPECTED_TOKENS)
def test_token_rows(tmp_path, name):
    assert token_row(name, tmp_path) == EXPECTED_TOKENS[name]


def test_only_the_gate_and_its_allow_label_are_typed_by_hand():
    assert BY_HAND == {"gate": "gate", "allow label": "allow"}
    rdf = extract(build_graph("correct"), ROOT / "gebra.toml")
    assert set(rdf.subjects(RDF.type, FLOW.Gate)) == {FLOW.gate}
    assert set(rdf.subjects(RDF.type, FLOW.Write)) == {FLOW.commit_refund}
    assert set(rdf.objects(FLOW.gate, FLOW.allow)) == {FLOW.commit_refund}
    # Every edge is a next statement, and exactly one of them is not unchecked.
    edges = set(rdf.subject_objects(FLOW.next))
    assert edges - set(rdf.subject_objects(FLOW.unchecked)) == {(FLOW.gate, FLOW.commit_refund)}
    assert (FLOW.door, FLOW.gate) in edges


def test_make_rdf_exits_zero(capsys):
    assert main(["--root", str(ROOT)]) == 0
    out = capsys.readouterr().out
    assert "every row is as expected" in out
    assert "pass, which is wrong" in out
