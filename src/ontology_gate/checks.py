"""gebra's structural checks on the refund graphs, before anything runs.

``run_gebra`` extracts one graph with one sidecar and returns the result of the five
properties gebra 0.1.1 implements. ``python -m ontology_gate.checks`` (``make check``)
prints the matrix of every configuration and exits non-zero if a row differs from what this
repository expects.

gebra reads the graph definition and the sidecar declarations. It never runs a node, and it
trusts what the sidecar declares without checking it.
"""

import argparse
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import gebra
from gebra.verify import to_data, verify

from ontology_gate.graph import build_graph

PROPERTIES = {
    "P-01": "graph-well-formed",
    "P-02": "termination-witness",
    "P-04": "dataflow-completeness",
    "P-06": "effect-safety",
    "P-08": "determinism-replay",
}

Outcome = tuple[str, str | None]


def run_gebra(graph, sidecar_path: str | Path) -> dict:
    """Extract ``graph`` with an explicit sidecar and run gebra's checks on it.

    Returns ``{property id: (result, failure code or None)}`` for P-01, P-02, P-04, P-06 and
    P-08, plus ``"locations"`` (property id -> nodes named by the failure) and ``"warnings"``
    (extraction warnings as ``(code, node, slots)``).

    Always pass a sidecar: without one, gebra looks for a gebra.toml from the current
    directory up to the repository root, and would find this repository's own file.
    """
    envelope = gebra.extract(graph, sidecar=str(sidecar_path))
    report = verify(envelope.ir)
    outcome: dict = {"locations": {}, "warnings": []}
    for pid, slug in PROPERTIES.items():
        result = report.outcome_for(slug)
        failure = getattr(result, "failure", None)
        code = failure.property_condition if failure is not None else None
        outcome[pid] = (result.result, code)
        if failure is not None:
            outcome["locations"][pid] = _nodes(to_data(failure.location))
    outcome["warnings"] = [
        (warning.code.value, warning.node, tuple(warning.slots)) for warning in envelope.warnings
    ]
    return outcome


def write_sidecar(text: str, directory: str | Path | None = None) -> Path:
    """Write sidecar text to a temporary file and return its path (used by the notebooks)."""
    folder = Path(directory) if directory else Path(tempfile.mkdtemp(prefix="gebra-sidecar-"))
    path = folder / "gebra.toml"
    path.write_text(text, encoding="utf-8")
    return path


def describe_outcome(outcome: dict, ids: tuple[str, ...] = ("P-01", "P-02", "P-06")) -> str:
    """A few lines of plain text for one run of run_gebra."""
    lines = []
    for pid in ids:
        result, code = outcome[pid]
        line = f"{pid} {PROPERTIES[pid]:22} {result}"
        if code:
            where = ", ".join(outcome["locations"].get(pid, []))
            line += f"  {code}" + (f" ({where})" if where else "")
        lines.append(line)
    return "\n".join(lines)


@dataclass(frozen=True)
class Configuration:
    label: str
    variant: str
    sidecar: str
    expected: dict[str, Outcome]
    note: str


PASS: Outcome = ("pass", None)
NO_WITNESS: Outcome = ("fail", "cycle-without-termination-witness")


def _expect(p01=PASS, p02=PASS, p04=PASS, p06=PASS, p08=PASS) -> dict[str, Outcome]:
    return {"P-01": p01, "P-02": p02, "P-04": p04, "P-06": p06, "P-08": p08}


CONFIGURATIONS = (
    Configuration(
        "correct, no sidecar",
        "correct",
        "sidecars/none.toml",
        _expect(p02=NO_WITNESS),
        "the repair loop declares no bound; no effect is declared, so P-06 has nothing to check",
    ),
    Configuration(
        "correct, gebra.toml",
        "correct",
        "gebra.toml",
        _expect(),
        "bound declared on gate; commit_refund is outside the loop",
    ),
    Configuration(
        "defect, defect.toml",
        "defect",
        "sidecars/defect.toml",
        _expect(p06=("fail", "unprotected-effect-in-cycle")),
        "execute_refund is billable and irreversible inside the loop, with no protection",
    ),
    Configuration(
        "defect, defect-idempotent.toml",
        "defect",
        "sidecars/defect-idempotent.toml",
        _expect(),
        "the declared idempotency key on order_id is accepted; it is trusted, not checked",
    ),
    Configuration(
        "correct, negative-control.toml",
        "correct",
        "sidecars/negative-control.toml",
        _expect(p02=NO_WITNESS),
        "the variant names a key that is not in the state, so it is not a bound",
    ),
    Configuration(
        "no-escalate, gebra.toml",
        "no-escalate",
        "gebra.toml",
        _expect(p01=("fail", "node-unreachable-from-start")),
        "nothing routes to human_review",
    ),
    Configuration(
        "uncapped, gebra.toml",
        "uncapped",
        "gebra.toml",
        _expect(),
        "limit: the declared bound is trusted, but the router no longer enforces it",
    ),
    Configuration(
        "bypass, gebra.toml",
        "bypass",
        "gebra.toml",
        _expect(),
        "pass (gate ordering not checked in 0.1.1; planned)",
    ),
)


def check_matrix(root: str | Path = ".") -> list[tuple[Configuration, dict]]:
    """Run gebra on every configuration. Sidecar paths are relative to ``root``."""
    base = Path(root)
    return [
        (config, run_gebra(build_graph(config.variant), base / config.sidecar))
        for config in CONFIGURATIONS
    ]


def matches(config: Configuration, outcome: dict) -> bool:
    return all(outcome[pid] == expected for pid, expected in config.expected.items())


def format_matrix(rows: list[tuple[Configuration, dict]]) -> str:
    header = f"{'configuration':34}" + "".join(f"{pid:6}" for pid in PROPERTIES) + "as expected"
    lines = [header, "-" * len(header)]
    for config, outcome in rows:
        cells = "".join(f"{outcome[pid][0]:6}" for pid in PROPERTIES)
        lines.append(f"{config.label:34}{cells}{'yes' if matches(config, outcome) else 'NO'}")
    lines += ["", "findings"]
    for config, outcome in rows:
        found = [
            f"{pid} {outcome[pid][1]} ({', '.join(outcome['locations'].get(pid, []))})"
            for pid in PROPERTIES
            if outcome[pid][1]
        ]
        lines.append(f"  {config.label}: {'; '.join(found) or 'none'}")
        lines.append(f"    {config.note}")
    warnings = Counter(code for code, _node, _slots in rows[1][1]["warnings"])
    lines += [
        "",
        "extraction warnings on the correct graph with gebra.toml: "
        + (", ".join(f"{code} x{count}" for code, count in sorted(warnings.items())) or "none"),
        "  (gebra inferred or defaulted these contract slots; warnings never change a result)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="directory holding gebra.toml and sidecars/")
    args = parser.parse_args(argv)
    rows = check_matrix(args.root)
    print(format_matrix(rows))
    mismatched = [config.label for config, outcome in rows if not matches(config, outcome)]
    if mismatched:
        print("\nrows that differ from the expected matrix: " + ", ".join(mismatched))
        return 1
    print("\nevery row matches the expected matrix")
    return 0


def _nodes(location: dict) -> list[str]:
    if location.get("node"):
        return [location["node"]]
    return list(location.get("nodes", []))


if __name__ == "__main__":
    sys.exit(main())
