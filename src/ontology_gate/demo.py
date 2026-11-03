"""Run the three cases on the refund graph and print what happened.

    python -m ontology_gate.demo            the correct graph
    python -m ontology_gate.demo --defect   the correct graph, then the defect graph
    python -m ontology_gate.demo --live     proposals from a hosted model instead of the script

Offline by default: the scripted model replays the same proposals every run.
"""

import argparse
import os
import sys
from collections import Counter

from ontology_gate.cases import DEMO_CASES, get_case
from ontology_gate.graph import CaseRun, build_graph, run_case
from ontology_gate.model import Model, ScriptedModel

TITLES = {
    "correct": "correct graph: the refund is written only after the gate says ALLOW",
    "defect": "defect graph: the refund is written before the gate has seen it",
}


def run_all(variant: str, model: Model) -> list[CaseRun]:
    graph = build_graph(variant, model)
    return [run_case(graph, case) for case in DEMO_CASES]


def format_run(variant: str, runs: list[CaseRun]) -> str:
    lines = [TITLES[variant], "=" * len(TITLES[variant]), ""]
    lines.append(f"{'case':18}{'attempt':9}{'decision':10}first violation")
    for run in runs:
        for number, (decision, violations) in enumerate(run.attempts, start=1):
            name = run.case if number == 1 else ""
            first = violations[0] if violations else ""
            lines.append(f"{name:18}{number:<9}{decision:10}{first}".rstrip())
        lines.append(f"{'':18}outcome: {outcome(run)}")
        lines.append("")
    lines.append("ledger (refunds paid)")
    entries = [entry for run in runs for entry in run.ledger]
    if not entries:
        lines.append("  none")
    for entry in entries:
        lines.append(f"  {entry['order_id']:7}{entry['refund_id']:13}{entry['case']}")
    return "\n".join(lines)


def outcome(run: CaseRun) -> str:
    paid = len(run.ledger)
    times = "once" if paid == 1 else f"{paid} times"
    if run.escalated:
        return "escalated to human review, " + ("nothing paid" if not paid else f"paid {times}")
    return f"{run.state.get('decision', '')}, paid {times}"


def summary_line(variant: str, runs: list[CaseRun]) -> str:
    paid = sum(len(run.ledger) for run in runs)
    escalated = sum(run.escalated for run in runs)
    per_order = Counter(entry["order_id"] for run in runs for entry in run.ledger)
    repeated = sorted(order for order, count in per_order.items() if count > 1)
    paid_then_escalated = [run for run in runs if run.escalated and run.ledger]
    if not repeated and not paid_then_escalated:
        return f"{variant}: {paid} refunds paid, {escalated} escalated, no order paid twice"
    parts = [
        f"{run.case.replace('-', ' ')} for {run.ledger[0]['order_id']} paid "
        f"{len(run.ledger)} times before escalation"
        for run in paid_then_escalated
    ]
    detail = f"{paid} payments in all, {len(repeated)} orders paid more than once"
    return f"{variant}: " + "; ".join(parts or [detail]) + (f" ({detail})" if parts else "")


def live_model() -> Model:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("--live needs ANTHROPIC_API_KEY in the environment.")
    try:
        from ontology_gate.model import LiveModel

        return LiveModel()
    except ImportError:
        sys.exit('--live needs the live extra: pip install "ontology-gate-langgraph[live]"')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the refund agent demo.")
    parser.add_argument("--defect", action="store_true", help="also run the defect graph")
    parser.add_argument("--live", action="store_true", help="use a hosted model (needs a key)")
    args = parser.parse_args(argv)

    model: Model = live_model() if args.live else ScriptedModel()
    if args.live:
        print(f"Live mode: proposals come from {model.model_name}. Results vary between runs.\n")
    print("Cases:")
    for case in DEMO_CASES:
        print(f"  {case:18}{get_case(case).request}")
    print()

    variants = ("correct", "defect") if args.defect else ("correct",)
    summaries = []
    for variant in variants:
        runs = run_all(variant, model)
        print(format_run(variant, runs))
        print()
        summaries.append(summary_line(variant, runs))
    print("summary")
    for line in summaries:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
