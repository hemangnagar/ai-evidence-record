"""``aiev``: run-demo | verify | tamper | ask | exceptions | datasheet | review.

Plain-text tables (rich, no colour that breaks in a PDF). Exit codes mean
something: ``verify`` exits 1 on a broken chain, ``exceptions`` exits 1 when
there are any, so both can sit in a pipeline.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import ask as askmod
from . import datasheet as dsmod
from . import rules as rulesmod
from .gate import CsvStore, Gate, GateError, ReviewerDirectory
from .ledger import Ledger, LedgerError, tamper
from .profile import load_profile
from .scenario import Plants
from .scenario import run as run_scenario
from .signing import HmacSigner, verify_manifest

# Non-TTY output (pipes, CI, the README transcript) gets a sane width instead of rich's 80-column default.
console = Console(highlight=False, soft_wrap=True, width=max(shutil.get_terminal_size((140, 24)).columns, 120))


def _demo_dir(args) -> Path:
    return Path(args.demo_dir)


def _ledger(args) -> Ledger:
    path = _demo_dir(args) / "ledger.jsonl"
    if not path.exists():
        console.print(f"no ledger at {path}; run `aiev run-demo` first")
        sys.exit(2)
    return Ledger(path)


def _reviewers(args) -> ReviewerDirectory | None:
    path = _demo_dir(args) / "reviewers.yaml"
    return ReviewerDirectory.load(path) if path.exists() else None


def _load_plants(demo_dir: Path) -> Plants:
    """``demo/scenario.py`` is the editable source of truth; fall back to defaults when absent."""
    path = demo_dir / "scenario.py"
    if not path.exists():
        return Plants()
    spec = importlib.util.spec_from_file_location("aiev_demo_scenario", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return getattr(module, "PLANTS", Plants())


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


# -- commands ------------------------------------------------------------------


def cmd_run_demo(args) -> int:
    demo_dir = _demo_dir(args)
    coder = None
    if args.coder == "llm":
        from .ai.llm_coder import LLMCoder

        coder = LLMCoder()
    summary = run_scenario(demo_dir, plants=_load_plants(demo_dir), coder=coder, seed=args.seed)
    console.print(f"wrote {summary.ledger_path} ({summary.events} events) and {summary.data_dir}/*.csv")
    console.print(
        f"coder {summary.coder}: {summary.ai_outputs} AI outputs, {summary.reviewed} reviewed, "
        f"{summary.promoted} promoted, {summary.pending} still in quarantine"
    )
    return 0


def cmd_verify(args) -> int:
    ledger = _ledger(args)
    result = ledger.verify()
    console.print(str(result))
    rc = 0 if result.ok else 1
    if args.manifest:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        sig_ok = verify_manifest(manifest, HmacSigner.from_env())
        head_ok = (
            manifest.get("ledger_head_sha256") == result.head_hash and manifest.get("event_count") == result.event_count
        )
        console.print(f"manifest signature: {'OK' if sig_ok else 'INVALID'}")
        console.print(
            f"manifest head {str(manifest.get('ledger_head_sha256'))[:16]}… vs ledger head {result.head_hash[:16]}…: "
            f"{'MATCH' if head_ok else 'MISMATCH'}"
        )
        if not (sig_ok and head_ok):
            rc = 1
    return rc


def cmd_tamper(args) -> int:
    path = _demo_dir(args) / "ledger.jsonl"
    try:
        before, after = tamper(path, args.seq, args.field, _parse_value(args.set), rehash=args.rehash)
    except LedgerError as e:
        console.print(str(e))
        return 2
    console.print(f"DEMO ONLY: edited seq {args.seq} in place ({args.field}).")
    console.print(f"  before: {json.dumps(before, sort_keys=True)[:200]}…")
    console.print(f"  after:  {json.dumps(after, sort_keys=True)[:200]}…")
    console.print("now run `aiev verify`.")
    return 0


def cmd_ask(args) -> int:
    ledger = _ledger(args)
    c = askmod.chain(ledger.events(), args.record, args.field)
    if not c.lines:
        console.print(f"no events for {args.record}")
        return 1
    console.print(askmod.render(c))
    return 0


def _findings(args):
    ledger = _ledger(args)
    profile = load_profile(args.profile)
    events = ledger.events()
    vr = ledger.verify()
    return ledger, profile, events, vr, rulesmod.evaluate(events, profile, _reviewers(args), vr)


def cmd_exceptions(args) -> int:
    _, profile, _, vr, findings = _findings(args)
    if args.json:
        print(json.dumps([f.to_dict() for f in findings], indent=2))
        return 1 if findings else 0
    table = Table(
        title=f"Exceptions · profile {profile['meta']['name']} v{profile['meta']['version']}",
        show_lines=False,
    )
    for col in ("ID", "Severity", "Record", "Seq", "Finding", "Citation"):
        table.add_column(col, overflow="fold")
    for f in findings:
        table.add_row(f.id, f.severity, f.record_ref, str(f.seq), f.explanation, f.citation)
    console.print(table)
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.id] = counts.get(f.id, 0) + 1
    console.print("  ".join(f"{k} ×{v}" for k, v in sorted(counts.items())) or "no exceptions")
    if not vr.ok:
        console.print(f"chain: {vr}")
    return 1 if findings else 0


def cmd_datasheet(args) -> int:
    _, profile, events, vr, findings = _findings(args)
    html_path, manifest_path, manifest = dsmod.write(
        args.out, events, profile, findings, vr, reviewers=_reviewers(args), pdf=args.pdf
    )
    console.print(f"wrote {html_path}")
    console.print(
        f"wrote {manifest_path} (ledger head {manifest['ledger_head_sha256'][:16]}…, {manifest['event_count']} events)"
    )
    if args.pdf:
        console.print(f"wrote {html_path.with_suffix('.pdf')}")
    return 0


def cmd_review(args) -> int:
    ledger = _ledger(args)
    directory = _reviewers(args)
    if directory is None:
        console.print("no demo/reviewers.yaml; cannot identify the reviewer")
        return 2
    reviewer = directory.get(args.reviewer)
    if reviewer is None:
        console.print(f"reviewer {args.reviewer!r} is not in reviewers.yaml")
        return 2
    gate = Gate(ledger, args.study, CsvStore(_demo_dir(args) / "data"))
    output = gate.latest_output(args.record, args.field)
    if output is None:
        console.print(f"no ai_output for {args.record} {args.field}")
        return 2
    p = output["payload"]
    console.print(f"{args.record} {args.field}: status {gate.status(args.record, args.field)}")
    console.print(
        f"  AI ({output['agent']['id']} v{output['agent']['version']}) proposed {p.get('value')!r} "
        f"(confidence {p.get('confidence')})"
    )
    if p.get("rationale"):
        console.print(f"  rationale: {p['rationale']}")

    decision, edited, secs = args.decision, args.edited_value, args.review_seconds
    if decision is None:
        # Interactive: the clock runs from the moment the output is shown to the moment a decision is typed.
        started = time.monotonic()
        decision = input("  decision [approve/edit/reject]: ").strip().lower()
        if decision == "edit":
            edited = input("  edited value: ").strip()
        secs = round(time.monotonic() - started, 1) if secs is None else secs
    elif secs is None:
        # Non-interactive with no timing supplied: the honest number is zero seconds of review.
        secs = 0.0
    try:
        ev = gate.review(
            args.record,
            args.field,
            reviewer,
            decision,
            edited_value=edited,
            review_seconds=secs,
            note=args.note,
        )
        console.print(
            f"  review recorded at seq {ev['seq']}: {ev['payload']['signature']['meaning']} "
            f"by {reviewer.display_name}, {secs}s"
        )
        if decision in ("approve", "edit") and not args.no_promote:
            pe = gate.promote(args.record, args.field)
            console.print(f"  promoted at seq {pe['seq']}: {args.field} = {pe['payload']['value']!r}")
        elif decision == "reject":
            re_ = gate.reject(args.record, args.field)
            console.print(f"  rejected at seq {re_['seq']}")
    except GateError as e:
        console.print(f"gate refused: {e}")
        return 1
    return 0


# -- parser --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aiev", description="AI Evidence Record: what did the AI do to this record?")
    p.add_argument(
        "--demo-dir",
        default="demo",
        help="directory holding ledger.jsonl, data/, reviewers.yaml (default: demo)",
    )
    p.add_argument("--profile", default=None, help="profile YAML (default: bundled clinical_gcp.yaml)")
    s = p.add_subparsers(dest="cmd", required=True)

    r = s.add_parser("run-demo", help="synthesise the study and run the planted scenario")
    r.add_argument("--coder", choices=["stub", "llm"], default="stub")
    r.add_argument("--seed", type=int, default=7)
    r.set_defaults(fn=cmd_run_demo)

    v = s.add_parser("verify", help="walk the hash chain; exit 1 at the first break")
    v.add_argument("--manifest", help="also check a manifest.json signature and head hash")
    v.set_defaults(fn=cmd_verify)

    t = s.add_parser("tamper", help="DEMO ONLY: edit one event in place so verify can be seen to fail")
    t.add_argument("--seq", type=int, required=True)
    t.add_argument("--field", required=True, help="dotted path, e.g. payload.value")
    t.add_argument("--set", required=True, help="new value (JSON if parseable, else string)")
    t.add_argument("--rehash", action="store_true", help="also recompute that event's own hash (break moves to seq+1)")
    t.set_defaults(fn=cmd_tamper)

    a = s.add_parser("ask", help="the full chain for one record, in words")
    a.add_argument("--record", required=True, help="e.g. AE:AIEV-001-1042:3")
    a.add_argument("--field", default=None, help="restrict to one field, e.g. AEDECOD")
    a.set_defaults(fn=cmd_ask)

    e = s.add_parser("exceptions", help="table of EX-xx findings; exit 1 if any")
    e.add_argument("--json", action="store_true")
    e.set_defaults(fn=cmd_exceptions)

    d = s.add_parser("datasheet", help="write the AI Evidence Datasheet HTML and manifest.json")
    d.add_argument("--out", default="demo/datasheet.html")
    d.add_argument("--pdf", action="store_true", help="also write a PDF (needs weasyprint)")
    d.set_defaults(fn=cmd_datasheet)

    rv = s.add_parser("review", help="review a quarantined AI output as a named reviewer")
    rv.add_argument("--record", required=True)
    rv.add_argument("--field", default="AEDECOD")
    rv.add_argument("--reviewer", required=True, help="id from reviewers.yaml")
    rv.add_argument(
        "--decision",
        choices=["approve", "edit", "reject"],
        default=None,
        help="omit for interactive, timed review",
    )
    rv.add_argument("--edited-value", default=None)
    rv.add_argument("--review-seconds", type=float, default=None, help="override the measured review time")
    rv.add_argument("--note", default=None)
    rv.add_argument("--no-promote", action="store_true", help="record the review only; do not promote")
    rv.add_argument("--study", default="AIEV-001")
    rv.set_defaults(fn=cmd_review)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
