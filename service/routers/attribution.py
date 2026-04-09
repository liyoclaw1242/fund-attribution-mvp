"""Attribution API endpoint."""

from fastapi import APIRouter, HTTPException

from service.schemas.attribution import AttributionRequest, AttributionResponse
from service.services.attribution_service import run_attribution

router = APIRouter(prefix="/api", tags=["attribution"])


@router.post("/attribution", response_model=AttributionResponse)
async def compute_attribution(req: AttributionRequest):
    """Run Brinson-Fachler attribution on provided holdings."""
    try:
        result = run_attribution(
            holdings_input=[h.model_dump() for h in req.holdings],
            mode=req.mode,
            benchmark=req.benchmark,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
