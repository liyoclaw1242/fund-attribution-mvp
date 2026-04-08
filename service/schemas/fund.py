"""Pydantic schemas for fund API."""

from pydantic import BaseModel, Field


class FundHolding(BaseModel):
    """A single holding within a fund."""
    stock_name: str
    weight: float
    sector: str = ""


class FundResponse(BaseModel):
    """Fund details with latest holdings."""
    fund_id: str
    fund_name: str
    fund_type: str = ""
    market: str = ""
    source: str = ""
    holdings: list[FundHolding] = []
    as_of_date: str = ""


class FundSearchResult(BaseModel):
    """A single search result."""
    fund_id: str
    fund_name: str
    fund_type: str = ""
    market: str = ""
    source: str = ""


class SearchResponse(BaseModel):
    """Fund search results."""
    query: str
    results: list[FundSearchResult]
    total: int
