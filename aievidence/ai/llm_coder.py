"""Optional LLM coder. Same interface as the stub; a real model string in the ledger.

Used only when ``aiev run-demo --coder llm`` is passed and a key is present
(``ANTHROPIC_API_KEY`` first, else ``OPENAI_API_KEY``). The prompt template is a
module constant so ``prompt_hash`` is stable across runs, which is what lets the
datasheet say "these 30 outputs came from the same prompt".

The model proposes; the gate still quarantines; a human still signs.
"""

from __future__ import annotations

import json
import os

from . import AIOutput, inputs_hash, prompt_hash

INPUT_FIELDS = ["AETERM"]

PROMPT_TEMPLATE = (
    "You are coding an adverse-event verbatim from a clinical trial case report form to a single "
    "MedDRA-style preferred term.\n"
    "Return JSON only, with keys: preferred_term (string), confidence (number 0-1), rationale (one sentence).\n"
    "If the verbatim bundles more than one event, code the first and say so in the rationale.\n"
    "Verbatim: {verbatim}"
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "preferred_term": {"type": "string"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["preferred_term", "confidence", "rationale"],
    "additionalProperties": False,
}

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class LLMCoder:
    prompt_hash = prompt_hash(PROMPT_TEMPLATE)

    def __init__(self, model: str | None = None):
        if os.environ.get("ANTHROPIC_API_KEY"):
            self.provider = "anthropic"
            self.model_id = model or os.environ.get("AIEV_LLM_MODEL", DEFAULT_ANTHROPIC_MODEL)
        elif os.environ.get("OPENAI_API_KEY"):
            self.provider = "openai"
            self.model_id = model or os.environ.get("AIEV_LLM_MODEL", DEFAULT_OPENAI_MODEL)
        else:
            raise RuntimeError("LLMCoder needs ANTHROPIC_API_KEY or OPENAI_API_KEY in the environment")
        # The dated model string is the version. If the provider reports a different served model,
        # the first call updates this so the ledger carries what actually ran.
        self.model_version = self.model_id
        self._client = None

    def _anthropic(self, prompt: str) -> str:
        import anthropic

        if self._client is None:
            self._client = anthropic.Anthropic()
        response = self._client.messages.create(
            model=self.model_id,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("model declined the request")
        if response.model:
            self.model_id = self.model_version = response.model
        return next(b.text for b in response.content if b.type == "text")

    def _openai(self, prompt: str) -> str:
        from openai import OpenAI

        if self._client is None:
            self._client = OpenAI()
        response = self._client.chat.completions.create(
            model=self.model_id,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        if response.model:
            self.model_id = self.model_version = response.model
        return response.choices[0].message.content or "{}"

    def run(self, record: dict) -> AIOutput:
        verbatim = str(record.get("AETERM") or "")
        ih = inputs_hash(record, INPUT_FIELDS)
        prompt = PROMPT_TEMPLATE.format(verbatim=verbatim)
        raw = self._anthropic(prompt) if self.provider == "anthropic" else self._openai(prompt)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return AIOutput(
                value=None, confidence=0.0, rationale=f"unparseable model output: {raw[:120]}", inputs_hash=ih
            )
        return AIOutput(
            value=data.get("preferred_term") or None,
            confidence=float(data.get("confidence") or 0.0),
            rationale=data.get("rationale"),
            inputs_hash=ih,
        )
