"""The AI Evidence Datasheet: one HTML file an inspector can read, print, and verify offline.

Section model lifted from governed-data-platform's governance report: "enforce,
then publish what you enforced", pointed at AI events instead of data in motion.
Every scorecard row cites the rule it satisfies, and the manifest beside the
datasheet carries the ledger head hash under a signature.
"""

from __future__ import annotations

import html
import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .gate import ReviewerDirectory
from .ledger import VerifyResult, sha256
from .profile import profile_version
from .rules import Finding
from .signing import HmacSigner, Signer, sign_manifest

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_model(
    events: list[dict],
    profile: dict,
    findings: list[Finding],
    verify_result: VerifyResult,
    reviewers: ReviewerDirectory | None = None,
    study_id: str | None = None,
) -> dict:
    outputs = [e for e in events if e["event_type"] == "ai_output"]
    reviews = [e for e in events if e["event_type"] == "review"]
    promotes = [e for e in events if e["event_type"] == "promote"]
    study_id = study_id or (events[0]["study_id"] if events else "unknown")

    # -- gate summary ----------------------------------------------------------
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in events:
        if e.get("field"):
            by_key[(e["record_ref"], e["field"])].append(e)
    pending = reviewed = rejected = 0
    for evs in by_key.values():
        outs = [e for e in evs if e["event_type"] == "ai_output"]
        if not outs:
            continue
        later = {e["event_type"] for e in evs if e["seq"] > outs[-1]["seq"]}
        if "review" in later:
            reviewed += 1
        if "reject" in later:
            rejected += 1
        if not later:
            pending += 1
    summary = {
        "events": len(events),
        "ai_outputs": len(outputs),
        "reviewed": reviewed,
        "promoted": len(promotes),
        "forced_promotions": sum(1 for p in promotes if p["payload"].get("forced")),
        "pending": pending,
        "rejected": rejected,
        "exceptions": len(findings),
        "first_ts": events[0]["ts"] if events else None,
        "last_ts": events[-1]["ts"] if events else None,
    }

    # -- context of use (profile text + ledger counts) -------------------------
    touchpoints = []
    for field, tp in profile["touchpoints"].items():
        tp_outputs = [o for o in outputs if o["field"] == field]
        models = sorted({f"{o['agent']['id']} v{o['agent'].get('version')}" for o in tp_outputs})
        matrix = profile.get("risk_matrix", {})
        tier = matrix.get(tp.get("influence", "medium"), {}).get(tp.get("consequence", "medium"), "unrated")
        touchpoints.append(
            {
                "field": field,
                "name": tp["name"],
                "question": tp["question"],
                "influences": tp["influences"],
                "decides": tp["decides"],
                "influence": tp.get("influence", "medium"),
                "consequence": tp.get("consequence", "medium"),
                "risk_tier": tier,
                "outputs": len(tp_outputs),
                "models": models,
            }
        )

    # -- model inventory ---------------------------------------------------------
    inv: dict[str, dict] = {}
    for o in outputs:
        m = inv.setdefault(
            o["agent"]["id"],
            {
                "model_id": o["agent"]["id"],
                "versions": [],
                "prompt_hashes": set(),
                "first": o["ts"],
                "last": o["ts"],
                "count": 0,
                "fields": set(),
            },
        )
        v = o["agent"].get("version")
        if v not in m["versions"]:
            m["versions"].append(v)
        if o["payload"].get("prompt_hash"):
            m["prompt_hashes"].add(o["payload"]["prompt_hash"])
        m["first"], m["last"] = min(m["first"], o["ts"]), max(m["last"], o["ts"])
        m["count"] += 1
        m["fields"].add(o["field"])
    declared = {
        e["payload"]["model_id"]: e["payload"]["new_version"] for e in events if e["event_type"] == "model_change"
    }
    inventory = [
        {
            **m,
            "prompt_hashes": sorted(m["prompt_hashes"]),
            "fields": sorted(m["fields"]),
            "declared_change": declared.get(mid),
        }
        for mid, m in inv.items()
    ]

    # -- review log ----------------------------------------------------------------
    rl: dict[str, dict] = {}
    for r in reviews:
        rid = r["agent"]["id"]
        d = rl.setdefault(
            rid,
            {
                "id": rid,
                "name": r["payload"].get("signature", {}).get("printed_name", rid),
                "credential": r["agent"].get("credential") or "",
                "in_directory": (reviewers is not None and rid in reviewers),
                "reviews": 0,
                "approve": 0,
                "edit": 0,
                "reject": 0,
                "seconds": [],
            },
        )
        d["reviews"] += 1
        d[r["payload"]["decision"]] += 1
        if r["payload"].get("review_seconds") is not None:
            d["seconds"].append(float(r["payload"]["review_seconds"]))
    review_log = []
    for d in rl.values():
        secs = d.pop("seconds")
        review_log.append(
            {
                **d,
                "median_seconds": round(statistics.median(secs), 1) if secs else None,
                "min_seconds": min(secs) if secs else None,
            }
        )

    # -- exceptions, scorecard -----------------------------------------------------
    flagged_ids = {f.id for f in findings}
    counts = defaultdict(int)
    for f in findings:
        counts[f.id] += 1
    scorecard = []
    for row in profile["alcoa"]:
        hits = [rid for rid in row.get("flagged_by", []) if rid in flagged_ids]
        scorecard.append(
            {
                "attribute": row["attribute"],
                "status": "FLAG" if hits else "PASS",
                "fields": row["fields"],
                "citation": row["citation"],
                "flagged_by": hits,
            }
        )

    return {
        "study_id": study_id,
        "generated_at": _ts(),
        "tool_version": __version__,
        "profile": {
            "version": profile_version(profile),
            "fingerprint": profile["_fingerprint"],
            "description": profile["meta"].get("description", "").strip(),
            "refs": profile["meta"].get("authority_refs", []),
        },
        "summary": summary,
        "touchpoints": touchpoints,
        "inventory": inventory,
        "review_log": review_log,
        "findings": [f.to_dict() for f in findings],
        "finding_counts": dict(sorted(counts.items())),
        "scorecard": scorecard,
        "crosswalk": profile["crosswalk"],
        "integrity": {
            "ok": verify_result.ok,
            "text": str(verify_result),
            "event_count": verify_result.event_count,
            "head_hash": verify_result.head_hash,
            "first_broken_seq": verify_result.first_broken_seq,
        },
    }


def build_manifest(model: dict, signer: Signer, datasheet_sha256: str | None = None) -> dict:
    manifest = {
        "manifest_version": "0",
        "study_id": model["study_id"],
        "ledger_head_sha256": model["integrity"]["head_hash"],
        "event_count": model["integrity"]["event_count"],
        "chain_ok": model["integrity"]["ok"],
        "profile_version": model["profile"]["version"],
        "profile_fingerprint": model["profile"]["fingerprint"],
        "exception_count": len(model["findings"]),
        "generated_at": model["generated_at"],
        "generator": f"aievidence/{model['tool_version']}",
        "datasheet_sha256": datasheet_sha256,
        "signature_note": (
            "HMAC with a demo key. Production: Ed25519 (aievidence.signing.Ed25519Signer) or an HSM-backed signer."
        ),
    }
    return sign_manifest(manifest, signer)


def render_html(model: dict, manifest: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    env.filters["short"] = lambda s: (s[:16] + "…") if isinstance(s, str) and len(s) > 16 else s
    template = env.get_template("datasheet.html")
    return template.render(m=model, manifest=manifest, esc=html.escape)


def write(
    out_path: str | Path,
    events: list[dict],
    profile: dict,
    findings: list[Finding],
    verify_result: VerifyResult,
    reviewers: ReviewerDirectory | None = None,
    signer: Signer | None = None,
    pdf: bool = False,
) -> tuple[Path, Path, dict]:
    """Write ``datasheet.html`` and ``manifest.json`` next to it. Returns (html_path, manifest_path, manifest)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    signer = signer or HmacSigner.from_env()
    model = build_model(events, profile, findings, verify_result, reviewers)

    # Two-pass so the manifest can carry the datasheet hash and the datasheet can show the signature:
    # the datasheet embeds the manifest *without* datasheet_sha256; the manifest on disk adds it.
    embedded = build_manifest(model, signer)
    html_text = render_html(model, embedded)
    out_path.write_text(html_text, encoding="utf-8")
    manifest = build_manifest(model, signer, datasheet_sha256=sha256(html_text.encode("utf-8")))
    manifest_path = out_path.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if pdf:
        try:
            from weasyprint import HTML  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("PDF output needs `pip install 'aievidence[pdf]'`") from e
        HTML(string=html_text).write_pdf(out_path.with_suffix(".pdf"))
    return out_path, manifest_path, manifest
