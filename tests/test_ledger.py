from __future__ import annotations

import json

import pytest

from aievidence.ledger import GENESIS, Ledger, LedgerError, event_hash, tamper, verify_events

AGENT = {"kind": "model", "id": "stub-coder", "version": "1.0.0", "credential": None}


def _fill(ledger: Ledger, n: int) -> None:
    for i in range(n):
        ledger.append(
            "ai_output",
            study_id="S",
            record_ref=f"AE:S-1:{i}",
            field="AEDECOD",
            agent=AGENT,
            payload={"value": f"v{i}", "inputs_hash": "x", "prompt_hash": "y"},
        )


def test_chain_links_and_verifies(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    _fill(ledger, 5)
    events = ledger.events()
    assert events[0]["prev_hash"] == GENESIS
    for a, b in zip(events, events[1:], strict=False):
        assert b["prev_hash"] == a["hash"]
    assert all(event_hash(e) == e["hash"] for e in events)
    result = ledger.verify()
    assert result.ok and result.event_count == 5 and result.head_hash == events[-1]["hash"]


def test_reopen_continues_chain(tmp_path):
    path = tmp_path / "l.jsonl"
    _fill(Ledger(path), 3)
    again = Ledger(path)
    assert len(again) == 3
    _fill(again, 2)
    assert again.verify().ok and len(again) == 5


def test_single_byte_tamper_breaks_at_that_seq(tmp_path):
    path = tmp_path / "l.jsonl"
    _fill(Ledger(path), 20)
    before, after = tamper(path, 17, "payload.value", "Headache")
    assert before["payload"]["value"] == "v16" and after["payload"]["value"] == "Headache"
    result = Ledger(path).verify()
    assert not result.ok
    assert result.first_broken_seq == 17
    # Events before the edit still verify on their own.
    assert verify_events(Ledger(path).events()[:16]).ok


def test_rehashed_tamper_breaks_at_next_seq(tmp_path):
    path = tmp_path / "l.jsonl"
    _fill(Ledger(path), 20)
    tamper(path, 17, "payload.value", "Headache", rehash=True)
    result = Ledger(path).verify()
    assert not result.ok and result.first_broken_seq == 18


def test_deleting_a_line_breaks_chain(tmp_path):
    path = tmp_path / "l.jsonl"
    _fill(Ledger(path), 6)
    lines = path.read_text().splitlines()
    del lines[2]
    path.write_text("\n".join(lines) + "\n")
    result = Ledger(path).verify()
    assert not result.ok and result.first_broken_seq == 3


def test_reordering_breaks_chain(tmp_path):
    path = tmp_path / "l.jsonl"
    _fill(Ledger(path), 4)
    lines = path.read_text().splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    path.write_text("\n".join(lines) + "\n")
    assert Ledger(path).verify().first_broken_seq == 2


def test_rejects_unknown_event_type_and_agent(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    with pytest.raises(LedgerError):
        ledger.append("delete", study_id="S", record_ref="r", field=None, agent=AGENT, payload={})
    with pytest.raises(LedgerError):
        ledger.append(
            "review", study_id="S", record_ref="r", field=None, agent={"kind": "robot", "id": "x"}, payload={}
        )


def test_lines_are_canonical_json(tmp_path):
    path = tmp_path / "l.jsonl"
    _fill(Ledger(path), 1)
    line = path.read_text().splitlines()[0]
    assert json.dumps(json.loads(line), sort_keys=True, ensure_ascii=False) == line
