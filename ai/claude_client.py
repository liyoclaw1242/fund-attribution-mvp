"""Claude API client with number verification and fallback.

Pipeline:
  1. prompt_builder constructs prompt from AttributionResult
  2. Call Claude API with 10s timeout
  3. number_verifier extracts all % from response, compares to source
  4. If ALL match: use AI summary. If ANY mismatch: rule-based fallback.
"""

import json
import logging
from typing import Optional

import anthropic

from config.settings import ANTHROPIC_API_KEY, AI_TIMEOUT_SECONDS
from interfaces import AISummary
from ai.prompt_builder import build_prompt
from ai.number_verifier import verify_numbers
from ai.fallback_template import generate_fallback

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"


def generate_summary(
    result: dict,
    api_key: Optional[str] = None,
    timeout: int = AI_TIMEOUT_SECONDS,
) -> AISummary:
    """Generate AI summary with verification and fallback.

    Args:
        result: AttributionResult dict from Brinson engine.
        api_key: Anthropic API key. If None, uses env/settings.
        timeout: API call timeout in seconds.

    Returns:
        AISummary TypedDict.
    """
    prompt = build_prompt(result)
    key = api_key or ANTHROPIC_API_KEY

    if not key:
        logger.warning("No API key — using fallback template")
        return _build_fallback_summary(result, prompt)

    try:
        ai_text = _call_claude(prompt, key, timeout)
        parsed = _parse_response(ai_text)

        if parsed is None:
            logger.warning("Failed to parse AI response — using fallback")
            return _build_fallback_summary(result, prompt)

        # Verify numbers in all 3 formats
        all_text = f"{parsed['line_message']} {parsed['pdf_summary']} {parsed['advisor_note']}"
        verification = verify_numbers(all_text, result)

        if not verification.passed:
            logger.warning(
                "Number verification failed — %d mismatches: %s — using fallback",
                len(verification.mismatches),
                verification.mismatches,
            )
            return _build_fallback_summary(result, prompt)

        logger.info("AI summary verified — all numbers match")
        return AISummary(
            line_message=parsed["line_message"],
            pdf_summary=parsed["pdf_summary"],
            advisor_note=parsed["advisor_note"],
            verification_passed=True,
            fallback_used=False,
            ai_prompt=prompt,
        )

    except anthropic.APITimeoutError:
        logger.warning("Claude API timeout (%ds) — using fallback", timeout)
        return _build_fallback_summary(result, prompt)

    except Exception as e:
        logger.warning("Claude API error: %s — using fallback", e)
        return _build_fallback_summary(result, prompt)


def _call_claude(prompt: str, api_key: str, timeout: int) -> str:
    """Call Claude API and return the text response."""
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        timeout=timeout,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _parse_response(text: str) -> Optional[dict]:
    """Parse Claude response as JSON with 3 summary keys."""
    # Try to extract JSON from markdown code block
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    required = ["line_message", "pdf_summary", "advisor_note"]
    if not all(k in data for k in required):
        return None

    return data


def _build_fallback_summary(result: dict, prompt: str) -> AISummary:
    """Build AISummary using rule-based fallback templates."""
    fallback = generate_fallback(result)
    return AISummary(
        line_message=fallback["line_message"],
        pdf_summary=fallback["pdf_summary"],
        advisor_note=fallback["advisor_note"],
        verification_passed=False,
        fallback_used=True,
        ai_prompt=prompt,
    )
