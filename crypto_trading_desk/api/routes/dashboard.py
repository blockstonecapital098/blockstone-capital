"""
Dashboard route — returns static $1,000 Base Capital and dynamic Live Market Value Portfolio.
"""
from __future__ import annotations
from fastapi import APIRouter, Request
from crypto_trading_desk.data.live_price import get_live_price

router = APIRouter()


@router.get("/")
@router.get("")
async def get_dashboard(request: Request):
    portfolio = request.app.state.portfolio
    initial_capital = 1000.00 # Always static $1,000.00 starting equity

    if not hasattr(portfolio, "realized_pnl"):
        portfolio.realized_pnl = 0.0

    positions_list = []
    total_exposure = 0.0
    total_unrealized_pnl = 0.0

    for sym, pos_data in portfolio.positions.items():
        qty = pos_data if isinstance(pos_data, (int, float)) else pos_data.get("qty", 0)
        if qty != 0:
            live_price = await get_live_price(sym)
            entry_price = getattr(portfolio, "_entry_prices", {}).get(sym, live_price)

            leverage = 10 # 10x leverage
            margin = 50.0 # $50 USDT margin
            notional = margin * leverage # $500 position size
            total_exposure += notional

            if qty > 0: # Long
                liq_price = entry_price * (1.0 - (1.0 / leverage))
                price_diff_pct = (live_price - entry_price) / entry_price
                unrealized_pnl = margin * leverage * price_diff_pct
            else: # Short
                liq_price = entry_price * (1.0 + (1.0 / leverage))
                price_diff_pct = (entry_price - live_price) / entry_price
                unrealized_pnl = margin * leverage * price_diff_pct

            pnl_pct = (unrealized_pnl / margin) * 100.0
            distance_to_liq_pct = abs((live_price - liq_price) / live_price) * 100.0
            total_unrealized_pnl += unrealized_pnl

            positions_list.append({
                "symbol": sym,
                "quantity": qty,
                "side": "LONG" if qty > 0 else "SHORT",
                "leverage": f"{leverage}x",
                "margin_used": f"${margin:.2f} USDT (5%)",
                "entry_price": round(entry_price, 2),
                "current_price": round(live_price, 2),
                "liq_price": round(liq_price, 2),
                "distance_to_liq": f"{distance_to_liq_pct:.1f}%",
                "stop_loss": round(entry_price * 0.98 if qty > 0 else entry_price * 1.02, 2),
                "take_profit": round(entry_price * 1.04 if qty > 0 else entry_price * 0.96, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pnl_pct": round(pnl_pct, 2)
            })

    # Total Portfolio Net PnL = Realized PnL + Unrealized Live PnL
    total_net_pnl = portfolio.realized_pnl + total_unrealized_pnl
    live_market_value_portfolio = initial_capital + total_net_pnl
    total_pnl_pct = (total_net_pnl / initial_capital) * 100.0
    drawdown_pct = (portfolio.drawdown / initial_capital) * 100.0 if portfolio.drawdown else 0.0

    return {
        "base_capital": initial_capital, # Always $1,000.00
        "live_market_value_portfolio": round(live_market_value_portfolio, 2),
        "total_net_pnl": round(total_net_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "total_exposure": round(total_exposure, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "positions_count": len(positions_list),
        "positions": positions_list,
    }
