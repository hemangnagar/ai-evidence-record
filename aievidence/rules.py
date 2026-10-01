"""Exception rules evaluated over the ledger. Logic here, thresholds and citations in the profile.

Lifted in shape from governed-data-platform's evaluate-rules-over-records loop.
Each rule is a function of the whole event list; it never trusts a payload's
claim about another event (``review_seq`` is recomputed from the ledger, not
read from the promote event) because a payload is exactly what a careless or
dishonest process would get wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

from .gate import ReviewerDirectory
from .ledger import VerifyResult, verify_events

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


@dataclass(frozen=True)
class Finding:
    id: str
    name: str
    record_ref: str
    seq: int
    severity: str
    citation: str
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    events: list[dict]
    profile: dict
    reviewers: ReviewerDirectory | None
    verify_result: VerifyResult

    def spec(self, rule_id: str) -> dict:
        return self.profile["rules"][rule_id]

    def finding(self, rule_id: str, record_ref: str, seq: int, **fmt) -> Finding:
        spec = self.spec(rule_id)
        return Finding(
            id=rule_id,
            name=spec["name"],
            record_ref=record_ref,
            seq=seq,
            severity=spec["severity"],
            citation=spec["citation"],
            explanation=spec["explanation"].format(seq=seq, record_ref=record_ref, **fmt),
        )


def _by_type(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e["event_type"] == kind]


def ex01_unreviewed_promotion(ctx: Context) -> list[Finding]:
    out = []
    for promo in _by_type(ctx.events, "promote"):
        ref, field, seq = promo["record_ref"], promo["field"], promo["seq"]
        outputs = [
            e
            for e in ctx.events
            if e["event_type"] == "ai_output" and e["record_ref"] == ref and e["field"] == field and e["seq"] < seq
        ]
        source_seq = outputs[-1]["seq"] if outputs else 0
        approving = [
            e
            for e in ctx.events
            if e["event_type"] == "review"
            and e["record_ref"] == ref
            and e["field"] == field
            and source_seq < e["seq"] < seq
            and e["payload"].get("decision") in ("approve", "edit")
        ]
        if not approving:
            out.append(ctx.finding("EX-01", ref, seq, field=field))
    return out


def ex02_rubber_stamp(ctx: Context) -> list[Finding]:
    threshold = float(ctx.profile.get("thresholds", {}).get("rubber_stamp_seconds", 5))
    out = []
    for rev in _by_type(ctx.events, "review"):
        secs = rev["payload"].get("review_seconds")
        if secs is None:
            continue
        if float(secs) < threshold:
            out.append(
                ctx.finding(
                    "EX-02",
                    rev["record_ref"],
                    rev["seq"],
                    reviewer=rev["agent"]["id"],
                    review_seconds=secs,
                    threshold=int(threshold) if threshold == int(threshold) else threshold,
                )
            )
    return out


def ex03_model_version_drift(ctx: Context) -> list[Finding]:
    """A model's version may change only after a model_change event declares the new version."""
    declared: dict[str, str] = {}
    out = []
    for e in ctx.events:
        if e["event_type"] == "model_change":
            declared[e["payload"]["model_id"]] = e["payload"]["new_version"]
        elif e["event_type"] == "ai_output":
            model, version = e["agent"]["id"], e["agent"].get("version")
            if model not in declared:
                declared[model] = version  # first sighting establishes the baseline
            elif version != declared[model]:
                out.append(
                    ctx.finding(
                        "EX-03",
                        e["record_ref"],
                        e["seq"],
                        model_id=model,
                        version=version,
                        declared=declared[model],
                    )
                )
    return out


def ex04_post_endorsement_change(ctx: Context) -> list[Finding]:
    endorsements: dict[str, list[int]] = {}
    for e in _by_type(ctx.events, "endorsement"):
        endorsements.setdefault(e["record_ref"], []).append(e["seq"])
    out = []
    for e in ctx.events:
        if e["event_type"] not in ("promote", "correction"):
            continue
        seqs = endorsements.get(e["record_ref"], [])
        before = [s for s in seqs if s < e["seq"]]
        after = [s for s in seqs if s > e["seq"]]
        if before and not after:
            out.append(
                ctx.finding("EX-04", e["record_ref"], e["seq"], event_type=e["event_type"], endorsed_seq=before[-1])
            )
    return out


def ex05_reviewer_without_credential(ctx: Context) -> list[Finding]:
    out = []
    for rev in _by_type(ctx.events, "review"):
        rid = rev["agent"].get("id") or ""
        cred = (rev["agent"].get("credential") or "").strip()
        problem = None
        if ctx.reviewers is not None and rid not in ctx.reviewers:
            problem = "is not in the reviewer directory"
        elif not cred:
            problem = "has no credential recorded"
        elif ctx.reviewers is not None and (ctx.reviewers.get(rid).credential or "").strip() != cred:
            problem = "signed with a credential that does not match the reviewer directory"
        if problem:
            out.append(ctx.finding("EX-05", rev["record_ref"], rev["seq"], reviewer=rid or "(no id)", problem=problem))
    return out


def ex06_missing_provenance(ctx: Context) -> list[Finding]:
    required = list(ctx.profile.get("required_ai_output_fields", []))
    out = []
    for e in _by_type(ctx.events, "ai_output"):
        present = {
            "inputs_hash": e["payload"].get("inputs_hash"),
            "prompt_hash": e["payload"].get("prompt_hash"),
            "model_id": e["agent"].get("id"),
            "model_version": e["agent"].get("version"),
        }
        missing = [f for f in required if not present.get(f)]
        if missing:
            out.append(ctx.finding("EX-06", e["record_ref"], e["seq"], missing=", ".join(missing)))
    return out


def ex07_chain_integrity(ctx: Context) -> list[Finding]:
    vr = ctx.verify_result
    if vr.ok:
        return []
    return [ctx.finding("EX-07", "LEDGER", vr.first_broken_seq or 0, reason=vr.reason)]


RULES: dict[str, Callable[[Context], list[Finding]]] = {
    "EX-01": ex01_unreviewed_promotion,
    "EX-02": ex02_rubber_stamp,
    "EX-03": ex03_model_version_drift,
    "EX-04": ex04_post_endorsement_change,
    "EX-05": ex05_reviewer_without_credential,
    "EX-06": ex06_missing_provenance,
    "EX-07": ex07_chain_integrity,
}


def evaluate(
    events: list[dict],
    profile: dict,
    reviewers: ReviewerDirectory | None = None,
    verify_result: VerifyResult | None = None,
) -> list[Finding]:
    """Run every rule the profile enables. Findings come back ordered by severity, then seq."""
    ctx = Context(events, profile, reviewers, verify_result or verify_events(events))
    findings: list[Finding] = []
    for rule_id in profile["rules"]:
        fn = RULES.get(rule_id)
        if fn is None:
            raise KeyError(f"profile enables {rule_id} but no rule implements it")
        findings.extend(fn(ctx))
    return sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.id, f.seq))
