from importlib.metadata import version
from pathlib import Path

import pytest

from ontology_gate.checks import CONFIGURATIONS, main, run_gebra, write_sidecar
from ontology_gate.graph import build_graph, build_workflow

ROOT = Path(__file__).resolve().parents[1]


def test_gebra_version_is_the_one_the_limits_describe():
    # The bypass row, notebook Part D and the README limits describe gebra 0.1.1.
    if version("gebra") != "0.1.1":
        pytest.fail("gebra upgraded: review the bypass row, notebook Part D and the README limits")


def test_bypass_passes_on_this_gebra():
    # gebra 0.1.1 does not check that every write passes through the gate's ALLOW branch.
    outcome = run_gebra(build_graph("bypass"), ROOT / "gebra.toml")
    for pid in ("P-01", "P-02", "P-04", "P-06", "P-08"):
        assert outcome[pid] == ("pass", None), pid


@pytest.mark.parametrize("config", CONFIGURATIONS, ids=[c.label for c in CONFIGURATIONS])
def test_each_configuration_matches_the_expected_row(config):
    outcome = run_gebra(build_graph(config.variant), ROOT / config.sidecar)
    for pid, expected in config.expected.items():
        assert outcome[pid] == expected, f"{config.label}: {pid}"


def test_findings_name_the_expected_nodes():
    loop = run_gebra(build_graph("correct"), ROOT / "sidecars/none.toml")
    assert loop["locations"]["P-02"] == ["agent", "gate"]
    effect = run_gebra(build_graph("defect"), ROOT / "sidecars/defect.toml")
    assert effect["locations"]["P-06"] == ["execute_refund"]
    unreachable = run_gebra(build_graph("no-escalate"), ROOT / "gebra.toml")
    assert unreachable["locations"]["P-01"] == ["human_review"]


def test_builder_and_compiled_graph_agree():
    for variant, sidecar in (("correct", "gebra.toml"), ("defect", "sidecars/defect.toml")):
        builder = run_gebra(build_workflow(variant), ROOT / sidecar)
        compiled = run_gebra(build_graph(variant), ROOT / sidecar)
        for pid in ("P-01", "P-02", "P-04", "P-06", "P-08"):
            assert builder[pid] == compiled[pid]


class ExplodingModel:
    def propose(self, case, violations, attempt):
        raise AssertionError("gebra must not run the agent")


def test_gebra_reads_the_graph_without_running_it():
    outcome = run_gebra(build_graph("correct", model=ExplodingModel()), ROOT / "gebra.toml")
    assert outcome["P-02"] == ("pass", None)


def test_sidecar_from_text(tmp_path):
    text = (ROOT / "gebra.toml").read_text(encoding="utf-8")
    path = write_sidecar(text, tmp_path)
    assert path.parent == tmp_path
    assert run_gebra(build_graph("correct"), path)["P-02"] == ("pass", None)


def test_make_check_exits_zero(capsys):
    assert main(["--root", str(ROOT)]) == 0
    assert "every row matches the expected matrix" in capsys.readouterr().out
