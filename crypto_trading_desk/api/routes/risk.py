"""Risk route — returns current risk status and emergency state."""
from __future__ import annotations
from fastapi import APIRouter, Request
router = APIRouter()

@router.get("/")
async def get_risk(request: Request):
    portfolio = request.app.state.portfolio
    emergency = request.app.state.emergency
    return {
        "emergency_active": emergency.is_active,
        "equity": portfolio.equity,
        "drawdown": portfolio.drawdown,
        "total_exposure": portfolio.total_exposure,
    }
