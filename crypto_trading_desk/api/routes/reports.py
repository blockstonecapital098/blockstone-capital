"""Reports route — serves daily reports and trade post‑mortems."""
from __future__ import annotations
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
router = APIRouter()

@router.get("/daily", response_class=PlainTextResponse)
async def get_daily_report(request: Request):
    daily_report = request.app.state.daily_report
    return daily_report.generate()

@router.get("/postmortems")
async def get_postmortems(request: Request, limit: int = 20):
    pm_gen = request.app.state.postmortem_gen
    records = pm_gen.latest(limit)
    return [
        {
            "trade_id": r.trade_id,
            "symbol": r.symbol,
            "side": r.side,
            "pnl": r.pnl,
            "pnl_pct": r.pnl_pct,
            "duration_seconds": r.duration_seconds,
        }
        for r in records
    ]
