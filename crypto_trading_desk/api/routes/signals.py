"""Signals route — returns agent performance stats."""
from __future__ import annotations
from fastapi import APIRouter, Request
router = APIRouter()

@router.get("/")
async def get_signals(request: Request):
    tracker = request.app.state.perf_tracker
    return tracker.summary()
