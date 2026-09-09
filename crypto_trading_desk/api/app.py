"""
FastAPI application entry point.

Creates all shared services, wires them together, and mounts routers.
Startup and shutdown hooks manage async resources (DB, market data, exchange).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from crypto_trading_desk.config.settings import Settings
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.risk.risk_manager import HardRiskManager
from crypto_trading_desk.risk.position_sizer import PositionSizer
from crypto_trading_desk.risk.portfolio_monitor import PortfolioMonitor
from crypto_trading_desk.risk.emergency import EmergencyManager
from crypto_trading_desk.head_trader.signal_aggregator import SignalAggregator
from crypto_trading_desk.head_trader.head_trader import HeadTrader
from crypto_trading_desk.execution.oms import OMS
from crypto_trading_desk.execution.paper_engine import PaperEngine
from crypto_trading_desk.execution.exchange_adapter import ExchangeAdapter
from crypto_trading_desk.execution.executor import Executor
from crypto_trading_desk.analytics.agent_tracker import AgentPerformanceTracker
from crypto_trading_desk.analytics.trade_postmortem import TradePostMortemGenerator
from crypto_trading_desk.analytics.daily_report import DailyReportGenerator
from crypto_trading_desk.alerts.alert_manager import AlertManager
from crypto_trading_desk.api.routes import dashboard, trades, signals, risk, control, reports

logger = logging.getLogger(__name__)

settings = Settings()

# ── Shared service instances ──────────────────────────────────────────────────
event_bus = EventBus()
emergency = EmergencyManager()
portfolio = PortfolioMonitor(initial_equity=settings.initial_equity if hasattr(settings, "initial_equity") else 100_000.0)

from crypto_trading_desk.config.risk_limits import RISK_LIMITS
risk_manager = HardRiskManager(RISK_LIMITS)
sizer = PositionSizer(RISK_LIMITS)
aggregator = SignalAggregator(event_bus)
head_trader = HeadTrader(event_bus, risk_manager, sizer, portfolio, emergency)
oms = OMS(event_bus)
exchange_adapter = ExchangeAdapter(settings)
paper_engine = PaperEngine(event_bus, portfolio)
executor = Executor(event_bus, settings, exchange_adapter)
perf_tracker = AgentPerformanceTracker()
postmortem_gen = TradePostMortemGenerator()
daily_report = DailyReportGenerator(perf_tracker, postmortem_gen)
alert_manager = AlertManager(channels=[settings.alert_channel if hasattr(settings, "alert_channel") else "console"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle manager."""
    logger.info("Trading Desk API starting up …")
    # Attach shared objects to app state for routers
    app.state.event_bus = event_bus
    app.state.portfolio = portfolio
    app.state.emergency = emergency
    app.state.oms = oms
    app.state.perf_tracker = perf_tracker
    app.state.postmortem_gen = postmortem_gen
    app.state.daily_report = daily_report
    app.state.alert_manager = alert_manager
    app.state.settings = settings

    from crypto_trading_desk.core.state import load_state, save_state
    load_state(portfolio)

    auto_trader = None
    if not os.environ.get("VERCEL"):
        from crypto_trading_desk.execution.auto_trader import AutonomousTradingEngine
        auto_trader = AutonomousTradingEngine(app.state)
        auto_trader.start()
        app.state.auto_trader = auto_trader

    yield  # Application runs here

    if auto_trader:
        auto_trader.stop()
    save_state(portfolio)
    logger.info("Trading Desk API shutting down …")
    await exchange_adapter.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Blockstone Capital AI Trading Desk",
        version="1.0.0",
        description="Institutional-grade crypto trading desk powered by multiple AI agents.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Mount routers
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
    app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
    app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
    app.include_router(risk.router, prefix="/api/risk", tags=["risk"])
    app.include_router(control.router, prefix="/api/control", tags=["control"])
    app.include_router(reports.router, prefix="/api/reports", tags=["reports"])

    from crypto_trading_desk.api.routes import binance_live
    app.include_router(binance_live.router, prefix="/api/binance", tags=["binance"])

    from fastapi.responses import HTMLResponse
    from crypto_trading_desk.api.templates.template import DASHBOARD_HTML

    @app.get("/", response_class=HTMLResponse)
    @app.get("/dashboard", response_class=HTMLResponse)
    async def get_ui_dashboard():
        return HTMLResponse(content=DASHBOARD_HTML)

    @app.get("/health")
    async def health():
        return {"status": "ok", "trading_mode": settings.trading_mode}

    return app


app = create_app()
