"""Goal CRUD + Monte Carlo simulation API endpoints."""

from fastapi import APIRouter, HTTPException

from interfaces import GoalConfig
from service.schemas.goal import (
    CreateGoalRequest,
    GoalResponse,
    SimulationResponse,
    UpdateGoalRequest,
)
from service.services import portfolio_service as svc

router = APIRouter(prefix="/api/goal", tags=["goal"])


@router.get("/{client_id}", response_model=list[GoalResponse])
async def list_goals(client_id: str):
    """List all goals for a client."""
    client = await svc.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client {client_id} not found")

    goals = await svc.list_goals(client_id)
    return goals


@router.post("", response_model=GoalResponse, status_code=201)
async def create_goal(req: CreateGoalRequest):
    """Create a new financial goal."""
    client = await svc.get_client(req.client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client {req.client_id} not found")

    goal = await svc.create_goal(
        client_id=req.client_id,
        goal_type=req.goal_type,
        target_amount=req.target_amount,
        target_year=req.target_year,
        monthly_contribution=req.monthly_contribution,
        risk_tolerance=req.risk_tolerance,
    )
    return goal


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(goal_id: str, req: UpdateGoalRequest):
    """Update goal parameters."""
    result = await svc.update_goal(
        goal_id,
        target_amount=req.target_amount,
        target_year=req.target_year,
        monthly_contribution=req.monthly_contribution,
        risk_tolerance=req.risk_tolerance,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return result


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: str):
    """Remove a goal."""
    deleted = await svc.delete_goal(goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")


@router.get("/{goal_id}/simulate", response_model=SimulationResponse)
async def simulate_goal(goal_id: str):
    """Re-run Monte Carlo simulation for a goal."""
    goal_data = await svc.get_goal(goal_id)
    if not goal_data:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")

    from engine.goal_tracker import simulate_goal as run_sim

    config = GoalConfig(
        target_amount=goal_data["target_amount"],
        target_year=goal_data["target_year"],
        monthly_contribution=goal_data["monthly_contribution"],
        risk_tolerance=goal_data["risk_tolerance"],
        goal_type=goal_data["goal_type"],
    )

    result = run_sim(config, seed=42)

    return SimulationResponse(
        goal_id=goal_id,
        success_probability=result.success_probability,
        median_outcome=result.median_outcome,
        p10_outcome=result.p10_outcome,
        p90_outcome=result.p90_outcome,
        target_amount=result.target_amount,
        years_to_goal=result.years_to_goal,
        suggestions=result.suggestions,
    )
