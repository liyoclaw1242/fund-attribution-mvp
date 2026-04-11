"""Portfolio CRUD API endpoints."""

from fastapi import APIRouter, HTTPException

from service.schemas.portfolio import (
    CreateClientRequest,
    ClientResponse,
    CreatePortfolioRequest,
    PortfolioHolding,
    PortfolioResponse,
    UpdatePortfolioRequest,
)
from service.services import portfolio_service as svc

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=list[dict])
async def list_portfolios():
    """List all clients with their holding counts."""
    return await svc.list_portfolios()


@router.post("", response_model=PortfolioHolding, status_code=201)
async def create_holding(req: CreatePortfolioRequest):
    """Create or upsert a holding for a client."""
    client = await svc.get_client(req.client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client {req.client_id} not found")

    holding = await svc.create_holding(
        client_id=req.client_id,
        fund_code=req.fund_code,
        bank_name=req.bank_name,
        shares=req.shares,
        cost_basis=req.cost_basis,
    )
    return holding


@router.get("/{client_id}", response_model=PortfolioResponse)
async def get_portfolio(client_id: str):
    """Get a client's full portfolio with cross-bank aggregation."""
    client = await svc.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client {client_id} not found")

    holdings = await svc.get_portfolio(client_id)
    return PortfolioResponse(
        client_id=client_id,
        holdings=holdings,
        total_holdings=len(holdings),
    )


@router.put("/{client_id}/{fund_code}", response_model=PortfolioHolding)
async def update_holding(
    client_id: str, fund_code: str, req: UpdatePortfolioRequest
):
    """Update a holding's shares or cost basis."""
    bank_name = req.bank_name if req.bank_name is not None else ""
    result = await svc.update_holding(
        client_id=client_id,
        fund_code=fund_code,
        bank_name=bank_name,
        shares=req.shares,
        cost_basis=req.cost_basis,
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Holding not found: {client_id}/{fund_code}/{bank_name}",
        )
    return result


@router.delete("/{client_id}/{fund_code}", status_code=204)
async def delete_holding(client_id: str, fund_code: str, bank_name: str = ""):
    """Remove a holding."""
    deleted = await svc.delete_holding(client_id, fund_code, bank_name)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Holding not found: {client_id}/{fund_code}/{bank_name}",
        )
