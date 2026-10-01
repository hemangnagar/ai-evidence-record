"""The browser engine and the Python engine must agree on the chain, byte for byte."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from aievidence import workbench
from aievidence.gate import ReviewerDirectory
from aievidence.ledger import Ledger
from aievidence.profile import load_profile
from aievidence.rules import evaluate

NODE = shutil.which("node")

NODE_SCRIPT = r"""
const A = require(process.argv[2]);
const data = JSON.parse(require("fs").readFileSync(process.argv[3], "utf8"));
const out = process.argv[4];
// 1. The Python ledger verifies under the JS engine, hash for hash.
const vr = A.verifyEvents(data.events);
if (!vr.ok) { console.error("python ledger failed JS verify: " + vr.text); process.exit(1); }
// 2. A ledger extended in the browser (a 2-second review by an uncredentialed reviewer) still chains.
const L = new A.Ledger(data.events);
const R = Object.fromEntries(data.reviewers.map((r) => [r.id, r]));
const g = new A.Gate(L, data.study_id, null);
g.review("AE:AIEV-001-1096:2", "AEDECOD", R.tlindqvist, "approve", { review_seconds: 2 });
g.promote("AE:AIEV-001-1096:2", "AEDECOD");
require("fs").writeFileSync(out + "/extended.jsonl", L.toJSONL());
// 3. A ledger generated entirely in the browser.
const r = A.runScenario(data, data.plants);
require("fs").writeFileSync(out + "/generated.jsonl", r.ledger.toJSONL());
const findings = A.evaluate(L.events, data.profile, R).map((f) => f.id);
console.log(JSON.stringify({ extended: L.length, generated: r.ledger.length, findings }));
"""


def test_page_builds_and_embeds_everything(demo_dir):
    out = workbench.write(demo_dir, demo_dir / "workbench.html")
    html = out.read_text(encoding="utf-8")
    assert "AIEV" in html and "runScenario" in html
    assert "AE:AIEV-001-1042:3" in html and "HEADACHE WORSE SINCE DOSE 2" in html
    data = workbench.build_data(demo_dir)
    assert data["plants"]["unreviewed_promotion"] == "AE:AIEV-001-1042:3"
    assert data["adapters"]["stub_coder"]["dictionary"]["headache"] == "Headache"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_and_python_engines_agree(demo_dir, tmp_path):
    data = workbench.build_data(demo_dir)
    data_path = tmp_path / "data.json"
    data_path.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "check.js"
    script.write_text(NODE_SCRIPT, encoding="utf-8")
    engine = Path(workbench.TEMPLATE_DIR) / "workbench_engine.js"
    res = subprocess.run(
        [NODE, str(script), str(engine), str(data_path), str(tmp_path)], capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout.strip().splitlines()[-1])

    profile = load_profile()
    reviewers = ReviewerDirectory.load(demo_dir / "reviewers.yaml")

    extended = Ledger(tmp_path / "extended.jsonl")
    assert extended.verify().ok and len(extended) == report["extended"] == len(Ledger(demo_dir / "ledger.jsonl")) + 2
    py_ids = sorted(f.id for f in evaluate(extended.events(), profile, reviewers))
    assert py_ids == sorted(report["findings"])
    assert Counter(py_ids)["EX-05"] == 1 and Counter(py_ids)["EX-02"] == 2

    generated = Ledger(tmp_path / "generated.jsonl")
    assert generated.verify().ok and len(generated) == report["generated"]
    counts = Counter(f.id for f in evaluate(generated.events(), profile, reviewers))
    bumped = sum(1 for e in generated.events() if e["event_type"] == "ai_output" and e["agent"]["version"] == "1.1.0")
    assert counts == {"EX-01": 1, "EX-02": 1, "EX-03": bumped} and bumped == 6
