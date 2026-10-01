"""``aiev workbench``: one self-contained HTML page where an auditor can run every scenario.

The page embeds the ledger, the datasets, the reviewer directory, the profile
and the planted scenario, plus a JavaScript port of the engine
(``templates/workbench_engine.js``). The hash chain in the browser is the same
SHA-256 over the same canonical JSON as Python's, so a ledger produced or
extended in the page downloads as ``ledger.jsonl`` and passes ``aiev verify``.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .ai import stub_coder, stub_querygen
from .gate import ReviewerDirectory
from .ledger import Ledger
from .profile import load_profile, profile_version
from .scenario import load_plants

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_data(demo_dir: str | Path, profile: dict | None = None) -> dict:
    """Everything the page needs, as one JSON-serialisable dict."""
    demo_dir = Path(demo_dir)
    profile = profile or load_profile()
    ledger = Ledger(demo_dir / "ledger.jsonl")
    events = ledger.events()
    data_dir = demo_dir / "data"
    reviewers_path = demo_dir / "reviewers.yaml"
    reviewers = [asdict(r) for r in ReviewerDirectory.load(reviewers_path)] if reviewers_path.exists() else []
    return {
        "study_id": events[0]["study_id"] if events else "AIEV-001",
        "tool_version": __version__,
        "events": events,
        "ae": _csv(data_dir / "AE.csv"),
        "dm": _csv(data_dir / "DM.csv"),
        "cm": _csv(data_dir / "CM.csv"),
        "queries": _csv(data_dir / "QUERIES.csv"),
        "reviewers": reviewers,
        "plants": asdict(load_plants(demo_dir)),
        "profile": {k: v for k, v in profile.items() if not k.startswith("_")},
        "profile_version": profile_version(profile),
        "profile_fingerprint": profile["_fingerprint"],
        "adapters": {
            "stub_coder": {
                "prompt_template": stub_coder.PROMPT_TEMPLATE,
                "dictionary": stub_coder.DICTIONARY,
                "input_fields": stub_coder.INPUT_FIELDS,
            },
            "stub_querygen": {
                "prompt_template": stub_querygen.PROMPT_TEMPLATE,
                "input_fields": stub_querygen.INPUT_FIELDS,
            },
        },
    }


def engine_source() -> str:
    return (TEMPLATE_DIR / "workbench_engine.js").read_text(encoding="utf-8")


def render(data: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    template = env.get_template("workbench.html")
    # "</" inside a <script> block would end the element; JSON never needs it unescaped.
    data_json = json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return template.render(
        study_id=data["study_id"],
        profile_version=data["profile_version"],
        profile_fingerprint=data["profile_fingerprint"],
        data_json=data_json,
        engine_js=engine_source().replace("</script", "<\\/script"),
    )


def write(demo_dir: str | Path, out_path: str | Path, profile: dict | None = None) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(build_data(demo_dir, profile)), encoding="utf-8")
    return out_path
