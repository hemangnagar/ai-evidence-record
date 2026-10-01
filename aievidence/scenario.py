"""The demo scenario engine. The plants themselves live in ``demo/scenario.py`` so they can be edited live.

Runs the coder and the query generator across the synthetic study with named
reviewers doing legitimate reviews, then inserts exactly the problems the
``Plants`` say to insert. A simulated clock makes the ledger byte-identical
from run to run, which means ``aiev run-demo`` is also the reset button.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import synth
from .ai.stub_coder import StubCoder
from .ai.stub_querygen import StubQueryGen
from .gate import CsvStore, Gate, ReviewerDirectory
from .ledger import Ledger


@dataclass
class Plants:
    """What the scenario deliberately gets wrong. Edit these and re-run."""

    unreviewed_promotion: str = "AE:AIEV-001-1042:3"
    rubber_stamp_record: str = "AE:AIEV-001-1017:1"
    rubber_stamp_seconds: float = 3.0
    version_bump_after: int = 24  # coding events before StubCoder silently becomes...
    version_bump_to: str = "1.1.0"
    leave_pending: list[str] = field(default_factory=lambda: ["AE:AIEV-001-1096:2", "AE:AIEV-001-1128:2"])
    endorse: list[str] = field(default_factory=lambda: ["AE:AIEV-001-1001:1", "AE:AIEV-001-1042:1"])


class Clock:
    def __init__(self, start: str = "2026-09-14T09:00:00Z"):
        self.now = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(UTC)

    def tick(self, seconds: float) -> str:
        self.now += timedelta(seconds=seconds)
        return self.iso()

    def iso(self) -> str:
        return self.now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self.now.microsecond // 1000:03d}Z"


@dataclass
class RunSummary:
    ledger_path: Path
    data_dir: Path
    events: int
    ai_outputs: int
    reviewed: int
    promoted: int
    pending: int
    coder: str


# Reviewer edits for verbatims a coder would argue about: (record_ref) -> (edited value, note).
EDITS = {
    "AE:AIEV-001-1017:1": (
        "Vomiting",
        "Verbatim bundles nausea and vomiting; vomiting is the reportable event.",
    ),
    "AE:AIEV-001-1023:1": (
        "Alanine aminotransferase increased",
        "Lab line shows ALT only; use the specific term.",
    ),
}


def run(
    out_dir: str | Path,
    *,
    plants: Plants | None = None,
    coder=None,
    reviewers_path: str | Path | None = None,
    seed: int = 7,
) -> RunSummary:
    out_dir = Path(out_dir)
    plants = plants or Plants()
    data_dir = out_dir / "data"
    ledger_path = out_dir / "ledger.jsonl"
    reviewers_path = Path(reviewers_path) if reviewers_path else out_dir / "reviewers.yaml"

    study = synth.generate(seed=seed)
    if ledger_path.exists():
        ledger_path.unlink()
    queries = data_dir / "QUERIES.csv"
    if queries.exists():
        queries.unlink()
    synth.write_csvs(study, data_dir)

    ledger = Ledger(ledger_path)
    gate = Gate(ledger, study.study_id, CsvStore(data_dir))
    directory = ReviewerDirectory.load(reviewers_path)
    rmehta, jokafor, pi = directory.get("rmehta"), directory.get("jokafor"), directory.get("pi_site01")
    assert rmehta and jokafor and pi, "demo/reviewers.yaml must define rmehta, jokafor and pi_site01"

    coder = coder or StubCoder("1.0.0")
    querygen = StubQueryGen()
    clock = Clock()
    rng = random.Random(seed)

    ai_outputs = reviewed = promoted = pending = 0

    # -- adverse event coding --------------------------------------------------
    for i, ae in enumerate(study.ae):
        if i == plants.version_bump_after and hasattr(coder, "model_version") and isinstance(coder, StubCoder):
            coder.model_version = plants.version_bump_to  # no model_change event: that is the plant
        ref = f"AE:{ae['USUBJID']}:{ae['AESEQ']}"
        gate.quarantine(coder, ref, "AEDECOD", ae, ts=clock.tick(rng.randint(30, 240)))
        ai_outputs += 1

        if ref == plants.unreviewed_promotion:
            gate.promote(ref, "AEDECOD", force=True, ts=clock.tick(45))
            promoted += 1
            continue
        if ref in plants.leave_pending:
            pending += 1
            continue

        reviewer = rmehta if i % 2 == 0 else jokafor
        if ref == plants.rubber_stamp_record:
            secs = plants.rubber_stamp_seconds
        else:
            secs = rng.randint(40, 300)
        edit = EDITS.get(ref)
        if edit:
            gate.review(
                ref,
                "AEDECOD",
                reviewer,
                "edit",
                edited_value=edit[0],
                note=edit[1],
                review_seconds=secs,
                ts=clock.tick(secs),
            )
        else:
            gate.review(ref, "AEDECOD", reviewer, "approve", review_seconds=secs, ts=clock.tick(secs))
        reviewed += 1
        gate.promote(ref, "AEDECOD", ts=clock.tick(5))
        promoted += 1

    # -- data queries ----------------------------------------------------------
    for ae in study.ae:
        record = {**ae, "RFICDTC": study.subject(ae["USUBJID"])["RFICDTC"]}
        out = querygen.run(record)
        if out.value is None:
            continue
        ref = f"AE:{ae['USUBJID']}:{ae['AESEQ']}"
        gate.quarantine(querygen, ref, "QUERY", record, ts=clock.tick(rng.randint(30, 120)))
        ai_outputs += 1
        secs = rng.randint(60, 180)
        gate.review(ref, "QUERY", rmehta, "approve", review_seconds=secs, ts=clock.tick(secs))
        reviewed += 1
        gate.promote(ref, "QUERY", ts=clock.tick(5))
        promoted += 1

    # -- investigator endorsements (clean: after promotion, nothing changes afterwards) --
    for ref in plants.endorse:
        gate.endorse(ref, pi, ts=clock.tick(3600))

    return RunSummary(
        ledger_path=ledger_path,
        data_dir=data_dir,
        events=len(ledger),
        ai_outputs=ai_outputs,
        reviewed=reviewed,
        promoted=promoted,
        pending=pending,
        coder=f"{coder.model_id} {coder.model_version}",
    )
