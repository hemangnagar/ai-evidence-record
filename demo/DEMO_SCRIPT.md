# The hour with Bhavesh

One laptop, one terminal, one browser tab. No slides. Run `aiev run-demo` before he sits down and again whenever you want a clean state; it is deterministic, so the ledger comes back byte-identical.

Record the session if he agrees. His phrases are the copy.

## 0–10 min — his terms, not yours

Open `demo/data/AE.csv`. Let him read the verbatims (`HEADACHE WORSE SINCE DOSE 2`, `nausea/vomitting x2 days`, `Elevated LFTs`). Ask: **"Is this what site data looks like?"**

Then open `demo/ledger.jsonl` raw. Let him scroll. Say nothing about hashes until he asks.

## 10–20 min — the question

```
aiev ask --record AE:AIEV-001-1042:3
```

Say only: **"An inspector asks what the AI did to this subject's third adverse event."** Let him read the chain. The last line says `PROMOTED WITHOUT REVIEW`.

If he wants a clean one for contrast: `aiev ask --record AE:AIEV-001-1001:1` (reviewed, promoted, investigator-endorsed).

## 20–40 min — hand him the keyboard

Each time, ask: **"Would that finding hold up?"**

1. **Break the chain.**
   ```
   aiev tamper --seq 16 --field payload.value --set "Migraine"
   aiev verify
   ```
   If he asks "what if I fix the hash too?": `aiev tamper --seq 16 --field payload.value --set "Migraine" --rehash` and `aiev verify` breaks at seq 17 instead. If he asks "what if I recompute every hash after it?": the signed `manifest.json` carries the head hash; `aiev verify --manifest demo/manifest.json` reports the mismatch. (Reset with `aiev run-demo`.)

2. **Rubber-stamp a review.** Two outputs are still in quarantine. Let him review one interactively; the clock runs from the moment the proposal is shown until he types a decision:
   ```
   aiev review --record AE:AIEV-001-1096:2 --reviewer rmehta
   aiev exceptions
   ```
   Under five seconds lands EX-02. Signing as `tlindqvist` (no credential on file) adds EX-05.

3. **Drift the model.** Open `demo/scenario.py`, change `version_bump_after` or `version_bump_to`, then:
   ```
   aiev run-demo && aiev exceptions
   ```
   The EX-03 count follows the number of coding events after the bump. Set `version_bump_after=99` and it disappears.

## 40–55 min — the datasheet as an auditor

```
aiev datasheet --out demo/datasheet.html
```

Open it. Ask him to read it **as if preparing to defend it**, and to write down every field he would ask for that is not there. **That list is the week-two backlog. Capture it verbatim.**

Things he may test and what happens:
- Section 1 shows the ledger head hash; `demo/manifest.json` carries the same hash under a signature.
- Section 3 shows `stub-coder` as `1.0.0 → 1.1.0` with "declared change: none".
- Section 7 (ALCOA+) flags Attributable, Accurate, Consistent; every row cites a clause.
- Clause numbers live in `aievidence/profiles/clinical_gcp.yaml`. If he disputes one, change it there and regenerate; the profile fingerprint in the header changes with it.

## 55–60 min — the two questions

**"Who at a sponsor would own this?"**

**"Would you put your name on it?"**

## Before the session

- Verify clause numbers in `clinical_gcp.yaml` against the primary texts (the file header lists them).
- Have the KYM agreement answer ready in case he asks about IP.
- `pip install -e .` on the demo laptop, `aiev run-demo && aiev verify && aiev exceptions && aiev datasheet` once, open the HTML in the browser so the tab is warm.
