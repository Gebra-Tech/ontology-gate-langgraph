"""The token workaround from gebra's guide, on the refund graphs, with its two gaps.

gebra 0.2.0 has no rule of its own for gate ordering. Its adopter guide, in the section "An
approval gate in front of a write", describes a workaround: the gate's ALLOW branch writes a
token, and the write declares that it reads it. A route that reaches the write without passing
the ALLOW branch is then a route on which the write reads a key nothing on that route wrote, and
P-04 ``dataflow-completeness`` reports it as ``read-key-never-written-on-path``.

Here the state gets an ``allow_token`` key that the input schema leaves out,
``StateGraph(TokenState, input_schema=RefundState)``, so no caller can supply it. The node
``issue_token`` sits on the ALLOW edge and is the one node declared to write it. The write
declares ``allow_token`` among its reads in the sidecar (``sidecar_text``).

What P-04 then reports, on the graphs in ``TOKEN_GRAPHS``:

* the gated graph passes;
* the bypass graph and the graph that pays before the gate fail P-04 at the write;
* two broken graphs pass, and these are the workaround's two gaps: a token written before the
  gate, which every route then carries, and a proposal changed after ALLOW, which the token does
  not cover.

This is P-04 answering its own question about a key the graph declares. It is not a rule about
gate ordering, and nothing in it knows which node is the gate.

At run time the write also compares the token with the proposal it is about to pay and refuses
on a mismatch. That comparison is this repository's code. gebra never runs it and does not see
it; it sees only the declared read.
"""

import hashlib
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from ontology_gate.checks import run_gebra, write_sidecar
from ontology_gate.graph import (
    RefundState,
    door_node,
    gate_node,
    human_review,
    ledger_entry,
    make_agent,
    route_after_agent,
    route_after_gate,
)
from ontology_gate.model import Model, RepairingModel


class TokenState(RefundState):
    """The refund state plus the token. The input schema stays RefundState."""

    allow_token: str


def token_for(proposal: str) -> str:
    """The token for one proposal: a short digest of its exact text."""
    return hashlib.sha256(proposal.encode("utf-8")).hexdigest()[:12]


def issue_token(state: TokenState) -> dict[str, Any]:
    """On the ALLOW edge: record which proposal the gate allowed."""
    return {"allow_token": token_for(state["proposal"])}


def commit_refund(state: TokenState) -> dict[str, Any]:
    """The write. It pays only when the token matches the proposal it is about to pay."""
    if state.get("allow_token") != token_for(state["proposal"]):
        return {"decision": "REFUSED"}
    return {"ledger": [ledger_entry(state)]}


def execute_refund(state: TokenState) -> dict[str, Any]:
    """The same write, placed before the gate."""
    if state.get("allow_token") != token_for(state["proposal"]):
        return {"decision": "REFUSED"}
    return {"ledger": [ledger_entry(state)]}


def rewrite_proposal(state: TokenState) -> dict[str, Any]:
    """A node after ALLOW that changes what the gate checked: the AI agent becomes the approver."""
    proposal = state["proposal"]
    for manager in ("shop:marco", "shop:priya"):
        proposal = proposal.replace(manager, "shop:shopbot")
    return {"proposal": proposal}


GATE_TO_TOKEN = {"allow": "issue_token", "repair": "agent", "escalate": "human_review"}
GATE_TO_WRITE = {"allow": "commit_refund", "repair": "agent", "escalate": "human_review"}


def _base(model: Model | None) -> StateGraph:
    workflow = StateGraph(TokenState, input_schema=RefundState)
    workflow.add_node("agent", make_agent(model or RepairingModel()))
    workflow.add_node("door", door_node)
    workflow.add_node("gate", gate_node)
    workflow.add_node("issue_token", issue_token)
    workflow.add_node("human_review", human_review)
    workflow.add_edge(START, "agent")
    workflow.add_edge("human_review", END)
    return workflow


def gated(model: Model | None = None) -> StateGraph:
    """agent -> door -> gate --allow--> issue_token -> commit_refund."""
    workflow = _base(model)
    workflow.add_node("commit_refund", commit_refund)
    workflow.add_edge("agent", "door")
    workflow.add_edge("door", "gate")
    workflow.add_conditional_edges("gate", route_after_gate, GATE_TO_TOKEN)
    workflow.add_edge("issue_token", "commit_refund")
    workflow.add_edge("commit_refund", END)
    return workflow


def bypass(model: Model | None = None) -> StateGraph:
    """The gated graph plus the shortcut: small refunds go from the agent to the write."""
    workflow = _base(model)
    workflow.add_node("commit_refund", commit_refund)
    workflow.add_conditional_edges(
        "agent", route_after_agent, {"shortcut": "commit_refund", "check": "door"}
    )
    workflow.add_edge("door", "gate")
    workflow.add_conditional_edges("gate", route_after_gate, GATE_TO_TOKEN)
    workflow.add_edge("issue_token", "commit_refund")
    workflow.add_edge("commit_refund", END)
    return workflow


def defect(model: Model | None = None) -> StateGraph:
    """The refund is paid before the gate, inside the repair loop."""
    workflow = _base(model)
    workflow.add_node("execute_refund", execute_refund)
    workflow.add_edge("agent", "door")
    workflow.add_edge("door", "execute_refund")
    workflow.add_edge("execute_refund", "gate")
    workflow.add_conditional_edges("gate", route_after_gate, GATE_TO_TOKEN)
    workflow.add_edge("issue_token", END)
    return workflow


def token_before_gate(model: Model | None = None) -> StateGraph:
    """Gap one: the token is written before the gate has decided, so every route carries it."""
    workflow = _base(model)
    workflow.add_node("commit_refund", commit_refund)
    workflow.add_edge("agent", "door")
    workflow.add_edge("door", "issue_token")
    workflow.add_edge("issue_token", "gate")
    workflow.add_conditional_edges("gate", route_after_gate, GATE_TO_WRITE)
    workflow.add_edge("commit_refund", END)
    return workflow


def token_before_bypass(model: Model | None = None) -> StateGraph:
    """Gap one again, with the shortcut: the token is written, then small refunds skip the gate."""
    workflow = _base(model)
    workflow.add_node("commit_refund", commit_refund)
    workflow.add_edge("agent", "issue_token")
    workflow.add_conditional_edges(
        "issue_token", route_after_agent, {"shortcut": "commit_refund", "check": "door"}
    )
    workflow.add_edge("door", "gate")
    workflow.add_conditional_edges("gate", route_after_gate, GATE_TO_WRITE)
    workflow.add_edge("commit_refund", END)
    return workflow


def proposal_changed_after_allow(model: Model | None = None) -> StateGraph:
    """Gap two: a node between ALLOW and the write changes the proposal."""
    workflow = _base(model)
    workflow.add_node("rewrite_proposal", rewrite_proposal)
    workflow.add_node("commit_refund", commit_refund)
    workflow.add_edge("agent", "door")
    workflow.add_edge("door", "gate")
    workflow.add_conditional_edges("gate", route_after_gate, GATE_TO_TOKEN)
    workflow.add_edge("issue_token", "rewrite_proposal")
    workflow.add_edge("rewrite_proposal", "commit_refund")
    workflow.add_edge("commit_refund", END)
    return workflow


# Each token graph, with the node that writes the refund.
TOKEN_GRAPHS = {
    "correct, with token": (gated, "commit_refund"),
    "bypass, with token": (bypass, "commit_refund"),
    "defect, with token": (defect, "execute_refund"),
    "token written before the gate": (token_before_gate, "commit_refund"),
    "token written before a bypass": (token_before_bypass, "commit_refund"),
    "proposal changed after ALLOW": (proposal_changed_after_allow, "commit_refund"),
}


def sidecar_text(write_node: str) -> str:
    """The sidecar for a token graph: the loop bound, the token's writer, and the write."""
    return f"""schema = "gebra-sidecar-v1"

[nodes.gate.variant]
key = "repair_attempts"
measure = "MAX_REPAIRS - repair_attempts: gate adds 1 per BLOCK, the router escalates at 3"

# The one node declared to write the token.
[nodes.issue_token]
reads = ["proposal"]
writes = ["allow_token"]

# The write declares the token among its reads.
[nodes.{write_node}]
reads = ["case", "order_id", "proposal", "allow_token"]
effects = ["billable", "irreversible"]
"""


def run_token_graph(name: str, directory: str | Path | None = None) -> dict:
    """run_gebra on one token graph, with its sidecar written to a temporary folder."""
    build, write_node = TOKEN_GRAPHS[name]
    return run_gebra(build().compile(), write_sidecar(sidecar_text(write_node), directory))
