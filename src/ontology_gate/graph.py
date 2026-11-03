"""The refund agent as a LangGraph StateGraph, in every configuration the demo and notebooks use.

The correct graph::

    START -> agent -> gate --allow--> commit_refund -> END
                ^       |--repair--> agent
                        `--escalate--> human_review -> END

The gate returns its violations to the agent, which repairs its proposal. The refund is
written only after ALLOW, and the loop ends at human review after MAX_REPAIRS blocks.

All variants share the same node functions and use only declared edges: no Send, no
Command destinations and no subgraphs, so gebra can read every route.
"""

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ontology_gate.cases import get_case
from ontology_gate.gate import describe, gate
from ontology_gate.model import Model, ScriptedModel

MAX_REPAIRS = 3
BYPASS_THRESHOLD = 50
VARIANTS = ("correct", "defect", "no-escalate", "bypass", "uncapped")


class RefundState(TypedDict):
    case: str
    order_id: str
    proposal: str
    violations: list[str]
    repair_attempts: int
    decision: str
    ledger: Annotated[list[dict[str, str]], operator.add]
    escalated: bool


def initial_state(case: str) -> RefundState:
    return {
        "case": case,
        "order_id": "",
        "proposal": "",
        "violations": [],
        "repair_attempts": 0,
        "decision": "",
        "ledger": [],
        "escalated": False,
    }


def make_agent(model: Model):
    """The agent node: propose a refund, seeing the violations of the last attempt."""

    def agent(state: RefundState) -> dict[str, Any]:
        case = get_case(state["case"])
        proposal = model.propose(case, state["violations"], state["repair_attempts"])
        order_id = describe(proposal).order_id or case.order_id
        return {"proposal": proposal, "order_id": order_id}

    return agent


def gate_node(state: RefundState) -> dict[str, Any]:
    """The gate node. The repair counter is incremented here, not in the router."""
    result = gate(state["proposal"])
    update: dict[str, Any] = {"decision": result.decision, "violations": result.violations}
    if result.decision == "BLOCK":
        update["repair_attempts"] = state["repair_attempts"] + 1
    return update


def commit_refund(state: RefundState) -> dict[str, Any]:
    """The write: pay the refund. Here it only appends to the in-memory ledger."""
    return {"ledger": [_ledger_entry(state)]}


def execute_refund(state: RefundState) -> dict[str, Any]:
    """The same write, placed before the gate in the defect graph."""
    return {"ledger": [_ledger_entry(state)]}


def human_review(state: RefundState) -> dict[str, Any]:
    """Hand the case to a person, with the violations that stopped the agent."""
    return {"escalated": True, "violations": list(state["violations"])}


def route_after_gate(state: RefundState) -> str:
    if state["decision"] == "ALLOW":
        return "allow"
    if state["repair_attempts"] < MAX_REPAIRS:
        return "repair"
    return "escalate"


def route_without_cap(state: RefundState) -> str:
    """Never escalates: every BLOCK goes back to the agent."""
    return "allow" if state["decision"] == "ALLOW" else "repair"


def route_after_agent(state: RefundState) -> str:
    """The bypass shortcut: small refunds skip the gate."""
    amount = describe(state["proposal"]).amount
    return "shortcut" if amount is not None and amount < BYPASS_THRESHOLD else "check"


GATE_ROUTES = {"allow": "commit_refund", "repair": "agent", "escalate": "human_review"}


def build_workflow(variant: str = "correct", model: Model | None = None) -> StateGraph:
    """The uncompiled StateGraph for one configuration. gebra can read this or the compiled one."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {', '.join(VARIANTS)}")
    workflow = StateGraph(RefundState)
    workflow.add_node("agent", make_agent(model or ScriptedModel()))
    workflow.add_node("gate", gate_node)
    workflow.add_node("human_review", human_review)
    workflow.add_edge(START, "agent")
    workflow.add_edge("human_review", END)

    if variant == "defect":
        # Validate after the tool ran: the refund is paid before the gate sees it.
        workflow.add_node("execute_refund", execute_refund)
        workflow.add_edge("agent", "execute_refund")
        workflow.add_edge("execute_refund", "gate")
        workflow.add_conditional_edges(
            "gate",
            route_after_gate,
            {"allow": END, "repair": "agent", "escalate": "human_review"},
        )
        return workflow

    workflow.add_node("commit_refund", commit_refund)
    workflow.add_edge("commit_refund", END)
    if variant == "bypass":
        workflow.add_conditional_edges(
            "agent", route_after_agent, {"shortcut": "commit_refund", "check": "gate"}
        )
    else:
        workflow.add_edge("agent", "gate")

    if variant == "no-escalate":
        # human_review stays in the graph, but nothing routes to it.
        workflow.add_conditional_edges(
            "gate", route_without_cap, {"allow": "commit_refund", "repair": "agent"}
        )
    elif variant == "uncapped":
        workflow.add_conditional_edges("gate", route_without_cap, GATE_ROUTES)
    else:
        workflow.add_conditional_edges("gate", route_after_gate, GATE_ROUTES)
    return workflow


def build_graph(variant: str = "correct", model: Model | None = None):
    """The compiled graph, with no checkpointer."""
    return build_workflow(variant, model).compile()


@dataclass
class CaseRun:
    """What happened when one case ran: one (decision, violations) pair per gate visit."""

    case: str
    attempts: list[tuple[str, list[str]]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def ledger(self) -> list[dict[str, str]]:
        return self.state.get("ledger", [])

    @property
    def escalated(self) -> bool:
        return bool(self.state.get("escalated"))


def run_case(graph, case: str, recursion_limit: int = 25) -> CaseRun:
    """Run one case to the end. Raises GraphRecursionError if the run exceeds the limit."""
    run = CaseRun(case=case)
    for mode, chunk in graph.stream(
        initial_state(case),
        {"recursion_limit": recursion_limit},
        stream_mode=["updates", "values"],
    ):
        if mode == "values":
            run.state = chunk
        elif "gate" in chunk:
            update = chunk["gate"]
            run.attempts.append((update["decision"], list(update["violations"])))
    return run


def _ledger_entry(state: RefundState) -> dict[str, str]:
    return {
        "case": state["case"],
        "order_id": state["order_id"],
        "refund_id": describe(state["proposal"]).refund_id or "unknown",
    }
