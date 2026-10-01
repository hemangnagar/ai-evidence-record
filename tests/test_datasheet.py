from __future__ import annotations

import json

from aievidence import datasheet
from aievidence.gate import ReviewerDirectory
from aievidence.ledger import Ledger, tamper
from aievidence.profile import load_profile
from aievidence.rules import evaluate
from aievidence.signing import HmacSigner, verify_manifest


def _write(demo_dir, out_name="datasheet.html"):
    ledger = Ledger(demo_dir / "ledger.jsonl")
    profile = load_profile()
    reviewers = ReviewerDirectory.load(demo_dir / "reviewers.yaml")
    events, vr = ledger.events(), ledger.verify()
    findings = evaluate(events, profile, reviewers, vr)
    return ledger, datasheet.write(demo_dir / out_name, events, profile, findings, vr, reviewers)


def test_manifest_hash_equals_ledger_head(demo_dir):
    ledger, (html_path, manifest_path, manifest) = _write(demo_dir)
    last = ledger.events()[-1]
    assert manifest["ledger_head_sha256"] == last["hash"] == ledger.head_hash
    assert manifest["event_count"] == len(ledger)
    on_disk = json.loads(manifest_path.read_text())
    assert on_disk == manifest
    assert on_disk["datasheet_sha256"]


def test_manifest_signature_verifies_and_detects_edits(demo_dir):
    _, (_, _, manifest) = _write(demo_dir)
    signer = HmacSigner.from_env()
    assert verify_manifest(manifest, signer)
    forged = {**manifest, "event_count": manifest["event_count"] + 1}
    assert not verify_manifest(forged, signer)
    assert not verify_manifest(manifest, HmacSigner(b"other-key"))


def test_every_scorecard_row_has_a_citation(demo_dir):
    ledger = Ledger(demo_dir / "ledger.jsonl")
    profile = load_profile()
    events, vr = ledger.events(), ledger.verify()
    model = datasheet.build_model(events, profile, evaluate(events, profile, None, vr), vr)
    assert len(model["scorecard"]) == 9
    for row in model["scorecard"]:
        assert row["citation"].strip(), row["attribute"]
        assert row["status"] in ("PASS", "FLAG")
    flagged = {r["attribute"] for r in model["scorecard"] if r["status"] == "FLAG"}
    assert "Attributable" in flagged and "Consistent" in flagged
    assert "Legible" not in flagged
    for f in model["findings"]:
        assert f["citation"]


def test_html_contains_sections_and_plants(demo_dir):
    _, (html_path, _, manifest) = _write(demo_dir)
    html = html_path.read_text()
    for heading in (
        "Context of use",
        "Model inventory",
        "Model risk",
        "Review log",
        "Exceptions",
        "ALCOA+ scorecard",
        "Integrity statement",
    ):
        assert heading in html
    assert "AE:AIEV-001-1042:3" in html
    assert manifest["ledger_head_sha256"] in html
    assert "1.0.0 → 1.1.0" in html


def test_broken_chain_shows_in_datasheet(demo_dir):
    tamper(demo_dir / "ledger.jsonl", 3, "payload.value", "X")
    _, (html_path, _, manifest) = _write(demo_dir)
    assert manifest["chain_ok"] is False
    assert "BROKEN at seq 3" in html_path.read_text()
