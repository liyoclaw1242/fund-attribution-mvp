"""Tests for ai/ modules — prompt builder, number verifier, fallback, client."""

import json
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from ai.fallback_template import (
    generate_line_message,
    generate_pdf_summary,
    generate_advisor_note,
    generate_fallback,
)
from ai.number_verifier import (
    extract_percentages,
    verify_numbers,
    get_source_numbers,
)
from ai.prompt_builder import build_prompt
from ai.claude_client import generate_summary, _parse_response


# Shared test fixture
SAMPLE_RESULT = {
    "fund_return": 0.0587,
    "bench_return": 0.0537,
    "excess_return": 0.005,
    "allocation_total": 0.002,
    "selection_total": 0.003,
    "interaction_total": None,
    "brinson_mode": "BF2",
    "detail": pd.DataFrame([
        {"industry": "半導體業", "Wp": 0.42, "Wb": 0.40, "Rp": 0.085, "Rb": 0.080,
         "alloc_effect": 0.001, "select_effect": 0.002, "total_contrib": 0.003},
    ]),
    "top_contributors": pd.DataFrame([
        {"industry": "半導體業", "total_contrib": 0.003},
    ]),
    "bottom_contributors": pd.DataFrame([
        {"industry": "金融保險業", "total_contrib": -0.001},
    ]),
    "validation_passed": True,
    "unmapped_weight": 0.0,
    "unmapped_industries": [],
}


# ============================================================
# Fallback Template Tests
# ============================================================
class TestFallbackTemplate:
    def test_line_message_positive(self):
        msg = generate_line_message(SAMPLE_RESULT)
        assert "📈" in msg
        assert "5.87%" in msg
        assert len(msg) <= 100

    def test_line_message_negative(self):
        result = {**SAMPLE_RESULT, "excess_return": -0.005}
        msg = generate_line_message(result)
        assert "📉" in msg

    def test_pdf_summary_contains_numbers(self):
        summary = generate_pdf_summary(SAMPLE_RESULT)
        assert "5.87%" in summary
        assert "5.37%" in summary
        assert "0.20%" in summary  # allocation
        assert "0.30%" in summary  # selection

    def test_pdf_summary_bf3(self):
        result = {**SAMPLE_RESULT, "brinson_mode": "BF3", "interaction_total": 0.001}
        summary = generate_pdf_summary(result)
        assert "交互效果" in summary

    def test_advisor_note_compact(self):
        note = generate_advisor_note(SAMPLE_RESULT)
        assert len(note) <= 50
        assert "5.87%" in note

    def test_generate_fallback_all_keys(self):
        fb = generate_fallback(SAMPLE_RESULT)
        assert "line_message" in fb
        assert "pdf_summary" in fb
        assert "advisor_note" in fb


# ============================================================
# Number Verifier Tests
# ============================================================
class TestNumberVerifier:
    def test_extract_percentages(self):
        text = "基金報酬5.87%，基準5.37%，超額0.50%"
        pcts = extract_percentages(text)
        assert len(pcts) == 3
        assert pcts[0] == pytest.approx(0.0587)
        assert pcts[1] == pytest.approx(0.0537)

    def test_extract_negative(self):
        pcts = extract_percentages("虧損-2.50%")
        assert pcts[0] == pytest.approx(-0.025)

    def test_extract_no_numbers(self):
        pcts = extract_percentages("沒有任何數字")
        assert len(pcts) == 0

    def test_verify_pass(self):
        text = "基金報酬5.87%，基準5.37%，超額0.50%"
        vr = verify_numbers(text, SAMPLE_RESULT)
        assert vr.passed

    def test_verify_fail_hallucinated(self):
        text = "基金報酬12.34%"  # not in source
        vr = verify_numbers(text, SAMPLE_RESULT)
        assert not vr.passed
        assert len(vr.mismatches) == 1

    def test_verify_no_numbers_passes(self):
        text = "表現良好，優於同期基準"
        vr = verify_numbers(text, SAMPLE_RESULT)
        assert vr.passed

    def test_get_source_numbers(self):
        numbers = get_source_numbers(SAMPLE_RESULT)
        assert 0.0587 in numbers
        assert 0.0537 in numbers


# ============================================================
# Prompt Builder Tests
# ============================================================
class TestPromptBuilder:
    def test_builds_prompt(self):
        prompt = build_prompt(SAMPLE_RESULT)
        assert "5.87%" in prompt
        assert "5.37%" in prompt
        assert "Brinson" in prompt  # in the forbidden list
        assert "市場佈局" in prompt
        assert "選股能力" in prompt

    def test_no_forbidden_terms_in_data_section(self):
        prompt = build_prompt(SAMPLE_RESULT)
        # The data section should use Chinese terms, not English
        data_section = prompt.split("## 分析數據")[1].split("## 請產出")[0]
        assert "allocation effect" not in data_section
        assert "selection effect" not in data_section

    def test_bf3_includes_interaction(self):
        result = {**SAMPLE_RESULT, "brinson_mode": "BF3", "interaction_total": 0.001}
        prompt = build_prompt(result)
        assert "交互效果" in prompt
        assert "0.10%" in prompt


# ============================================================
# Claude Client Tests
# ============================================================
class TestParseResponse:
    def test_parse_json(self):
        text = '{"line_message": "test", "pdf_summary": "test2", "advisor_note": "test3"}'
        result = _parse_response(text)
        assert result["line_message"] == "test"

    def test_parse_json_in_code_block(self):
        text = '```json\n{"line_message": "a", "pdf_summary": "b", "advisor_note": "c"}\n```'
        result = _parse_response(text)
        assert result is not None
        assert result["line_message"] == "a"

    def test_parse_invalid_json(self):
        assert _parse_response("not json at all") is None

    def test_parse_missing_keys(self):
        assert _parse_response('{"line_message": "only one"}') is None


class TestGenerateSummary:
    def test_no_api_key_uses_fallback(self):
        result = generate_summary(SAMPLE_RESULT, api_key="")
        assert result["fallback_used"] is True
        assert "5.87%" in result["line_message"]

    def test_api_timeout_uses_fallback(self):
        with patch("ai.claude_client._call_claude") as mock:
            import anthropic
            mock.side_effect = anthropic.APITimeoutError(request=MagicMock())
            result = generate_summary(SAMPLE_RESULT, api_key="sk-test")
        assert result["fallback_used"] is True

    def test_api_success_with_verification(self):
        good_response = json.dumps({
            "line_message": "📈 基金報酬5.87%，超越基準5.37%",
            "pdf_summary": "基金報酬率為5.87%，基準為5.37%，超額報酬0.50%，配置效果0.20%，選股效果0.30%",
            "advisor_note": "基金5.87% 超額0.50% 配置0.20% 選股0.30%",
        })
        with patch("ai.claude_client._call_claude", return_value=good_response):
            result = generate_summary(SAMPLE_RESULT, api_key="sk-test")
        assert result["fallback_used"] is False
        assert result["verification_passed"] is True

    def test_api_hallucination_triggers_fallback(self):
        bad_response = json.dumps({
            "line_message": "📈 基金報酬12.00%",  # hallucinated number
            "pdf_summary": "報酬率12.00%",
            "advisor_note": "基金12.00%",
        })
        with patch("ai.claude_client._call_claude", return_value=bad_response):
            result = generate_summary(SAMPLE_RESULT, api_key="sk-test")
        assert result["fallback_used"] is True
        assert result["verification_passed"] is False
