"""Synthetic CDISC SDTM-shaped study. Seeded, so every run produces the same bytes.

No real identifiers, no real patients, no real sites. Verbatims are written the
way site staff type them, because a coder's job is harder than a dictionary.
Three data problems are planted for the query generator to find.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

STUDY_ID = "AIEV-001"
SITES = ["01", "02", "03"]
ARMS = ["PLACEBO", "AIEV-100 MG"]

# (verbatim, severity, serious, relationship). Written as site data entry, warts and all.
VERBATIMS: list[tuple[str, str, str, str]] = [
    ("HEADACHE WORSE SINCE DOSE 2", "MODERATE", "N", "POSSIBLE"),
    ("nausea/vomitting x2 days", "MILD", "N", "PROBABLE"),
    ("Elevated LFTs", "MODERATE", "N", "POSSIBLE"),
    ("rash L forearm", "MILD", "N", "UNLIKELY"),
    ("dizzy spells", "MILD", "N", "POSSIBLE"),
    ("tired all the time", "MILD", "N", "POSSIBLE"),
    ("trouble sleeping", "MILD", "N", "UNLIKELY"),
    ("stomach cramps after breakfast", "MODERATE", "N", "POSSIBLE"),
    ("runny nose", "MILD", "N", "NOT RELATED"),
    ("sore throat, cough", "MILD", "N", "NOT RELATED"),
    ("Fever 38.5 C", "MODERATE", "N", "POSSIBLE"),
    ("joint pain both knees", "MODERATE", "N", "UNLIKELY"),
    ("back ache", "MILD", "N", "NOT RELATED"),
    ("injection site redness", "MILD", "N", "PROBABLE"),
    ("itching all over", "MODERATE", "N", "POSSIBLE"),
    ("diarrhea x3", "MILD", "N", "POSSIBLE"),
    ("constipated", "MILD", "N", "UNLIKELY"),
    ("heartburn", "MILD", "N", "POSSIBLE"),
    ("High BP 150/95", "MODERATE", "N", "POSSIBLE"),
    ("palpitations", "MODERATE", "Y", "POSSIBLE"),
    ("shortness of breath climbing stairs", "SEVERE", "Y", "POSSIBLE"),
    ("fell and bruised hip", "MODERATE", "N", "NOT RELATED"),
    ("UTI", "MILD", "N", "NOT RELATED"),
    ("head cold", "MILD", "N", "NOT RELATED"),
    ("low mood", "MILD", "N", "POSSIBLE"),
    ("anxious before visits", "MILD", "N", "UNLIKELY"),
    ("blurry vision L eye", "MODERATE", "N", "POSSIBLE"),
    ("numbness in fingers", "MILD", "N", "POSSIBLE"),
    ("loss of appetite", "MILD", "N", "POSSIBLE"),
    ("chest pain on exertion", "SEVERE", "Y", "POSSIBLE"),
]

CONMEDS = [
    "paracetamol 500mg prn",
    "ibuprofen 400 mg",
    "omeprazole 20mg od",
    "metformin 500 bd",
    "lisinopril 10mg",
    "atorvastatin 20 mg nocte",
    "cetirizine",
    "salbutamol inhaler prn",
    "amoxicillin 500 tds x7d",
    "multivitamin",
    "levothyroxine 50mcg",
    "sertraline 50mg",
    "loratadine 10mg",
    "aspirin 75mg",
    "vitamin D 1000 IU",
    "senna 7.5mg nocte",
    "ondansetron 4mg prn",
    "ramipril 5 mg",
    "amlodipine 5mg",
    "zopiclone 7.5mg prn",
]


@dataclass
class Study:
    study_id: str
    dm: list[dict] = field(default_factory=list)
    ae: list[dict] = field(default_factory=list)
    cm: list[dict] = field(default_factory=list)

    def subject(self, usubjid: str) -> dict:
        return next(r for r in self.dm if r["USUBJID"] == usubjid)

    def ae_record(self, usubjid: str, aeseq: int) -> dict:
        return next(r for r in self.ae if r["USUBJID"] == usubjid and int(r["AESEQ"]) == aeseq)


def _iso(d: date) -> str:
    return d.isoformat()


def generate(seed: int = 7, n_subjects: int = 12) -> Study:
    rng = random.Random(seed)
    study = Study(STUDY_ID)
    base = date(2026, 6, 1)

    subject_ids = [1001, 1017, 1023, 1042, 1058, 1061, 1074, 1089, 1096, 1103, 1115, 1128][:n_subjects]
    for i, sid in enumerate(subject_ids):
        consent = base + timedelta(days=rng.randint(0, 20))
        study.dm.append(
            {
                "STUDYID": STUDY_ID,
                "USUBJID": f"{STUDY_ID}-{sid}",
                "SITEID": SITES[i % len(SITES)],
                "ARM": ARMS[i % 2],
                "SEX": rng.choice(["F", "M"]),
                "AGE": rng.randint(24, 71),
                "RFICDTC": _iso(consent),
                "RFSTDTC": _iso(consent + timedelta(days=rng.randint(3, 10))),
            }
        )

    # Deal verbatims across subjects in a fixed order, so record refs are stable.
    per_subject: dict[str, int] = {r["USUBJID"]: 0 for r in study.dm}
    order = list(range(len(VERBATIMS)))
    for idx in order:
        verbatim, sev, ser, rel = VERBATIMS[idx]
        subj = study.dm[idx % len(study.dm)]
        usubjid = subj["USUBJID"]
        per_subject[usubjid] += 1
        first_dose = date.fromisoformat(subj["RFSTDTC"])
        start = first_dose + timedelta(days=rng.randint(1, 60))
        end = start + timedelta(days=rng.randint(0, 14))
        study.ae.append(
            {
                "STUDYID": STUDY_ID,
                "USUBJID": usubjid,
                "AESEQ": per_subject[usubjid],
                "AETERM": verbatim,
                "AEDECOD": "",
                "AESTDTC": _iso(start),
                "AEENDTC": _iso(end),
                "AESEV": sev,
                "AESER": ser,
                "AEREL": rel,
            }
        )

    # Planted data problems for the query generator.
    # 1. end before start
    ae_end_before_start = study.ae[7]
    s = date.fromisoformat(ae_end_before_start["AESTDTC"])
    ae_end_before_start["AEENDTC"] = _iso(s - timedelta(days=3))
    # 2. serious with severity blank
    ae_serious_blank = study.ae[19]
    ae_serious_blank["AESER"] = "Y"
    ae_serious_blank["AESEV"] = ""
    # 3. AE before informed consent
    ae_before_consent = study.ae[23]
    consent = date.fromisoformat(study.subject(ae_before_consent["USUBJID"])["RFICDTC"])
    ae_before_consent["AESTDTC"] = _iso(consent - timedelta(days=5))
    ae_before_consent["AEENDTC"] = _iso(consent - timedelta(days=1))

    for i, cmtrt in enumerate(CONMEDS):
        subj = study.dm[(i * 5) % len(study.dm)]
        start = date.fromisoformat(subj["RFICDTC"]) - timedelta(days=rng.randint(0, 400))
        study.cm.append(
            {
                "STUDYID": STUDY_ID,
                "USUBJID": subj["USUBJID"],
                "CMSEQ": i + 1,
                "CMTRT": cmtrt,
                "CMSTDTC": _iso(start),
                "CMONGO": rng.choice(["Y", "N"]),
            }
        )
    return study


def write_csvs(study: Study, data_dir: str | Path) -> dict[str, Path]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for domain, rows in (("DM", study.dm), ("AE", study.ae), ("CM", study.cm)):
        path = data_dir / f"{domain}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        out[domain] = path
    return out
