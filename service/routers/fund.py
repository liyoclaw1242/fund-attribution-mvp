"""Fund lookup and search API endpoints."""

from fastapi import APIRouter, HTTPException, Query

from service.schemas.fund import FundResponse, SearchResponse
from service.services import fund_service as svc

router = APIRouter(prefix="/api/fund", tags=["fund"])


@router.get("/search", response_model=SearchResponse)
async def search_funds(q: str = Query(min_length=1)):
    """Search funds by name or code."""
    results = await svc.search_funds(q)
    return SearchResponse(query=q, results=results, total=len(results))


@router.get("/{identifier}", response_model=FundResponse)
async def get_fund(identifier: str):
    """Look up a fund by identifier (code, ISIN, or ticker)."""
    fund = await svc.get_fund_by_identifier(identifier)
    if not fund:
        raise HTTPException(status_code=404, detail=f"Fund not found: {identifier}")
    return fund
