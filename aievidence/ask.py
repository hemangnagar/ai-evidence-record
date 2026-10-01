"""``aiev ask``: what did the AI do to this record? The chain, in order, in words."""

from __future__ import annotations

from dataclasses import dataclass

from .gate import NONE, PROMOTED, QUARANTINED, REJECTED, REVIEWED


@dataclass
class ChainLine:
    seq: int
    ts: str
    kind: str
    who: str
    what: str


@dataclass
class Chain:
    record_ref: str
    lines: list[ChainLine]
    status_by_field: dict[str, str]
    verdicts: list[str]


def _who(e: dict) -> str:
    a = e["agent"]
    if a["kind"] == "model":
        return f"model {a['id']} v{a.get('version')}"
    if a["kind"] == "human":
        cred = a.get("credential") or "NO CREDENTIAL"
        return f"{a['id']} ({cred})"
    return f"system {a['id']}"


def _what(e: dict) -> str:
    p = e["payload"]
    t = e["event_type"]
    f = e.get("field")
    if t == "ai_output":
        conf = p.get("confidence")
        val = p.get("value")
        s = f"proposed {f} = {val!r}" + (f" (confidence {conf:.2f})" if isinstance(conf, int | float) else "")
        if p.get("rationale"):
            s += f"; rationale: {p['rationale']}"
        ih, ph = str(p.get("inputs_hash") or "?")[:12], str(p.get("prompt_hash") or "?")[:12]
        s += f"; inputs_hash {ih}…, prompt_hash {ph}…"
        return s + " -> QUARANTINED"
    if t == "review":
        sig = p.get("signature", {})
        s = f"{p['decision'].upper()} after {p.get('review_seconds')}s"
        s += f"; signed '{sig.get('meaning')}' by {sig.get('printed_name')}"
        if p.get("edited_value") is not None:
            s += f"; edited to {p['edited_value']!r}"
        if p.get("note"):
            s += f"; note: {p['note']}"
        return s
    if t == "promote":
        s = f"wrote {f} = {p.get('value')!r} to the dataset"
        s += " WITHOUT A REVIEW (forced)" if p.get("forced") else f" (review seq {p.get('review_seq')})"
        return s
    if t == "reject":
        return f"rejected {f}; value not written (review seq {p.get('review_seq')})"
    if t == "correction":
        return (
            f"corrected {f} from {p.get('previous_value')!r} to {p.get('value')!r}, "
            f"supersedes seq {p.get('supersedes_seq')}: {p.get('reason')}"
        )
    if t == "endorsement":
        return f"investigator endorsement: '{p.get('signature', {}).get('meaning')}'"
    if t == "model_change":
        return f"declared {p.get('model_id')} {p.get('old_version')} -> {p.get('new_version')}: {p.get('reason')}"
    return str(p)


def chain(events: list[dict], record_ref: str, field: str | None = None) -> Chain:
    sel = [e for e in events if e["record_ref"] == record_ref and (field is None or e["field"] == field)]
    lines = [ChainLine(e["seq"], e["ts"], e["event_type"], _who(e), _what(e)) for e in sel]

    status: dict[str, str] = {}
    verdicts: list[str] = []
    fields = sorted({e["field"] for e in sel if e.get("field")})
    for f in fields:
        fe = [e for e in sel if e["field"] == f]
        outs = [e for e in fe if e["event_type"] == "ai_output"]
        if not outs:
            status[f] = NONE
            continue
        last = outs[-1]
        later = [e["event_type"] for e in fe if e["seq"] > last["seq"]]
        if "promote" in later:
            status[f] = PROMOTED
            promo = next(e for e in fe if e["event_type"] == "promote" and e["seq"] > last["seq"])
            reviews = [e for e in fe if e["event_type"] == "review" and last["seq"] < e["seq"] < promo["seq"]]
            if not any(r["payload"]["decision"] in ("approve", "edit") for r in reviews):
                verdicts.append(f"{f}: PROMOTED WITHOUT REVIEW at seq {promo['seq']}. No human signed this value.")
            else:
                r = reviews[-1]
                verdicts.append(
                    f"{f}: promoted at seq {promo['seq']} after {r['agent']['id']} signed at seq {r['seq']} "
                    f"({r['payload']['decision']}, {r['payload'].get('review_seconds')}s)."
                )
        elif "reject" in later:
            status[f] = REJECTED
            verdicts.append(f"{f}: rejected; the AI value was never written.")
        elif "review" in later:
            status[f] = REVIEWED
            verdicts.append(f"{f}: reviewed, not yet promoted.")
        else:
            status[f] = QUARANTINED
            verdicts.append(f"{f}: AI output at seq {last['seq']} is still in quarantine; no human has looked at it.")
    endorsed = [e for e in sel if e["event_type"] == "endorsement"]
    if endorsed:
        verdicts.append(f"Investigator endorsed this record at seq {endorsed[-1]['seq']}.")
    return Chain(record_ref, lines, status, verdicts)


def render(c: Chain) -> str:
    out = [f"Record {c.record_ref}: {len(c.lines)} events"]
    for ln in c.lines:
        out.append(f"  seq {ln.seq:>4}  {ln.ts}  {ln.kind:<12} {ln.who}")
        out.append(f"            {ln.what}")
    out.append("")
    for f, s in c.status_by_field.items():
        out.append(f"  {f}: {s}")
    for v in c.verdicts:
        out.append(f"  * {v}")
    return "\n".join(out)
