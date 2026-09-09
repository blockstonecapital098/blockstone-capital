"""
Trades route — handles order execution, PKT timestamps, realized P&L tracking, and full history reset.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request

from crypto_trading_desk.core.models import TradeProposal
from crypto_trading_desk.data.live_price import get_live_price
from crypto_trading_desk.core.state import save_state

router = APIRouter()

PKT_TZ = timezone(timedelta(hours=5))


@router.get("/")
@router.get("")
async def get_trades(request: Request):
    oms = request.app.state.oms
    orders = oms.all_orders()
    formatted_orders = []

    for o in reversed(orders):
        created_at_dt = getattr(o, "created_at", None)
        if created_at_dt:
            if created_at_dt.tzinfo is None:
                created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)
            pkt_dt = created_at_dt.astimezone(PKT_TZ)
            time_str = pkt_dt.strftime("%b %d, %Y %I:%M:%S %p")
        else:
            time_str = datetime.now(PKT_TZ).strftime("%b %d, %Y %I:%M:%S %p")

        formatted_orders.append({
            "order_id": o.order_id[:8],
            "symbol": o.symbol,
            "side": o.side.upper(),
            "quantity": o.quantity,
            "notional": round(o.notional, 2),
            "status": o.status.upper(),
            "avg_fill_price": round(o.avg_fill_price, 2),
            "created_at": time_str,
        })

    return formatted_orders


@router.get("/closed")
@router.get("/closed/")
async def get_closed_trades(request: Request):
    portfolio = request.app.state.portfolio
    closed_trades = getattr(portfolio, "closed_trades", [])
    return list(reversed(closed_trades))


@router.post("/simulate")
@router.post("/simulate/")
async def trigger_simulated_trade(request: Request, symbol: str = "BTC/USDT", side: str = "buy"):
    event_bus = request.app.state.event_bus
    portfolio = request.app.state.portfolio

    live_price = await get_live_price(symbol)
    qty = 1 if "BTC" in symbol else 5
    notional = 500.0 # $50 margin x 10x leverage = $500 position size

    if not hasattr(portfolio, "_entry_prices"):
        portfolio._entry_prices = {}
    portfolio._entry_prices[symbol] = live_price

    proposal = TradeProposal(
        symbol=symbol,
        side=side.lower(),
        quantity=qty,
        notional=notional,
        confidence=0.89,
        evidence=[
            f"{symbol}: TrendAgent 4h EMA breakout at ${live_price:,.2f} (10x Leverage)",
            f"{symbol}: HardRiskManager approved 5% portfolio margin allocation ($50 USDT)"
        ],
        market_regime="BULL_TREND"
    )

    current_qty = portfolio.positions.get(symbol, 0)
    portfolio.positions[symbol] = (current_qty + qty) if side == "buy" else (current_qty - qty)
    portfolio.total_exposure += notional

    await event_bus.publish(proposal)
    save_state(portfolio)

    return {
        "status": "success",
        "message": f"Head Trader executed {side.upper()} {symbol} (10x Leverage) @ ${live_price:,.2f}",
        "live_price": live_price,
        "proposal_id": proposal.proposal_id[:8]
    }


@router.post("/close")
@router.post("/close/")
@router.post("/close/{symbol:path}")
async def close_single_position(request: Request, symbol: str | None = None, reason: str = "Manual Close"):
    from urllib.parse import unquote
    portfolio = request.app.state.portfolio

    # Extract symbol from query parameter if empty or path is root
    if not symbol or symbol in ("", "/"):
        symbol = request.query_params.get("symbol", "")
    symbol = unquote(symbol).strip()

    # Normalize symbol format (e.g. BTCUSDT -> BTC/USDT)
    if "/" not in symbol and symbol.endswith("USDT"):
        symbol = f"{symbol[:-4]}/USDT"

    if not hasattr(portfolio, "closed_trades"):
        portfolio.closed_trades = []
    if not hasattr(portfolio, "realized_pnl"):
        portfolio.realized_pnl = 0.0

    now_pkt = datetime.now(PKT_TZ).strftime("%b %d, %Y %I:%M:%S %p")
    qty = portfolio.positions.get(symbol, 0)
    if qty != 0:
        live_price = await get_live_price(symbol)
        entry_price = getattr(portfolio, "_entry_prices", {}).get(symbol, live_price)
        leverage = 10
        margin = 50.0

        if qty > 0:  # Long
            price_diff_pct = (live_price - entry_price) / entry_price
            realized_pnl = margin * leverage * price_diff_pct
            sl = entry_price * 0.98
            tp = entry_price * 1.04
        else:  # Short
            price_diff_pct = (entry_price - live_price) / entry_price
            realized_pnl = margin * leverage * price_diff_pct
            sl = entry_price * 1.02
            tp = entry_price * 0.96

        pnl_pct = (realized_pnl / margin) * 100.0
        portfolio.realized_pnl += realized_pnl

        portfolio.closed_trades.append({
            "trade_id": str(uuid.uuid4())[:8],
            "closed_at": now_pkt,
            "symbol": symbol,
            "side": "LONG" if qty > 0 else "SHORT",
            "leverage": f"{leverage}x",
            "entry_price": round(entry_price, 2),
            "exit_price": round(live_price, 2),
            "sl_tp": f"${sl:,.2f} / ${tp:,.2f}",
            "realized_pnl": round(realized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "closed_by": reason,
        })

        portfolio.positions[symbol] = 0
        portfolio.total_exposure = max(0.0, portfolio.total_exposure - 500.0)
        save_state(portfolio)
        return {"status": "success", "message": f"Closed {symbol} position. Realized P&L: ${realized_pnl:.2f}"}

    return {"status": "warning", "message": f"No open position found for {symbol}."}


@router.post("/close-all")
@router.post("/close-all/")
async def close_all_positions(request: Request, reason: str = "Manual Close"):
    portfolio = request.app.state.portfolio

    if not hasattr(portfolio, "closed_trades"):
        portfolio.closed_trades = []
    if not hasattr(portfolio, "realized_pnl"):
        portfolio.realized_pnl = 0.0

    now_pkt = datetime.now(PKT_TZ).strftime("%b %d, %Y %I:%M:%S %p")
    closed_count = 0

    for sym, qty in list(portfolio.positions.items()):
        if qty != 0:
            live_price = await get_live_price(sym)
            entry_price = getattr(portfolio, "_entry_prices", {}).get(sym, live_price)
            leverage = 10
            margin = 50.0

            if qty > 0: # Long
                price_diff_pct = (live_price - entry_price) / entry_price
                realized_pnl = margin * leverage * price_diff_pct
                sl = entry_price * 0.98
                tp = entry_price * 1.04
            else: # Short
                price_diff_pct = (entry_price - live_price) / entry_price
                realized_pnl = margin * leverage * price_diff_pct
                sl = entry_price * 1.02
                tp = entry_price * 0.96

            pnl_pct = (realized_pnl / margin) * 100.0
            portfolio.realized_pnl += realized_pnl

            portfolio.closed_trades.append({
                "trade_id": str(uuid.uuid4())[:8],
                "closed_at": now_pkt,
                "symbol": sym,
                "side": "LONG" if qty > 0 else "SHORT",
                "leverage": f"{leverage}x",
                "entry_price": round(entry_price, 2),
                "exit_price": round(live_price, 2),
                "sl_tp": f"${sl:,.2f} / ${tp:,.2f}",
                "realized_pnl": round(realized_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "closed_by": reason
            })
            closed_count += 1

    portfolio.positions.clear()
    portfolio.total_exposure = 0.0
    if hasattr(portfolio, "_entry_prices"):
        portfolio._entry_prices.clear()

    save_state(portfolio)
    return {"status": "success", "message": f"Closed {closed_count} open position(s). Realized P&L updated."}


@router.post("/reset-all")
@router.post("/reset-all/")
async def reset_all_history(request: Request):
    """Wipes all old positions, orders, realized P&L, and closed trades history."""
    portfolio = request.app.state.portfolio
    oms = request.app.state.oms

    portfolio.equity = 1000.0
    portfolio.realized_pnl = 0.0
    portfolio.positions.clear()
    portfolio.total_exposure = 0.0
    portfolio.drawdown = 0.0
    portfolio.high_watermark = 1000.0
    if hasattr(portfolio, "_entry_prices"):
        portfolio._entry_prices.clear()
    portfolio.closed_trades = []

    if hasattr(oms, "_orders"):
        oms._orders.clear()

    save_state(portfolio)
    return {"status": "success", "message": "All previous trades & history cleared. Reset to $1,000.00 USDT."}
