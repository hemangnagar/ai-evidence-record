"""The gate: AI output is QUARANTINED until a credentialed human signs it.

Same shape as decision_gate's deterministic gate: inputs in, fixed decision out,
no model anywhere in the path. An ``ai_output`` event parks a value in
quarantine. A ``review`` event, with a signature manifestation that satisfies
21 CFR 11.50 (printed name, date and time, meaning), is the only thing that can
move it. ``promote`` writes the value into the dataset. Promoting without a
review is possible with ``force=True`` so the demo can plant it, and is always
flagged as EX-01 by the rules.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .ai import AIAdapter
from .ledger import Ledger, now_iso

QUARANTINED = "QUARANTINED"
REVIEWED = "REVIEWED"
PROMOTED = "PROMOTED"
REJECTED = "REJECTED"
NONE = "NONE"

DECISIONS = ("approve", "edit", "reject")


class GateError(Exception):
    """A gate rule refused the action. The message says which and why."""


class UnreviewedPromotion(GateError):
    pass


class NoPendingOutput(GateError):
    pass


@dataclass(frozen=True)
class Reviewer:
    id: str
    display_name: str
    credential: str
    role: str = "reviewer"

    def agent(self) -> dict:
        return {"kind": "human", "id": self.id, "version": None, "credential": self.credential or ""}


class ReviewerDirectory:
    """``demo/reviewers.yaml``: who is allowed to sign, and with what credential."""

    def __init__(self, reviewers: list[Reviewer]):
        self._by_id = {r.id: r for r in reviewers}

    @classmethod
    def load(cls, path: str | Path) -> ReviewerDirectory:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(
            [
                Reviewer(
                    id=str(r["id"]),
                    display_name=str(r.get("display_name", r["id"])),
                    credential=str(r.get("credential") or ""),
                    role=str(r.get("role") or "reviewer"),
                )
                for r in data.get("reviewers", [])
            ]
        )

    def get(self, reviewer_id: str) -> Reviewer | None:
        return self._by_id.get(reviewer_id)

    def __contains__(self, reviewer_id: str) -> bool:
        return reviewer_id in self._by_id

    def __iter__(self):
        return iter(self._by_id.values())


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def seconds_between(a: str, b: str) -> float:
    return round((parse_ts(b) - parse_ts(a)).total_seconds(), 3)


def split_ref(record_ref: str) -> tuple[str, str, str | None]:
    """``AE:AIEV-001-1042:3`` -> ``("AE", "AIEV-001-1042", "3")``."""
    parts = record_ref.split(":")
    if len(parts) == 2:
        return parts[0], parts[1], None
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    raise GateError(f"record_ref must look like DOMAIN:USUBJID[:SEQ], got {record_ref!r}")


class CsvStore:
    """Writes promoted values into the SDTM-shaped CSVs. Queries go to QUERIES.csv."""

    SEQ_COLUMN = {"AE": "AESEQ", "CM": "CMSEQ"}

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def read(self, domain: str) -> dict:
        path = self.data_dir / f"{domain}.csv"
        if not path.exists():
            raise GateError(f"dataset {path} does not exist; run `aiev run-demo` first")
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return {"fields": list(reader.fieldnames or []), "rows": list(reader)}

    def write(self, domain: str, fields: list[str], rows: list[dict]) -> None:
        with open(self.data_dir / f"{domain}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    def apply(self, record_ref: str, field: str, value: Any, *, seq: int) -> None:
        domain, usubjid, rseq = split_ref(record_ref)
        if field == "QUERY":
            path = self.data_dir / "QUERIES.csv"
            new = not path.exists()
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["record_ref", "query_text", "ledger_seq"])
                if new:
                    w.writeheader()
                w.writerow({"record_ref": record_ref, "query_text": value, "ledger_seq": seq})
            return
        data = self.read(domain)
        if field not in data["fields"]:
            raise GateError(f"{domain}.csv has no column {field}")
        seq_col = self.SEQ_COLUMN.get(domain)
        for row in data["rows"]:
            if row["USUBJID"] != usubjid:
                continue
            if seq_col and rseq is not None and str(row[seq_col]) != str(rseq):
                continue
            row[field] = "" if value is None else str(value)
            self.write(domain, data["fields"], data["rows"])
            return
        raise GateError(f"no row for {record_ref} in {domain}.csv")


class Gate:
    def __init__(self, ledger: Ledger, study_id: str, store: CsvStore | None = None):
        self.ledger = ledger
        self.study_id = study_id
        self.store = store

    # -- ledger views ----------------------------------------------------------

    def _events_for(self, record_ref: str, field: str | None = None) -> list[dict]:
        return [
            e for e in self.ledger.events() if e["record_ref"] == record_ref and (field is None or e["field"] == field)
        ]

    def latest_output(self, record_ref: str, field: str) -> dict | None:
        outs = [e for e in self._events_for(record_ref, field) if e["event_type"] == "ai_output"]
        return outs[-1] if outs else None

    def review_for(self, output: dict) -> dict | None:
        """The latest review that followed this specific output."""
        reviews = [
            e
            for e in self._events_for(output["record_ref"], output["field"])
            if e["event_type"] == "review" and e["seq"] > output["seq"]
        ]
        return reviews[-1] if reviews else None

    def status(self, record_ref: str, field: str) -> str:
        output = self.latest_output(record_ref, field)
        if output is None:
            return NONE
        later = [e for e in self._events_for(record_ref, field) if e["seq"] > output["seq"]]
        kinds = [e["event_type"] for e in later]
        if "promote" in kinds:
            return PROMOTED
        if "reject" in kinds:
            return REJECTED
        if "review" in kinds:
            return REVIEWED
        return QUARANTINED

    # -- transitions -----------------------------------------------------------

    def quarantine(
        self, adapter: AIAdapter, record_ref: str, field: str, record: dict, *, ts: str | None = None
    ) -> dict:
        out = adapter.run(record)
        agent = {
            "kind": "model",
            "id": adapter.model_id,
            "version": adapter.model_version,
            "credential": None,
        }
        payload = {
            "value": out.value,
            "confidence": out.confidence,
            "rationale": out.rationale,
            "inputs_hash": out.inputs_hash,
            "prompt_hash": adapter.prompt_hash,
            "status": QUARANTINED,
        }
        return self.ledger.append(
            "ai_output",
            study_id=self.study_id,
            record_ref=record_ref,
            field=field,
            agent=agent,
            payload=payload,
            ts=ts,
        )

    def review(
        self,
        record_ref: str,
        field: str,
        reviewer: Reviewer,
        decision: str,
        *,
        edited_value: Any = None,
        review_seconds: float | None = None,
        note: str | None = None,
        ts: str | None = None,
    ) -> dict:
        if decision not in DECISIONS:
            raise GateError(f"decision must be one of {DECISIONS}, got {decision!r}")
        output = self.latest_output(record_ref, field)
        if output is None:
            raise NoPendingOutput(f"nothing to review: no ai_output for {record_ref} {field}")
        if self.status(record_ref, field) in (PROMOTED, REJECTED):
            raise GateError(f"{record_ref} {field} is already {self.status(record_ref, field)}; use a correction")
        if decision == "edit" and edited_value in (None, ""):
            raise GateError("decision 'edit' requires edited_value")
        if not reviewer.display_name:
            raise GateError("signature manifestation requires the reviewer's printed name")
        ts = ts or now_iso()
        if review_seconds is None:
            review_seconds = seconds_between(output["ts"], ts)
        meaning = {
            "approve": f"Approved for promotion to {field}",
            "edit": f"Edited and approved for promotion to {field}",
            "reject": f"Rejected; not to be promoted to {field}",
        }[decision]
        payload = {
            "decision": decision,
            "reviewed_seq": output["seq"],
            "proposed_value": output["payload"].get("value"),
            "edited_value": edited_value if decision == "edit" else None,
            "review_seconds": review_seconds,
            "note": note,
            "signature": {"printed_name": reviewer.display_name, "signed_at": ts, "meaning": meaning},
        }
        return self.ledger.append(
            "review",
            study_id=self.study_id,
            record_ref=record_ref,
            field=field,
            agent=reviewer.agent(),
            payload=payload,
            ts=ts,
        )

    def promote(self, record_ref: str, field: str, *, force: bool = False, ts: str | None = None) -> dict:
        output = self.latest_output(record_ref, field)
        if output is None:
            raise NoPendingOutput(f"nothing to promote: no ai_output for {record_ref} {field}")
        if self.status(record_ref, field) == PROMOTED:
            raise GateError(f"{record_ref} {field} is already promoted")
        review = self.review_for(output)
        approving = review is not None and review["payload"]["decision"] in ("approve", "edit")
        if not approving and not force:
            raise UnreviewedPromotion(
                f"{record_ref} {field} has no approving review "
                f"(seq {output['seq']} is {self.status(record_ref, field)}); "
                "pass force=True to record it anyway, which EX-01 will flag"
            )
        if approving and review["payload"]["decision"] == "edit":
            value = review["payload"]["edited_value"]
        else:
            value = output["payload"].get("value")
        agent = (
            {
                "kind": "human",
                "id": review["agent"]["id"],
                "version": None,
                "credential": review["agent"]["credential"],
            }
            if approving
            else {"kind": "system", "id": "aievidence-gate", "version": None, "credential": None}
        )
        payload = {
            "value": value,
            "source_seq": output["seq"],
            "review_seq": review["seq"] if approving else None,
            "forced": not approving,
        }
        event = self.ledger.append(
            "promote",
            study_id=self.study_id,
            record_ref=record_ref,
            field=field,
            agent=agent,
            payload=payload,
            ts=ts,
        )
        if self.store is not None:
            self.store.apply(record_ref, field, value, seq=event["seq"])
        return event

    def reject(self, record_ref: str, field: str, *, ts: str | None = None) -> dict:
        output = self.latest_output(record_ref, field)
        if output is None:
            raise NoPendingOutput(f"nothing to reject: no ai_output for {record_ref} {field}")
        review = self.review_for(output)
        if review is None or review["payload"]["decision"] != "reject":
            raise GateError("reject requires a review with decision 'reject'")
        payload = {
            "source_seq": output["seq"],
            "review_seq": review["seq"],
            "note": review["payload"].get("note"),
        }
        agent = {
            "kind": "human",
            "id": review["agent"]["id"],
            "version": None,
            "credential": review["agent"]["credential"],
        }
        return self.ledger.append(
            "reject",
            study_id=self.study_id,
            record_ref=record_ref,
            field=field,
            agent=agent,
            payload=payload,
            ts=ts,
        )

    def endorse(self, record_ref: str, investigator: Reviewer, *, ts: str | None = None) -> dict:
        ts = ts or now_iso()
        payload = {
            "scope": "record",
            "signature": {
                "printed_name": investigator.display_name,
                "signed_at": ts,
                "meaning": f"Investigator endorsement of reported data for {record_ref}",
            },
        }
        return self.ledger.append(
            "endorsement",
            study_id=self.study_id,
            record_ref=record_ref,
            field=None,
            agent=investigator.agent(),
            payload=payload,
            ts=ts,
        )

    def correct(
        self, record_ref: str, field: str, new_value: Any, by: Reviewer, reason: str, *, ts: str | None = None
    ) -> dict:
        prior = [e for e in self._events_for(record_ref, field) if e["event_type"] in ("promote", "correction")]
        if not prior:
            raise GateError(f"nothing to correct: {record_ref} {field} was never promoted")
        supersedes = prior[-1]
        payload = {
            "value": new_value,
            "previous_value": supersedes["payload"].get("value"),
            "supersedes_seq": supersedes["seq"],
            "reason": reason,
        }
        event = self.ledger.append(
            "correction",
            study_id=self.study_id,
            record_ref=record_ref,
            field=field,
            agent=by.agent(),
            payload=payload,
            ts=ts,
        )
        if self.store is not None:
            self.store.apply(record_ref, field, new_value, seq=event["seq"])
        return event

    def declare_model_change(
        self,
        model_id: str,
        old_version: str | None,
        new_version: str,
        by: Reviewer,
        reason: str,
        *,
        ts: str | None = None,
    ) -> dict:
        payload = {
            "model_id": model_id,
            "old_version": old_version,
            "new_version": new_version,
            "reason": reason,
        }
        return self.ledger.append(
            "model_change",
            study_id=self.study_id,
            record_ref=f"MODEL:{model_id}",
            field=None,
            agent=by.agent(),
            payload=payload,
            ts=ts,
        )
