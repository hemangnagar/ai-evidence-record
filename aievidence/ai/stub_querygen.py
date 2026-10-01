"""Deterministic data-query generator.

Three checks a data manager would run on an adverse-event record joined to its
subject's demographics. Output is the query text aimed at the site, or ``None``
when the record is clean. Confidence is 1.0 because the rules are exact.
"""

from __future__ import annotations

from . import AIOutput, inputs_hash, prompt_hash

INPUT_FIELDS = ["USUBJID", "AESEQ", "AETERM", "AESTDTC", "AEENDTC", "AESEV", "AESER", "RFICDTC"]

PROMPT_TEMPLATE = (
    "stub-querygen/v1: flag AEENDTC earlier than AESTDTC; flag AESER=Y with blank AESEV; "
    "flag AESTDTC earlier than the subject's RFICDTC. One query per record, first rule that fires."
)


class StubQueryGen:
    model_id = "stub-querygen"
    model_version = "1.0.0"
    prompt_hash = prompt_hash(PROMPT_TEMPLATE)

    def run(self, record: dict) -> AIOutput:
        ih = inputs_hash(record, INPUT_FIELDS)
        start, end = record.get("AESTDTC") or "", record.get("AEENDTC") or ""
        if start and end and end < start:
            return AIOutput(
                value=f"AE end date {end} is before start date {start}. Please confirm both dates.",
                confidence=1.0,
                rationale="rule: end-before-start",
                inputs_hash=ih,
            )
        if (record.get("AESER") or "").upper() == "Y" and not (record.get("AESEV") or "").strip():
            return AIOutput(
                value="Event is marked serious but severity is blank. Please provide AESEV.",
                confidence=1.0,
                rationale="rule: serious-without-severity",
                inputs_hash=ih,
            )
        consent = record.get("RFICDTC") or ""
        if start and consent and start < consent:
            return AIOutput(
                value=(
                    f"AE start date {start} is before informed consent {consent}. "
                    "Please confirm the date or document as medical history."
                ),
                confidence=1.0,
                rationale="rule: ae-before-consent",
                inputs_hash=ih,
            )
        return AIOutput(value=None, confidence=1.0, rationale="no query", inputs_hash=ih)
