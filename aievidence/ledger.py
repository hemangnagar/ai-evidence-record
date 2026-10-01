"""Append-only, hash-chained JSONL ledger.

One JSON object per line. Each event carries the hash of the event before it
(``prev_hash``) and its own hash (``hash``), computed over the canonical JSON of
the event with ``prev_hash`` included. Editing any byte of any event, or removing
or reordering a line, breaks the chain at that point and ``verify()`` names the
first broken ``seq``.

Nothing is ever deleted. A correction is a new event that points at the old
``seq``. The only function that edits a line in place is ``tamper()``, which
exists so a demo audience can watch the chain break; it is not part of the
product surface and is labelled accordingly.

The schema borrows its vocabulary from W3C PROV: every event names an *agent*
(a model or a human), an *activity* (the event type) and an *entity* (the
record reference), so the ledger can be exported as PROV-JSON later without a
remodel.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64

EVENT_TYPES = frozenset({"ai_output", "review", "promote", "reject", "correction", "endorsement", "model_change"})
AGENT_KINDS = frozenset({"model", "human", "system"})


class LedgerError(Exception):
    """Raised when an event cannot be appended."""


def normalize(obj: Any) -> Any:
    """Make a value JSON-portable: integral floats become ints (``3.0`` -> ``3``).

    JavaScript's ``JSON.stringify`` has no ``3.0``, so without this a browser could
    never recompute the same hash as Python. Applied to every event before it is
    written and before it is hashed, so the file and the chain agree.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [normalize(v) for v in obj]
    return obj


def canonical(obj: Any) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, UTF-8, integral floats as ints.

    Hash this, never the pretty form. The output is byte-identical to
    ``JSON.stringify`` over sorted keys in JavaScript, which is what lets the
    browser workbench verify and extend the same chain.
    """
    return json.dumps(normalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    """UTC timestamp with millisecond precision and a trailing Z."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(UTC).microsecond // 1000:03d}Z"


def event_hash(event: dict) -> str:
    """SHA-256 of the canonical event with its own ``hash`` field removed."""
    body = {k: v for k, v in event.items() if k != "hash"}
    return sha256(canonical(body))


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    event_count: int
    head_hash: str
    first_broken_seq: int | None
    reason: str

    def __str__(self) -> str:
        if self.ok:
            return f"OK: {self.event_count} events, head {self.head_hash[:16]}…"
        return f"BROKEN at seq {self.first_broken_seq}: {self.reason}"


class Ledger:
    """A hash-chained JSONL file. Open it, append to it, verify it."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._seq, self._head = self._tail()

    # -- reading -----------------------------------------------------------

    def _tail(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, GENESIS
        last: dict | None = None
        for line in self._lines():
            last = json.loads(line)
        if last is None:
            return 0, GENESIS
        return int(last["seq"]), str(last["hash"])

    def _lines(self) -> list[str]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [line for line in f.read().splitlines() if line.strip()]

    def events(self) -> list[dict]:
        return [json.loads(line) for line in self._lines()]

    def __len__(self) -> int:
        return self._seq

    @property
    def head_hash(self) -> str:
        return self._head

    def get(self, seq: int) -> dict | None:
        for event in self.events():
            if event["seq"] == seq:
                return event
        return None

    # -- writing -----------------------------------------------------------

    def append(
        self,
        event_type: str,
        *,
        study_id: str,
        record_ref: str,
        field: str | None,
        agent: dict,
        payload: dict,
        ts: str | None = None,
    ) -> dict:
        if event_type not in EVENT_TYPES:
            raise LedgerError(f"unknown event_type {event_type!r}; expected one of {sorted(EVENT_TYPES)}")
        if agent.get("kind") not in AGENT_KINDS:
            raise LedgerError(f"agent.kind must be one of {sorted(AGENT_KINDS)}, got {agent.get('kind')!r}")
        if not agent.get("id"):
            raise LedgerError("agent.id is required")
        event = normalize(
            {
                "seq": self._seq + 1,
                "ts": ts or now_iso(),
                "event_type": event_type,
                "study_id": study_id,
                "record_ref": record_ref,
                "field": field,
                "agent": agent,
                "payload": payload,
                "prev_hash": self._head,
            }
        )
        event["hash"] = event_hash(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        self._seq, self._head = event["seq"], event["hash"]
        return event

    # -- integrity ---------------------------------------------------------

    def verify(self) -> VerifyResult:
        return verify_events(self.events())


def verify_events(events: list[dict]) -> VerifyResult:
    """Walk the chain. Returns OK or the first seq at which it breaks and why."""
    prev = GENESIS
    for expected_seq, event in enumerate(events, start=1):
        seq = event.get("seq")
        if seq != expected_seq:
            return VerifyResult(False, len(events), prev, expected_seq, f"expected seq {expected_seq}, found {seq}")
        if event.get("prev_hash") != prev:
            return VerifyResult(False, len(events), prev, seq, "prev_hash does not match the preceding event")
        if event_hash(event) != event.get("hash"):
            return VerifyResult(False, len(events), prev, seq, "stored hash does not match event content")
        prev = event["hash"]
    return VerifyResult(True, len(events), prev, None, "chain intact")


# -- demo only -----------------------------------------------------------------


def set_path(obj: dict, dotted: str, value: Any) -> None:
    """Set ``obj["a"]["b"]`` from ``"a.b"``, creating intermediate dicts."""
    parts = dotted.split(".")
    cur = obj
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def tamper(path: str | Path, seq: int, field: str, new_value: Any, *, rehash: bool = False) -> tuple[dict, dict]:
    """DEMO ONLY. Edit one event in place so that ``verify()`` can be seen to fail.

    This is the thing the product exists to make detectable, kept in the codebase
    so an auditor can try it themselves. It rewrites the JSONL line for ``seq``
    with ``field`` (dotted path, e.g. ``payload.value``) set to ``new_value``.

    With ``rehash=False`` the stored ``hash`` is left as it was, so the break is
    reported at ``seq`` itself. With ``rehash=True`` the event's own hash is
    recomputed, as a more careful attacker would, and the break moves to
    ``seq + 1`` whose ``prev_hash`` no longer matches. Recomputing every later
    hash too would hide the edit from ``verify()`` alone, which is why the
    datasheet manifest carries a signed copy of the head hash.

    Returns ``(before, after)``.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        event = json.loads(line)
        if event["seq"] != seq:
            continue
        before = json.loads(line)
        set_path(event, field, normalize(new_value))
        if rehash:
            event["hash"] = event_hash(event)
        lines[i] = json.dumps(event, sort_keys=True, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return before, event
    raise LedgerError(f"no event with seq {seq}")
