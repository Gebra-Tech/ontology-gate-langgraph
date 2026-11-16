"""The models that propose refunds.

``RepairingModel`` is the default. It runs offline and reads the gate's messages: its first
proposal comes from the case, and each later one is computed from the last messages and the
knowledge base, so the demo, the tests and the notebooks print the same thing every time.
``ScriptedModel`` replays a fixed plan per case and ignores the messages. ``LiveModel`` asks a
hosted model instead; it needs the ``live`` extra and ANTHROPIC_API_KEY, and its results vary.
"""

import os
import re
from typing import Protocol

from rdflib import RDF, Namespace

from ontology_gate.cases import Case
from ontology_gate.door import parse_turtle
from ontology_gate.ontology import KB_TTL, NS, SCHEMA_TTL

SHOP = Namespace(NS)

# The messages that say the approver is the problem.
APPROVER_MESSAGES = frozenset(
    {
        "The approver does not exist.",
        "A refund needs an approver.",
        "Only a Manager may approve a refund.",
        "The approver must not be the person who requested the refund.",
    }
)

DEFAULT_LIVE_MODEL = "claude-haiku-5-5"


class Model(Protocol):
    def propose(self, case: Case, violations: list[str], attempt: int) -> str:
        """Return Turtle for one new refund. ``violations`` come from the last BLOCK."""
        ...


def refund_turtle(refund_id: str, case: Case, approver: str) -> str:
    """Turtle for one refund on the case's order, using the ``shop:`` prefix."""
    return (
        f"shop:{refund_id} a shop:Refund ;\n"
        f"    shop:forOrder    shop:{case.order_id} ;\n"
        f"    shop:requestedBy shop:{case.customer} ;\n"
        f"    shop:approvedBy  shop:{approver} ;\n"
        f"    shop:amount      {case.amount} .\n"
    )


def refund_id_for(case: Case, attempt: int) -> str:
    return f"rf_{case.order_id}_{attempt + 1}"


class ScriptedModel:
    """Replays one approver per attempt. The last approver repeats if the run keeps going."""

    APPROVERS: dict[str, tuple[str, ...]] = {
        "agent-approves": ("shopbot", "priya"),
        "self-approval": ("priya", "marco"),
        # The order already has a refund, so no approver can fix this one.
        "duplicate-refund": ("priya",),
        "small-refund": ("shopbot", "marco"),
    }

    def propose(self, case: Case, violations: list[str], attempt: int) -> str:
        approvers = self.APPROVERS[case.name]
        approver = approvers[min(attempt, len(approvers) - 1)]
        return refund_turtle(refund_id_for(case, attempt), case, approver)


class RepairingModel:
    """Proposes from the case, then repairs from the gate's messages and the knowledge base.

    After a BLOCK whose messages reject the approver, it names a Manager from the knowledge
    base other than the requester, the first by name. After any other BLOCK, such as an order
    that was already refunded, it changes nothing, because no field it controls can fix that.
    Each proposal gets a new refund id. It remembers its last approver per case, and starts
    again from the case on the first attempt.
    """

    def __init__(self, kb_ttl: str = KB_TTL) -> None:
        kb = parse_turtle(kb_ttl)
        self.managers = sorted(str(m).removeprefix(NS) for m in kb.subjects(RDF.type, SHOP.Manager))
        self._approvers: dict[str, str] = {}

    def propose(self, case: Case, violations: list[str], attempt: int) -> str:
        approver = self._approvers.get(case.name, case.approver)
        if attempt == 0:
            approver = case.approver
        elif APPROVER_MESSAGES & set(violations):
            others = [manager for manager in self.managers if manager != case.customer]
            approver = others[0] if others else approver
        self._approvers[case.name] = approver
        return refund_turtle(refund_id_for(case, attempt), case, approver)


SYSTEM_PROMPT = """\
You are the refund agent of a small webshop. You propose refunds as RDF Turtle.
Use only the shop: prefix (it is already declared). Reply with Turtle only, no prose and no
code fences. Describe exactly one shop:Refund with shop:forOrder, shop:requestedBy,
shop:approvedBy and shop:amount (an integer).
"""


class LiveModel:
    """Asks a hosted model for the proposal. Optional: never used by the tests."""

    def __init__(self, model_name: str | None = None) -> None:
        from langchain_anthropic import ChatAnthropic  # the "live" extra

        self.model_name = model_name or os.environ.get("ONTOLOGY_GATE_MODEL", DEFAULT_LIVE_MODEL)
        self._chat = ChatAnthropic(model=self.model_name, max_tokens=1024)

    def propose(self, case: Case, violations: list[str], attempt: int) -> str:
        feedback = (
            "Your last proposal was blocked by the policy gate:\n"
            + "\n".join(f"- {message}" for message in violations)
            + "\nRepair the proposal."
            if violations
            else "This is your first proposal."
        )
        prompt = (
            f"Schema:\n{SCHEMA_TTL}\nKnown facts:\n{KB_TTL}\n"
            f"Request: {case.request}\n"
            f"Use the refund id shop:{refund_id_for(case, attempt)}.\n"
            f"{feedback}"
        )
        reply = self._chat.invoke([("system", SYSTEM_PROMPT), ("human", prompt)])
        return strip_fences(reply.text)


def strip_fences(text: str) -> str:
    """Remove a Markdown code fence if the model added one anyway."""
    match = re.search(r"```(?:turtle|ttl)?\s*\n(.*?)```", text, flags=re.DOTALL)
    return (match.group(1) if match else text).strip() + "\n"
