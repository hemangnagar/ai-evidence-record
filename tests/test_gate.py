from __future__ import annotations

import pytest

from aievidence.ai.stub_coder import StubCoder
from aievidence.gate import (
    PROMOTED,
    QUARANTINED,
    REVIEWED,
    Gate,
    GateError,
    NoPendingOutput,
    Reviewer,
    UnreviewedPromotion,
)
from aievidence.ledger import Ledger

RMEHTA = Reviewer("rmehta", "Rina Mehta", "PharmD, Clinical Data Manager")
RECORD = {"USUBJID": "S-1", "AESEQ": 1, "AETERM": "headache"}
REF = "AE:S-1:1"


@pytest.fixture
def gate(tmp_path) -> Gate:
    return Gate(Ledger(tmp_path / "l.jsonl"), "S")


def test_ai_output_is_quarantined(gate):
    ev = gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    assert ev["payload"]["status"] == QUARANTINED
    assert gate.status(REF, "AEDECOD") == QUARANTINED
    for key in ("inputs_hash", "prompt_hash"):
        assert ev["payload"][key]
    assert ev["agent"] == {"kind": "model", "id": "stub-coder", "version": "1.0.0", "credential": None}


def test_cannot_promote_without_review(gate):
    gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    with pytest.raises(UnreviewedPromotion):
        gate.promote(REF, "AEDECOD")
    assert gate.status(REF, "AEDECOD") == QUARANTINED


def test_force_promote_is_recorded_as_forced(gate):
    gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    ev = gate.promote(REF, "AEDECOD", force=True)
    assert ev["payload"]["forced"] is True and ev["payload"]["review_seq"] is None
    assert ev["agent"]["kind"] == "system"
    assert gate.status(REF, "AEDECOD") == PROMOTED


def test_review_carries_signature_manifestation(gate):
    out = gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD, ts="2026-09-14T09:00:00.000Z")
    rev = gate.review(REF, "AEDECOD", RMEHTA, "approve", ts="2026-09-14T09:01:30.000Z")
    sig = rev["payload"]["signature"]
    assert sig == {
        "printed_name": "Rina Mehta",
        "signed_at": "2026-09-14T09:01:30.000Z",
        "meaning": "Approved for promotion to AEDECOD",
    }
    assert rev["agent"]["credential"] == "PharmD, Clinical Data Manager"
    assert rev["payload"]["reviewed_seq"] == out["seq"]
    assert rev["payload"]["review_seconds"] == 90.0
    assert gate.status(REF, "AEDECOD") == REVIEWED


def test_approve_then_promote_writes_proposed_value(gate):
    gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    gate.review(REF, "AEDECOD", RMEHTA, "approve", review_seconds=60)
    ev = gate.promote(REF, "AEDECOD")
    assert ev["payload"]["value"] == "Headache" and ev["payload"]["forced"] is False
    assert ev["agent"]["id"] == "rmehta"


def test_edit_then_promote_writes_edited_value(gate):
    gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    with pytest.raises(GateError):
        gate.review(REF, "AEDECOD", RMEHTA, "edit", review_seconds=60)  # no edited value
    gate.review(REF, "AEDECOD", RMEHTA, "edit", edited_value="Migraine", review_seconds=60)
    assert gate.promote(REF, "AEDECOD")["payload"]["value"] == "Migraine"


def test_reject_review_blocks_promotion(gate):
    gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    gate.review(REF, "AEDECOD", RMEHTA, "reject", review_seconds=60, note="not an AE")
    with pytest.raises(UnreviewedPromotion):
        gate.promote(REF, "AEDECOD")
    assert gate.reject(REF, "AEDECOD")["event_type"] == "reject"


def test_review_requires_pending_output(gate):
    with pytest.raises(NoPendingOutput):
        gate.review(REF, "AEDECOD", RMEHTA, "approve")


def test_cannot_review_after_promotion(gate):
    gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    gate.promote(REF, "AEDECOD", force=True)
    with pytest.raises(GateError):
        gate.review(REF, "AEDECOD", RMEHTA, "approve")


def test_correction_points_at_superseded_seq(gate):
    gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    gate.review(REF, "AEDECOD", RMEHTA, "approve", review_seconds=60)
    promo = gate.promote(REF, "AEDECOD")
    corr = gate.correct(REF, "AEDECOD", "Migraine", RMEHTA, "site clarified")
    assert corr["payload"]["supersedes_seq"] == promo["seq"]
    assert corr["payload"]["previous_value"] == "Headache"


def test_reviewer_without_printed_name_cannot_sign(gate):
    gate.quarantine(StubCoder(), REF, "AEDECOD", RECORD)
    with pytest.raises(GateError):
        gate.review(REF, "AEDECOD", Reviewer("ghost", "", ""), "approve")
