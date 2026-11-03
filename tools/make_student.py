"""Build the STUDENT notebook from the SOLUTION notebook, so the two never drift.

In SOLUTION code cells:

* a line ending in ``# BLANK`` is an assignment whose value is the answer:
  ``ALLOW_TARGET = "commit_refund"  # BLANK`` becomes ``ALLOW_TARGET = ____``;
* lines between ``# BLANK-START`` and ``# BLANK-END`` are a multi-line answer, replaced by
  one ``____`` line at the indentation of the first answer line.

The title cell's "Solution edition" becomes "Student edition", and every output is cleared.
The result is byte-stable: building twice from the same SOLUTION gives the same file.

    python tools/make_student.py          write notebooks/refund_gate_STUDENT.ipynb
    python tools/make_student.py --check  exit 1 if the committed STUDENT is out of date
"""

import argparse
import re
import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parents[1]
SOLUTION = ROOT / "notebooks" / "refund_gate_SOLUTION.ipynb"
STUDENT = ROOT / "notebooks" / "refund_gate_STUDENT.ipynb"

BLANK = "____"
LINE_MARK = re.compile(r"^(?P<target>\s*[A-Za-z_][\w.\[\]\"']*\s*=\s*)(?P<value>.+?)\s+# BLANK$")


def blank_source(source: str) -> str:
    out: list[str] = []
    in_block = False
    block_written = False
    for line in source.split("\n"):
        stripped = line.strip()
        if stripped == "# BLANK-START":
            in_block, block_written = True, False
            continue
        if stripped == "# BLANK-END":
            in_block = False
            continue
        if in_block:
            if not block_written:
                indent = line[: len(line) - len(line.lstrip())]
                out.append(indent + BLANK)
                block_written = True
            continue
        if line.rstrip().endswith("# BLANK"):
            match = LINE_MARK.match(line.rstrip())
            if match is None:
                raise ValueError(f"cannot blank this line (use NAME = value  # BLANK): {line!r}")
            out.append(match.group("target") + BLANK)
            continue
        out.append(line)
    if in_block:
        raise ValueError("a # BLANK-START block has no # BLANK-END")
    return "\n".join(out)


def build_student(solution: nbformat.NotebookNode) -> nbformat.NotebookNode:
    student = nbformat.from_dict(solution)
    for cell in student.cells:
        if cell.cell_type == "code":
            cell.source = blank_source(cell.source)
            cell.outputs = []
            cell.execution_count = None
        elif cell.cell_type == "markdown":
            cell.source = cell.source.replace("Solution edition", "Student edition")
    return student


def render(notebook: nbformat.NotebookNode) -> str:
    return nbformat.writes(notebook) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the STUDENT notebook.")
    parser.add_argument("--check", action="store_true", help="only compare, do not write")
    args = parser.parse_args(argv)
    text = render(build_student(nbformat.read(SOLUTION, as_version=4)))
    if args.check:
        current = STUDENT.read_text(encoding="utf-8") if STUDENT.exists() else ""
        if current != text:
            print(f"{STUDENT.name} is out of date: run python tools/make_student.py")
            return 1
        print(f"{STUDENT.name} is up to date")
        return 0
    STUDENT.write_text(text, encoding="utf-8")
    print(f"wrote {STUDENT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
