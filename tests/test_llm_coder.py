"""Acceptance test 7. Makes real API calls, so it runs only when a key is present."""

from __future__ import annotations

import pytest

from aievidence.ai.llm_coder import LLMCoder, anthropic_client_kwargs


def test_key_resolution_prefers_project_variable():
    env = {"CORPUSCLE_ANTHROPIC_KEY": "k1", "ANTHROPIC_API_KEY": "k2", "ANTHROPIC_BASE_URL": "https://proxy"}
    kw = anthropic_client_kwargs(env)
    assert kw["api_key"] == "k1" and kw["base_url"] == "https://api.anthropic.com"
    assert anthropic_client_kwargs({"ANTHROPIC_API_KEY": "k2"}) == {}
    assert anthropic_client_kwargs({}) is None


@pytest.mark.skipif(anthropic_client_kwargs() is None, reason="no Anthropic credential in the environment")
def test_live_coder_records_real_model_and_stable_prompt_hash():
    a, b = LLMCoder(), LLMCoder()
    assert a.prompt_hash == b.prompt_hash
    out = a.run({"AETERM": "HEADACHE WORSE SINCE DOSE 2"})
    assert out.value and 0 <= out.confidence <= 1 and out.inputs_hash
    assert a.model_id.startswith("claude-")
