"""Pydantic schemas for attribution API."""

from pydantic import BaseModel, Field


class HoldingInput(BaseModel):
    """A fund holding in the attribution request."""
    identifier: str
    shares: float = Field(default=1, ge=0)


class AttributionRequest(BaseModel):
    """Request body for Brinson attribution."""
    holdings: list[HoldingInput] = Field(min_length=1)
    benchmark: str = "auto"
    mode: str = Field(default="BF2", pattern="^(BF2|BF3)$")
    base_currency: str = "TWD"
    generate_ai: bool = False


class IndustryDetail(BaseModel):
    """Attribution detail for a single industry."""
    industry: str
    Wp: float
    Wb: float
    Rp: float
    Rb: float
    alloc_effect: float
    select_effect: float
    interaction_effect: float | None = None
    total_contrib: float


class AttributionResponse(BaseModel):
    """Brinson attribution result."""
    fund_return: float
    bench_return: float
    excess_return: float
    allocation_total: float
    selection_total: float
    interaction_total: float | None = None
    brinson_mode: str
    detail: list[IndustryDetail]
    top_contributors: list[IndustryDetail]
    bottom_contributors: list[IndustryDetail]
    unmapped_weight: float = 0.0
    chart_base64: str | None = None
    ai_summary: str | None = None
