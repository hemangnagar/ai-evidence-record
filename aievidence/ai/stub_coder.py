"""Deterministic verbatim-to-preferred-term coder.

A dictionary plus normalisation and a fuzzy fallback. It exists so the demo runs
with no network and no key, and so the ledger has a model whose version can be
bumped mid-study on purpose. The terms are MedDRA-style preferred terms chosen
for plausibility; this is not MedDRA and makes no claim to be.
"""

from __future__ import annotations

import difflib
import re

from . import AIOutput, inputs_hash, prompt_hash

INPUT_FIELDS = ["AETERM"]

PROMPT_TEMPLATE = (
    "stub-coder/v1: normalise the verbatim (lowercase, strip punctuation, collapse whitespace), "
    "match the longest dictionary keyword, fall back to a fuzzy token match, return the preferred term "
    "with a confidence."
)

# keyword (normalised) -> preferred term. Longer keywords win so "injection site redness" beats "redness".
DICTIONARY: dict[str, str] = {
    "headache": "Headache",
    "migraine": "Migraine",
    "nausea": "Nausea",
    "vomiting": "Vomiting",
    "vomitting": "Vomiting",
    "elevated lfts": "Hepatic enzyme increased",
    "lfts elevated": "Hepatic enzyme increased",
    "alt increased": "Alanine aminotransferase increased",
    "rash": "Rash",
    "dizzy": "Dizziness",
    "dizziness": "Dizziness",
    "tired": "Fatigue",
    "fatigue": "Fatigue",
    "trouble sleeping": "Insomnia",
    "insomnia": "Insomnia",
    "stomach cramps": "Abdominal pain",
    "abdominal pain": "Abdominal pain",
    "runny nose": "Rhinorrhoea",
    "sore throat": "Oropharyngeal pain",
    "cough": "Cough",
    "fever": "Pyrexia",
    "temp": "Pyrexia",
    "joint pain": "Arthralgia",
    "back ache": "Back pain",
    "back pain": "Back pain",
    "injection site redness": "Injection site erythema",
    "injection site": "Injection site reaction",
    "itching": "Pruritus",
    "itchy": "Pruritus",
    "diarrhea": "Diarrhoea",
    "diarrhoea": "Diarrhoea",
    "constipated": "Constipation",
    "constipation": "Constipation",
    "heartburn": "Dyspepsia",
    "high bp": "Hypertension",
    "palpitations": "Palpitations",
    "shortness of breath": "Dyspnoea",
    "short of breath": "Dyspnoea",
    "bruised": "Contusion",
    "fell": "Fall",
    "uti": "Urinary tract infection",
    "common cold": "Nasopharyngitis",
    "head cold": "Nasopharyngitis",
    "low mood": "Depressed mood",
    "anxious": "Anxiety",
    "blurry vision": "Vision blurred",
    "numbness": "Hypoaesthesia",
    "tingling": "Paraesthesia",
    "loss of appetite": "Decreased appetite",
    "no appetite": "Decreased appetite",
    "chest pain": "Chest pain",
    "muscle ache": "Myalgia",
    "swollen ankles": "Peripheral swelling",
}


def normalise(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9/ ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class StubCoder:
    model_id = "stub-coder"
    prompt_hash = prompt_hash(PROMPT_TEMPLATE)

    def __init__(self, model_version: str = "1.0.0"):
        self.model_version = model_version
        self._keys = sorted(DICTIONARY, key=len, reverse=True)

    def run(self, record: dict) -> AIOutput:
        verbatim = str(record.get("AETERM") or "")
        norm = normalise(verbatim)
        ih = inputs_hash(record, INPUT_FIELDS)

        hits = [k for k in self._keys if re.search(rf"\b{re.escape(k)}\b", norm)]
        if hits:
            # Longest keyword first; extra hits lower confidence because the verbatim bundles symptoms.
            term = DICTIONARY[hits[0]]
            others = {DICTIONARY[h] for h in hits[1:]} - {term}
            if others:
                return AIOutput(
                    value=term,
                    confidence=0.62,
                    rationale=(
                        f"verbatim mentions more than one event ({term}; also {', '.join(sorted(others))}); "
                        "coded the first and recommend splitting"
                    ),
                    inputs_hash=ih,
                )
            conf = 0.96 if hits[0] == norm else 0.88
            return AIOutput(value=term, confidence=conf, rationale=f"dictionary match on '{hits[0]}'", inputs_hash=ih)

        # Fuzzy fallback over whole-string similarity.
        best, score = None, 0.0
        for k in self._keys:
            r = difflib.SequenceMatcher(None, norm, k).ratio()
            if r > score:
                best, score = k, r
        if best is not None and score >= 0.6:
            return AIOutput(
                value=DICTIONARY[best],
                confidence=round(0.4 + 0.4 * score, 2),
                rationale=f"fuzzy match to '{best}' (ratio {score:.2f})",
                inputs_hash=ih,
            )
        return AIOutput(value=None, confidence=0.0, rationale="no match; needs manual coding", inputs_hash=ih)
