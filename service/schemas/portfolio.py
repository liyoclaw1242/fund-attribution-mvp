"""Pydantic schemas for portfolio API."""

from pydantic import BaseModel, Field


class CreatePortfolioRequest(BaseModel):
    """Create a new client holding."""
    client_id: str
    fund_code: str
    bank_name: str = ""
    shares: float = Field(ge=0)
    cost_basis: float = Field(ge=0)


class UpdatePortfolioRequest(BaseModel):
    """Update an existing holding."""
    shares: float | None = Field(default=None, ge=0)
    cost_basis: float | None = Field(default=None, ge=0)
    bank_name: str | None = None


class PortfolioHolding(BaseModel):
    """A single holding in a client's portfolio."""
    client_id: str
    fund_code: str
    bank_name: str
    shares: float
    cost_basis: float
    added_at: str


class PortfolioResponse(BaseModel):
    """Full portfolio for a client."""
    client_id: str
    holdings: list[PortfolioHolding]
    total_holdings: int


class CreateClientRequest(BaseModel):
    """Create a new client."""
    client_id: str
    name: str
    kyc_risk_level: str = "moderate"


class ClientResponse(BaseModel):
    """Client info."""
    client_id: str
    name: str
    kyc_risk_level: str
    created_at: str
