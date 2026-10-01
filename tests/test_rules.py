from __future__ import annotations

from collections import Counter

from aievidence.ai.stub_coder import StubCoder
from aievidence.gate import Gate, Reviewer, ReviewerDirectory
from aievidence.ledger import Ledger, tamper
from aievidence.profile import load_profile
from aievidence.rules import evaluate

RMEHTA = Reviewer("rmehta", "Rina Mehta", "PharmD, Clinical Data Manager")
PI = Reviewer("pi", "Anand Raghavan", "MD, Principal Investigator")
DIRECTORY = ReviewerDirectory([RMEHTA, PI])
RECORD = {"USUBJID": "S-1", "AESEQ": 1, "AETERM": "headache"}


def _findings(ledger: Ledger, reviewers=DIRECTORY):
    return evaluate(ledger.events(), load_profile(), reviewers, ledger.verify())


def _clean_gate(tmp_path) -> Gate:
    gate = Gate(Ledger(tmp_path / "l.jsonl"), "S")
    gate.quarantine(StubCoder(), "AE:S-1:1", "AEDECOD", RECORD)
    gate.review("AE:S-1:1", "AEDECOD", RMEHTA, "approve", review_seconds=60)
    gate.promote("AE:S-1:1", "AEDECOD")
    return gate


def test_clean_ledger_has_zero_exceptions(tmp_path):
    gate = _clean_gate(tmp_path)
    assert _findings(gate.ledger) == []


def test_planted_scenario_finds_exactly_the_plants(demo_dir):
    ledger = Ledger(demo_dir / "ledger.jsonl")
    findings = _findings(ledger, ReviewerDirectory.load(demo_dir / "reviewers.yaml"))
    counts = Counter(f.id for f in findings)
    events = ledger.events()
    bumped = [
        e
        for e in events
        if e["event_type"] == "ai_output" and e["agent"]["id"] == "stub-coder" and e["agent"]["version"] == "1.1.0"
    ]
    assert counts == {"EX-01": 1, "EX-02": 1, "EX-03": len(bumped)}
    assert len(bumped) > 0
    ex01 = next(f for f in findings if f.id == "EX-01")
    assert ex01.record_ref == "AE:AIEV-001-1042:3"
    ex02 = next(f for f in findings if f.id == "EX-02")
    assert ex02.record_ref == "AE:AIEV-001-1017:1" and "took 3s" in ex02.explanation
    assert all(f.citation for f in findings)


def test_ex01_unreviewed_promotion(tmp_path):
    gate = Gate(Ledger(tmp_path / "l.jsonl"), "S")
    gate.quarantine(StubCoder(), "AE:S-1:1", "AEDECOD", RECORD)
    gate.promote("AE:S-1:1", "AEDECOD", force=True)
    ids = [f.id for f in _findings(gate.ledger)]
    assert ids == ["EX-01"]


def test_ex01_does_not_trust_payload_review_seq(tmp_path):
    """A promote that *claims* a review_seq but has no review event is still EX-01."""
    gate = Gate(Ledger(tmp_path / "l.jsonl"), "S")
    gate.quarantine(StubCoder(), "AE:S-1:1", "AEDECOD", RECORD)
    gate.promote("AE:S-1:1", "AEDECOD", force=True)
    tamper(gate.ledger.path, 2, "payload.review_seq", 1, rehash=True)
    tamper(gate.ledger.path, 2, "payload.forced", False, rehash=True)
    ids = {f.id for f in _findings(Ledger(gate.ledger.path))}
    assert "EX-01" in ids


def test_ex02_rubber_stamp_threshold_from_profile(tmp_path):
    gate = Gate(Ledger(tmp_path / "l.jsonl"), "S")
    gate.quarantine(StubCoder(), "AE:S-1:1", "AEDECOD", RECORD)
    gate.review("AE:S-1:1", "AEDECOD", RMEHTA, "approve", review_seconds=4.9)
    assert [f.id for f in _findings(gate.ledger)] == ["EX-02"]
    profile = load_profile()
    profile["thresholds"]["rubber_stamp_seconds"] = 2
    assert evaluate(gate.ledger.events(), profile, DIRECTORY) == []


def test_ex03_version_drift_and_declared_change(tmp_path):
    gate = Gate(Ledger(tmp_path / "l.jsonl"), "S")
    coder = StubCoder("1.0.0")
    gate.quarantine(coder, "AE:S-1:1", "AEDECOD", RECORD)
    coder.model_version = "1.1.0"
    gate.quarantine(coder, "AE:S-1:2", "AEDECOD", RECORD)
    gate.quarantine(coder, "AE:S-1:3", "AEDECOD", RECORD)
    assert [f.id for f in _findings(gate.ledger)] == ["EX-03", "EX-03"]
    # Declaring the change makes subsequent outputs clean; the earlier ones stay flagged.
    gate.declare_model_change("stub-coder", "1.1.0", "1.2.0", RMEHTA, "revalidated dictionary")
    coder.model_version = "1.2.0"
    gate.quarantine(coder, "AE:S-1:4", "AEDECOD", RECORD)
    assert [f.id for f in _findings(gate.ledger)] == ["EX-03", "EX-03"]


def test_ex04_post_endorsement_change(tmp_path):
    gate = _clean_gate(tmp_path)
    gate.endorse("AE:S-1:1", PI)
    assert _findings(gate.ledger) == []
    gate.correct("AE:S-1:1", "AEDECOD", "Migraine", RMEHTA, "site clarified")
    assert [f.id for f in _findings(gate.ledger)] == ["EX-04"]
    gate.endorse("AE:S-1:1", PI)  # re-endorsement clears it
    assert _findings(gate.ledger) == []


def test_ex05_reviewer_without_credential_or_not_in_directory(tmp_path):
    gate = Gate(Ledger(tmp_path / "l.jsonl"), "S")
    gate.quarantine(StubCoder(), "AE:S-1:1", "AEDECOD", RECORD)
    gate.review("AE:S-1:1", "AEDECOD", Reviewer("tlindqvist", "Tove Lindqvist", ""), "approve", review_seconds=60)
    findings = _findings(gate.ledger, ReviewerDirectory([RMEHTA, Reviewer("tlindqvist", "Tove Lindqvist", "")]))
    assert [f.id for f in findings] == ["EX-05"] and "no credential" in findings[0].explanation
    findings = _findings(gate.ledger, DIRECTORY)
    assert "not in the reviewer directory" in findings[0].explanation


def test_ex06_missing_provenance_fields(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(
        "ai_output",
        study_id="S",
        record_ref="AE:S-1:1",
        field="AEDECOD",
        agent={"kind": "model", "id": "mystery-model", "version": None, "credential": None},
        payload={"value": "Headache", "confidence": 0.5},
    )
    findings = _findings(ledger)
    assert [f.id for f in findings] == ["EX-06"]
    for missing in ("inputs_hash", "prompt_hash", "model_version"):
        assert missing in findings[0].explanation


def test_ex07_chain_integrity(tmp_path):
    gate = _clean_gate(tmp_path)
    tamper(gate.ledger.path, 2, "payload.decision", "reject")
    findings = _findings(Ledger(gate.ledger.path))
    ex07 = [f for f in findings if f.id == "EX-07"]
    assert len(ex07) == 1 and ex07[0].seq == 2 and ex07[0].record_ref == "LEDGER"


def test_every_profile_rule_has_an_implementation_and_citation():
    profile = load_profile()
    from aievidence.rules import RULES

    for rule_id, spec in profile["rules"].items():
        assert rule_id in RULES
        assert spec["citation"] and spec["severity"] in ("critical", "major", "minor")
