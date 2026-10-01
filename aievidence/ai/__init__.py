"""AI touchpoints. The AI is pluggable and, for the evidence record, irrelevant.

Every adapter exposes the four provenance fields the ledger needs (``model_id``,
``model_version``, ``prompt_hash``, and per-call ``inputs_hash``) and one
``run(record)`` method. Swapping a stub for a frontier model changes the
``agent`` block of the events; it changes nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..ledger import canonical, sha256


@dataclass(frozen=True)
class AIOutput:
    """What a model proposed, and the hash of exactly what it saw.

    ``value`` is ``None`` when the model had nothing to propose (for the query
    generator: no data problem found). ``inputs_hash`` is the SHA-256 of the
    canonical JSON of the record fields the model was given, so an inspector
    can confirm the record has not changed since the model read it.
    """

    value: Any
    confidence: float
    rationale: str | None
    inputs_hash: str


@runtime_checkable
class AIAdapter(Protocol):
    model_id: str
    model_version: str
    prompt_hash: str

    def run(self, record: dict) -> AIOutput: ...


def inputs_hash(record: dict, fields: list[str]) -> str:
    """SHA-256 over the subset of ``record`` the model is given, in canonical form."""
    return sha256(canonical({f: record.get(f) for f in fields}))


def prompt_hash(template: str) -> str:
    return sha256(template.encode("utf-8"))


__all__ = ["AIAdapter", "AIOutput", "inputs_hash", "prompt_hash"]
