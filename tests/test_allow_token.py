"""The token workaround from gebra's guide, on the refund graphs, with its two gaps."""

import gebra
import pytest
from gebra.verify import to_data, verify

from ontology_gate.allow_token import TOKEN_GRAPHS, run_token_graph, sidecar_text
from ontology_gate.checks import write_sidecar
from ontology_gate.graph import run_case

PROPERTIES = ("P-01", "P-02", "P-04", "P-06", "P-08")
UNWRITTEN = ("fail", "read-key-never-written-on-path")


def test_the_gated_graph_passes(tmp_path):
    outcome = run_token_graph("correct, with token", tmp_path)
    assert all(outcome[pid] == ("pass", None) for pid in PROPERTIES)


@pytest.mark.parametrize(
    ("name", "write"),
    [("bypass, with token", "commit_refund"), ("defect, with token", "execute_refund")],
)
def test_a_write_reached_without_allow_fails_p04_at_the_write(tmp_path, name, write):
    outcome = run_token_graph(name, tmp_path)
    assert outcome["P-04"] == UNWRITTEN
    assert outcome["locations"]["P-04"] == [write]
    build, _ = TOKEN_GRAPHS[name]
    sidecar = write_sidecar(sidecar_text(write), tmp_path)
    envelope = gebra.extract(build().compile(), sidecar=str(sidecar))
    location = to_data(verify(envelope.ir).outcome_for("dataflow-completeness").failure.location)
    assert (location["node"], location["key"]) == (write, "allow_token")


@pytest.mark.parametrize(
    "name",
    [
        "token written before the gate",
        "token written before a bypass",
        "proposal changed after ALLOW",
    ],
)
def test_the_two_gaps_pass_p04(tmp_path, name):
    assert run_token_graph(name, tmp_path)["P-04"] == ("pass", None)


def run(name: str, case: str):
    build, _ = TOKEN_GRAPHS[name]
    return run_case(build().compile(), case)


def test_at_run_time_the_write_refuses_a_missing_or_stale_token():
    gated = run("correct, with token", "agent-approves")
    assert [entry["refund_id"] for entry in gated.ledger] == ["rf_o1002_2"]
    shortcut = run("bypass, with token", "small-refund")
    assert shortcut.attempts == [] and shortcut.ledger == []
    assert shortcut.state["decision"] == "REFUSED"
    changed = run("proposal changed after ALLOW", "agent-approves")
    assert changed.ledger == [] and changed.state["decision"] == "REFUSED"


def test_gap_one_at_run_time_a_token_written_before_a_bypass_pays_without_the_gate():
    shortcut = run("token written before a bypass", "small-refund")
    assert shortcut.attempts == []  # the gate never ran
    assert [entry["refund_id"] for entry in shortcut.ledger] == ["rf_o1004_1"]
