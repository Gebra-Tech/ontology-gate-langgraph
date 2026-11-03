"""The models that propose refunds.

``ScriptedModel`` is the default: it replays a fixed plan per case, so the demo, the tests and
the notebooks run offline and print the same thing every time. ``LiveModel`` asks a hosted
model instead; it needs the ``live`` extra and ANTHROPIC_API_KEY, and its results vary.
"""

import os
import re
from typing import Protocol

from ontology_gate.cases import Case
from ontology_gate.ontology import KB_TTL, SCHEMA_TTL

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
