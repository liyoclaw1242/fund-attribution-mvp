"""Build structured prompt from AttributionResult for Claude API.

Output: 3 variants
  - LINE message: <100 chars Chinese with emoji
  - PDF summary: 150-200 chars professional Chinese
  - Advisor note: <50 chars metrics only

Prompt principles:
  - Role: senior investment research director
  - Forbidden terms: Brinson, attribution, allocation effect, selection effect
  - Use: market positioning, stock-picking ability, sector exposure
  - Instruction: use ONLY exact numbers provided, do NOT round/adjust/estimate
"""


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def build_prompt(result: dict) -> str:
    """Build a Claude prompt from AttributionResult.

    Args:
        result: AttributionResult dict.

    Returns:
        Full prompt string for Claude API.
    """
    fund_ret = _fmt_pct(result["fund_return"])
    bench_ret = _fmt_pct(result["bench_return"])
    excess_ret = _fmt_pct(result["excess_return"])
    alloc = _fmt_pct(result["allocation_total"])
    select = _fmt_pct(result["selection_total"])
    mode = result.get("brinson_mode", "BF2")

    # Build top/bottom contributors text
    top_text = ""
    top = result.get("top_contributors")
    if top is not None and len(top) > 0:
        lines = []
        for _, row in top.head(3).iterrows():
            lines.append(f"  - {row['industry']}: 總貢獻 {_fmt_pct(row['total_contrib'])}")
        top_text = "正面貢獻前三產業:\n" + "\n".join(lines)

    bottom_text = ""
    bottom = result.get("bottom_contributors")
    if bottom is not None and len(bottom) > 0:
        lines = []
        for _, row in bottom.head(3).iterrows():
            lines.append(f"  - {row['industry']}: 總貢獻 {_fmt_pct(row['total_contrib'])}")
        bottom_text = "負面貢獻前三產業:\n" + "\n".join(lines)

    interaction_text = ""
    if mode == "BF3" and result.get("interaction_total") is not None:
        interaction_text = f"交互效果: {_fmt_pct(result['interaction_total'])}"

    prompt = f"""你是一位資深投資研究總監，正在為台灣理財顧問撰寫基金分析摘要。

## 重要規則
1. **禁止使用以下術語**: Brinson, attribution, allocation effect, selection effect
2. **改用以下說法**: 市場佈局（取代 allocation）、選股能力（取代 selection）、產業配置（取代 sector allocation）
3. **數字規則**: 僅使用以下提供的精確數字，不可四捨五入、調整或估計。每個百分比必須與下方數據完全一致。

## 分析數據
- 基金報酬率: {fund_ret}
- 基準指數報酬率: {bench_ret}
- 超額報酬: {excess_ret}
- 產業配置效果（市場佈局）: {alloc}
- 選股效果（選股能力）: {select}
{interaction_text}

{top_text}

{bottom_text}

## 請產出以下三種格式

### 格式一：LINE 訊息
- 100字以內的中文
- 開頭用一個合適的 emoji（📈上漲/📉下跌）
- 簡潔有力，適合手機閱讀

### 格式二：PDF 報告摘要
- 150-200字的專業中文段落
- 適合正式報告，語氣專業但不艱澀
- 必須提及產業配置與選股能力的具體數字

### 格式三：顧問筆記
- 50字以內
- 僅列出關鍵數字指標
- 格式：基金XX% 超額XX% 配置XX% 選股XX%

請用以下 JSON 格式回覆：
```json
{{
  "line_message": "...",
  "pdf_summary": "...",
  "advisor_note": "..."
}}
```"""

    return prompt
