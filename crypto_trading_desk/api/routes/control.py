"""Control route — allows activating/deactivating kill-switch and toggling autonomous auto-trading."""
from __future__ import annotations
from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/kill-switch/activate")
@router.post("/kill-switch/activate/")
async def activate_kill_switch(request: Request, reason: str = "Manual activation via API"):
    emergency = request.app.state.emergency
    emergency.activate(reason)
    return {"status": "activated", "reason": reason}


@router.post("/kill-switch/deactivate")
@router.post("/kill-switch/deactivate/")
async def deactivate_kill_switch(request: Request):
    emergency = request.app.state.emergency
    emergency.deactivate()
    return {"status": "deactivated"}


@router.post("/autopilot/toggle")
@router.post("/autopilot/toggle/")
async def toggle_autopilot(request: Request):
    auto_trader = getattr(request.app.state, "auto_trader", None)
    if auto_trader:
        auto_trader.is_enabled = not auto_trader.is_enabled
        return {"status": "success", "autopilot_active": auto_trader.is_enabled}
    return {"status": "error", "message": "Auto trader not initialized"}


@router.get("/status")
@router.get("/status/")
async def get_system_status(request: Request):
    auto_trader = getattr(request.app.state, "auto_trader", None)
    emergency = request.app.state.emergency
    return {
        "emergency_active": emergency.is_active,
        "autopilot_active": auto_trader.is_enabled if auto_trader else False
    }
