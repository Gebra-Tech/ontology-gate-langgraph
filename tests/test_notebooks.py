"""Run both notebooks with the network blocked and check what their ✅ / ❌ lines say."""

import json
import sys
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell

from tests.conftest import GUARD_SOURCE

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ROOT / "notebooks"
KERNEL = "ontology-gate-tests"

sys.path.insert(0, str(ROOT / "tools"))
import make_student  # noqa: E402


@pytest.fixture(scope="module")
def kernel_path(tmp_path_factory):
    """A kernel spec that runs this interpreter, so the notebooks see this environment."""
    base = tmp_path_factory.mktemp("jupyter")
    spec = base / "kernels" / KERNEL
    spec.mkdir(parents=True)
    argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
    (spec / "kernel.json").write_text(
        json.dumps({"argv": argv, "display_name": KERNEL, "language": "python"})
    )
    return base


def execute(name: str, kernel_path: Path, monkeypatch, workdir: Path):
    monkeypatch.setenv("JUPYTER_PATH", str(kernel_path))
    notebook = nbformat.read(NOTEBOOKS / name, as_version=4)
    notebook.cells.insert(0, new_code_cell(GUARD_SOURCE))
    client = NotebookClient(
        notebook,
        kernel_name=KERNEL,
        timeout=600,
        resources={"metadata": {"path": str(workdir)}},
    )
    client.execute()
    return notebook.cells[1:]


def check_lines(cells, your_turn: bool | None = None) -> list[str]:
    lines = []
    for cell in cells:
        if cell.cell_type != "code":
            continue
        if your_turn is not None and ("your-turn" in cell.metadata.get("tags", [])) != your_turn:
            continue
        for output in cell.get("outputs", []):
            text = output.get("text", "")
            lines += [line for line in text.splitlines() if line.startswith(("✅", "❌"))]
    return lines


def test_solution_prints_only_ticks(kernel_path, monkeypatch, tmp_path):
    cells = execute("refund_gate_SOLUTION.ipynb", kernel_path, monkeypatch, tmp_path)
    lines = check_lines(cells)
    assert len(lines) == 9
    assert all(line.startswith("✅") for line in lines), lines
    assert list(tmp_path.iterdir()) == []  # nothing written next to the notebook


def test_student_runs_and_every_your_turn_check_fails(kernel_path, monkeypatch, tmp_path):
    cells = execute("refund_gate_STUDENT.ipynb", kernel_path, monkeypatch, tmp_path)
    lines = check_lines(cells, your_turn=True)
    assert len(lines) == 9
    assert all(line.startswith("❌") for line in lines), lines
    # Sync points keep the rest of the notebook working: no other check exists to fail.
    assert check_lines(cells, your_turn=False) == []


def test_student_is_built_from_solution():
    solution = nbformat.read(NOTEBOOKS / "refund_gate_SOLUTION.ipynb", as_version=4)
    committed = (NOTEBOOKS / "refund_gate_STUDENT.ipynb").read_text(encoding="utf-8")
    assert make_student.render(make_student.build_student(solution)) == committed
    assert "Student edition" in committed and "Solution edition" not in committed
    assert "# BLANK" not in committed


def test_committed_notebooks_have_no_outputs():
    for path in NOTEBOOKS.glob("*.ipynb"):
        for cell in nbformat.read(path, as_version=4).cells:
            if cell.cell_type == "code":
                assert cell.outputs == [] and cell.execution_count is None, path.name


def test_blank_markers():
    source = (
        'X = "answer"  # BLANK\n'
        "def f():\n"
        "    # BLANK-START\n"
        "    a = 1\n"
        "    return a\n"
        "    # BLANK-END\n"
        "Y = 2"
    )
    assert make_student.blank_source(source) == "X = ____\ndef f():\n    ____\nY = 2"
    with pytest.raises(ValueError):
        make_student.blank_source("print('x')  # BLANK")
