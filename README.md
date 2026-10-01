# AI Evidence Record

*When the inspector asks what the AI did to this record, this is the answer.*

A tamper-evident ledger that sits beside a clinical trial's data systems, quarantines every AI-generated output until a credentialed human signs it, scans the ledger for the things an inspector would find, and generates a per-study **AI Evidence Datasheet**: context of use, model inventory, reviewer log, exceptions, and an ALCOA+ scorecard where every row cites the rule it satisfies (21 CFR Part 11, ICH E6(R3) Annex 1 data governance, FDA's 7-step AI credibility framework).

The AI is pluggable and, for the record, irrelevant. The evidence record is the product.

**Design principle:** the deterministic engine (ledger, gate, rules, scorecard) is the sole source of truth. An LLM may be the *subject* of an event; it is never the author of the record.

All data in this repository is synthetic. There are no real subjects, sites, investigators or identifiers anywhere.

## 90-second demo

```
$ pip install -e .
$ aiev run-demo
wrote demo/ledger.jsonl (96 events) and demo/data/*.csv
coder stub-coder 1.1.0: 33 AI outputs, 30 reviewed, 31 promoted, 2 still in quarantine

$ aiev verify
OK: 96 events, head a9babf7075a42f41…

$ aiev exceptions
┏━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ID    ┃ Severity ┃ Record            ┃ Seq ┃ Finding                                            ┃ Citation                       ┃
┡━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ EX-01 │ critical │ AE:AIEV-001-1042:3│ 79  │ promote at seq 79 wrote AEDECOD for               │ 21 CFR 211.22(c) by analogy;   │
│       │          │                   │     │ AE:AIEV-001-1042:3 with no approving review …      │ ICH E6(R3) Annex 1 §4 …        │
│ EX-02 │ major    │ AE:AIEV-001-1017:1│ 5   │ review at seq 5 by jokafor took 3.0s, below the 5s │ ICH E6(R3) Annex 1 §4.2 …      │
│ EX-03 │ major    │ AE:AIEV-001-1001:3│ 69  │ stub-coder ran as version 1.1.0 at seq 69; the     │ FDA AI credibility framework   │
│       │          │                   │     │ last declared version was 1.0.0 and no             │ step 7 …; 21 CFR 11.10(k)      │
│       │          │                   │     │ model_change event precedes it                     │                                │
│ …     │          │                   │     │ (five more EX-03, one per coding event after the bump)                              │
└───────┴──────────┴───────────────────┴─────┴────────────────────────────────────────────────────┴────────────────────────────────┘
EX-01 ×1  EX-02 ×1  EX-03 ×6

$ aiev ask --record AE:AIEV-001-1042:3
Record AE:AIEV-001-1042:3: 2 events
  seq   78  2026-09-14T10:56:24.000Z  ai_output    model stub-coder v1.1.0
            proposed AEDECOD = 'Hypoaesthesia' (confidence 0.88); rationale: dictionary match on 'numbness'; inputs_hash 75143db99598…, prompt_hash e6f4591dff8f… -> QUARANTINED
  seq   79  2026-09-14T10:57:09.000Z  promote      system aievidence-gate
            wrote AEDECOD = 'Hypoaesthesia' to the dataset WITHOUT A REVIEW (forced)

  AEDECOD: PROMOTED
  * AEDECOD: PROMOTED WITHOUT REVIEW at seq 79. No human signed this value.

$ aiev tamper --seq 16 --field payload.value --set "Migraine"     # demo only
DEMO ONLY: edited seq 16 in place (payload.value).
$ aiev verify
BROKEN at seq 16: stored hash does not match event content

$ aiev run-demo >/dev/null && aiev datasheet --out demo/datasheet.html
wrote demo/datasheet.html
wrote demo/manifest.json (ledger head a9babf7075a42f41…, 96 events)
```

The same record, when the process was followed:

```
$ aiev ask --record AE:AIEV-001-1001:1
Record AE:AIEV-001-1001:1: 4 events
  seq    1  2026-09-14T09:01:52.000Z  ai_output    model stub-coder v1.0.0
            proposed AEDECOD = 'Headache' (confidence 0.88); rationale: dictionary match on 'headache'; inputs_hash 9e89bd7aa879…, prompt_hash e6f4591dff8f… -> QUARANTINED
  seq    2  2026-09-14T09:03:49.000Z  review       rmehta (PharmD, Clinical Data Manager)
            APPROVE after 117s; signed 'Approved for promotion to AEDECOD' by Rina Mehta
  seq    3  2026-09-14T09:03:54.000Z  promote      rmehta (PharmD, Clinical Data Manager)
            wrote AEDECOD = 'Headache' to the dataset (review seq 2)
  seq   95  2026-09-14T12:19:35.000Z  endorsement  pi_site01 (MD, Principal Investigator, Site 01)
            investigator endorsement: 'Investigator endorsement of reported data for AE:AIEV-001-1001:1'
```

`aiev run-demo` is deterministic: a simulated clock and a seeded study mean the ledger comes back byte-identical, so it doubles as the reset button after a tamper.

## How it works

```
site data (CSV)  ──►  AI adapter  ──►  ai_output event ──► QUARANTINED
                     (stub or LLM)           │
                                             ▼
                                  review event (printed name, time,
                                  meaning of signature, credential)
                                             │
                                             ▼
                                  promote ──► value written to CSV
                                  (or reject; corrections are new events)

every event: seq, ts, agent, record_ref, field, payload, prev_hash, hash
```

- **Ledger** (`aievidence/ledger.py`): append-only JSONL, each line hashed over its content plus the previous line's hash. `verify()` names the first broken seq. Nothing is deleted; corrections point at the seq they supersede.
- **Gate** (`aievidence/gate.py`): an `ai_output` is quarantined. A `review` needs a reviewer id, printed name, credential, decision and a signature manifestation (21 CFR 11.50). Only then can `promote` write to the dataset. `promote(force=True)` exists so the demo can plant an unreviewed promotion; it is always flagged.
- **Rules** (`aievidence/rules.py`): seven exception rules evaluated over the whole ledger. They never trust a payload's claim about another event; a promote that *says* it was reviewed is still EX-01 if no review event exists.
- **Profile** (`aievidence/profiles/clinical_gcp.yaml`): thresholds, citations, the crosswalk and the ALCOA+ scorecard are content, not code. A wrong clause number is a one-line fix and changes the profile fingerprint printed on the datasheet. A GMP profile would be a second file with no code change.
- **Datasheet** (`aievidence/datasheet.py`): one printable HTML file plus `manifest.json` carrying the ledger head hash, event count and profile fingerprint under a signature. Demo signing is HMAC; `Ed25519Signer` is the production choice.
- **AI adapters** (`aievidence/ai/`): a deterministic stub coder and query generator, and an optional LLM coder (`aiev run-demo --coder llm` with `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) that records the real model string and a prompt hash that is stable across runs.

## Exceptions

| ID | Rule | Why an inspector cares |
|---|---|---|
| EX-01 | Unreviewed promotion | 21 CFR 211.22(c) by analogy; E6(R3) Annex 1 §4 (changes authorised and in the audit trail) |
| EX-02 | Rubber-stamp review (under 5 s) | E6(R3): audit-trail review must be meaningful and documented |
| EX-03 | Model version drift with no `model_change` event | FDA credibility framework step 7 and lifecycle maintenance; 21 CFR 11.10(k) |
| EX-04 | Change after investigator endorsement, no re-endorsement | E6(R3) Annex 1 §4.2 |
| EX-05 | Reviewer with no credential, or not in the directory | 21 CFR 11.10(d),(g); 11.100 |
| EX-06 | `ai_output` missing `inputs_hash`, `prompt_hash`, `model_id` or `model_version` | FDA-EMA Good AI Practice provenance principle; ALCOA+ |
| EX-07 | Chain integrity failure | 21 CFR 11.10(e) |

## Crosswalk

| Record field | ALCOA+ | 21 CFR Part 11 | ICH E6(R3) | FDA AI credibility step |
|---|---|---|---|---|
| `agent.id / version` (model) | Attributable | 11.10(k) | Annex 1 §4.3 computerised systems | Step 2 (context of use), Step 7 (adequacy; lifecycle) |
| `inputs_hash`, `prompt_hash` | Original, Traceable | 11.10(b),(c) | Annex 1 §4.2 data life cycle (metadata) | Steps 5–6 (execution and results documented) |
| `ts` | Contemporaneous | 11.10(e) | Annex 1 §4.2 (audit trail) | — |
| `hash`, `prev_hash` | Enduring, Consistent | 11.10(c),(e) | Annex 1 §4.3 (audit trail integrity) | — |
| `review.*` + signature manifestation | Attributable, Accurate | 11.50, 11.70, 11.100, 11.200 | Annex 1 §4.2 (data changes authorised) | Step 3 (model risk; human oversight) |
| `endorsement` | Complete, Accurate | 11.70 | Annex 1 §4.2 (investigator endorsement) | — |
| `model_change` | Consistent | 11.10(k) | Annex 1 §4.3 (validation, change control) | Step 7 |
| Datasheet `context_of_use` | — | — | — | Steps 1–2 |
| Datasheet `model_risk` | — | — | — | Step 3 (influence × consequence) |

Clause numbers are held in `clinical_gcp.yaml` and should be verified against the primary texts before relying on them; the file header lists which.

## CLI

```
aiev run-demo [--coder stub|llm] [--seed N]   # synth data + planted scenario -> demo/ledger.jsonl, demo/data/*.csv
aiev verify [--manifest demo/manifest.json]  # chain integrity; exit 1 on break, prints first broken seq
aiev tamper --seq 16 --field payload.value --set "Migraine" [--rehash]   # demo only; then run verify
aiev ask --record AE:AIEV-001-1042:3 [--field AEDECOD]   # full chain for one record, human-readable
aiev exceptions [--json]                     # table of EX-xx findings; exit 1 if any
aiev datasheet --out demo/datasheet.html [--pdf]   # + manifest.json
aiev review --record AE:AIEV-001-1096:2 --reviewer rmehta [--decision approve|edit|reject]   # omit --decision for a timed, interactive review
```

The planted problems live in `demo/scenario.py` as plain constants. Edit them and re-run `aiev run-demo`. The one-hour session plan is in `demo/DEMO_SCRIPT.md`.

## Ledger event shape

```json
{
  "seq": 2,
  "ts": "2026-09-14T09:03:49.000Z",
  "event_type": "review",
  "study_id": "AIEV-001",
  "record_ref": "AE:AIEV-001-1001:1",
  "field": "AEDECOD",
  "agent": {"kind": "human", "id": "rmehta", "version": null, "credential": "PharmD, Clinical Data Manager"},
  "payload": {
    "decision": "approve", "reviewed_seq": 1, "proposed_value": "Headache", "edited_value": null,
    "review_seconds": 117, "note": null,
    "signature": {"printed_name": "Rina Mehta", "signed_at": "2026-09-14T09:03:49.000Z", "meaning": "Approved for promotion to AEDECOD"}
  },
  "prev_hash": "…", "hash": "…"
}
```

Event types: `ai_output | review | promote | reject | correction | endorsement | model_change`. The agent/activity/entity split follows W3C PROV so the ledger can be exported as PROV-JSON later.

## What this is not

Not an EDC. Not RBQM or central statistical monitoring. Not a medical coding product. Not trial-design AI. Not real-time data transport. No UI beyond the HTML datasheet. No real patient data. No authentication, no multi-tenancy. It is a demo of an evidence record, built to be broken by an auditor in an hour.

## Development

```
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```

Tests cover: the chain verifies and a single-byte tamper breaks it at that seq; the gate cannot promote without a review and signatures carry the required fields; each planted exception is detected and a clean ledger has zero; every scorecard row has a citation and `manifest.json` carries the ledger head hash.

## Lineage

Patterns lifted from the author's other repositories: profiles-as-content and "enforce, then publish what you enforced" from `governed-data-platform`; the prospective ledger, W3C PROV vocabulary and deterministic gate from `decision_gate`; the signed, portable manifest from `corpuscle`.

## License

MIT.
