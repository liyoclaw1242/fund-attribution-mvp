"""Pydantic schemas for goal API."""

from pydantic import BaseModel, Field


class CreateGoalRequest(BaseModel):
    """Create a new financial goal."""
    client_id: str
    goal_type: str = "retirement"
    target_amount: float = Field(gt=0)
    target_year: int = Field(ge=2026)
    monthly_contribution: float = Field(ge=0, default=0)
    risk_tolerance: str = "moderate"
    current_savings: float = Field(ge=0, default=0)


class UpdateGoalRequest(BaseModel):
    """Update an existing goal."""
    target_amount: float | None = Field(default=None, gt=0)
    target_year: int | None = Field(default=None, ge=2026)
    monthly_contribution: float | None = Field(default=None, ge=0)
    risk_tolerance: str | None = None
    current_savings: float | None = Field(default=None, ge=0)


class GoalResponse(BaseModel):
    """A single goal."""
    goal_id: str
    client_id: str
    goal_type: str
    target_amount: float
    target_year: int
    monthly_contribution: float
    risk_tolerance: str
    created_at: str
    updated_at: str


class SimulationResponse(BaseModel):
    """Monte Carlo simulation result."""
    goal_id: str
    success_probability: float
    median_outcome: float
    p10_outcome: float
    p90_outcome: float
    target_amount: float
    years_to_goal: int
    suggestions: list[str]
