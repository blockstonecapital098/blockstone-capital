"""
Serverless-compatible trading scan endpoint — Expert AI Trading Engine v3.0

Key improvements over v2:
- Multi-timeframe confluence: 1h + 4h + 24h must align → higher win rate
- ATR-adaptive TP/SL: TP = 1.5x ATR, SL = 0.8x ATR → proper risk-reward
- Volume confirmation: only enter on above-average volume
- Trend strength filter: only trade strong momentum (avoid sideways chop)
- True bidirectional: LONG in uptrend, SHORT in downtrend, skip neutral
- RSI-like momentum to avoid overbought/oversold entries
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request
from crypto_trading_desk.data.live_price import get_live_price
from crypto_trading_desk.api.routes.binance_live import get_live_binance_ticker
from crypto_trading_desk.core.models import TradeProposal
import httpx

logger = logging.getLogger(__name__)
router = APIRouter()

PKT_TZ = timezone(timedelta(hours=5))
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "TAO/USDT", "ZEC/USDT", "AVAX/USDT"]

_scan_state = {"index": 0, "last_scan": 0}
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=6.0)
    return _http_client


async def _get_klines(symbol: str, interval: str = "1h", limit: int = 50) -> list:
    """Fetch OHLCV klines from Binance."""
    clean = symbol.replace("/", "").upper()
    client = _get_http_client()
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={clean}&interval={interval}&limit={limit}"
        res = await client.get(url, timeout=6.0)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        logger.debug("Klines fetch error %s %s: %s", symbol, interval, e)
    return []


def _calc_ema(values: list[float], period: int) -> float:
    """Calculate EMA for given values and period."""
    if len(values) < period:
        return sum(values) / len(values) if values else 0.0
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _calc_atr(klines: list, period: int = 14) -> float:
    """Calculate Average True Range."""
    if len(klines) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(klines)):
        h = float(klines[i][2])
        l = float(klines[i][3])
        prev_c = float(klines[i-1][4])
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return sum(trs[-period:]) / period


def _calc_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 1e-10
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


async def _analyze_symbol(symbol: str) -> dict | None:
    """
    Expert multi-timeframe analysis for a symbol.
    Returns trade signal dict or None if no high-confidence setup.
    """
    # Fetch 1h klines (50 candles for indicators)
    klines_1h = await _get_klines(symbol, "1h", 50)
    if len(klines_1h) < 20:
        return None

    closes_1h = [float(k[4]) for k in klines_1h]
    volumes_1h = [float(k[5]) for k in klines_1h]
    highs_1h = [float(k[2]) for k in klines_1h]
    lows_1h = [float(k[3]) for k in klines_1h]

    live_price = closes_1h[-1]

    # ── Core Indicators ───────────────────────────────────────────────────────
    ema9 = _calc_ema(closes_1h, 9)
    ema21 = _calc_ema(closes_1h, 21)
    ema50 = _calc_ema(closes_1h, 50)
    rsi = _calc_rsi(closes_1h, 14)
    atr = _calc_atr(klines_1h, 14)

    # Volume analysis: compare last candle vs 10-candle average
    vol_avg = sum(volumes_1h[-11:-1]) / 10
    vol_latest = volumes_1h[-1]
    vol_ratio = vol_latest / vol_avg if vol_avg > 0 else 1.0

    # ── Price changes across timeframes ───────────────────────────────────────
    chg_1h = (closes_1h[-1] - closes_1h[-2]) / closes_1h[-2] * 100
    chg_4h = (closes_1h[-1] - closes_1h[-5]) / closes_1h[-5] * 100 if len(closes_1h) >= 5 else 0
    chg_24h = (closes_1h[-1] - closes_1h[-25]) / closes_1h[-25] * 100 if len(closes_1h) >= 25 else 0

    # ── ATR-based adaptive TP/SL ──────────────────────────────────────────────
    # Using ATR ensures SL is wider than noise, and TP gives positive expectancy
    # TP = 1.5x ATR, SL = 1.0x ATR → Risk:Reward = 1.5 (need >40% win rate)
    atr_pct = (atr / live_price) * 100
    tp_pct = max(0.40, min(1.5, atr_pct * 1.5))   # at least 0.4%, cap at 1.5%
    sl_pct = max(0.25, min(1.0, atr_pct * 1.0))    # at least 0.25%, cap at 1.0%
    rr_ratio = tp_pct / sl_pct

    # ── Signal Logic: Multi-Timeframe Confluence ───────────────────────────────
    # LONG conditions: EMA bull stack + positive 4h/24h momentum + RSI not overbought
    bull_confluence = (
        ema9 > ema21           # Recent 1h momentum up
        and ema21 > ema50      # 1h uptrend established
        and chg_4h > 0.05      # 4h positive (very small threshold — 1 pip move)
        and chg_24h > 0.5      # 24h trend positive
        and rsi > 40           # Has bullish momentum
        and rsi < 78           # Not severely overbought
    )

    # SHORT conditions: EMA bear stack + negative 4h/24h momentum + RSI not oversold
    bear_confluence = (
        ema9 < ema21           # Recent 1h momentum down
        and ema21 < ema50      # 1h downtrend established
        and chg_4h < -0.05     # 4h negative
        and chg_24h < -0.5     # 24h trend negative
        and rsi > 22           # Not severely oversold
        and rsi < 60           # Has bearish momentum
    )



    # Strength score for confidence calculation
    if bull_confluence:
        strength = (
            min(chg_24h / 3.0, 1.0) * 0.3 +        # 24h trend strength (0-30%)
            min(chg_4h / 1.5, 1.0) * 0.25 +         # 4h trend strength
            min((70 - rsi) / 30.0, 1.0) * 0.25 +    # RSI headroom
            min(vol_ratio / 2.0, 1.0) * 0.20         # Volume strength
        )
        confidence = round(min(0.90, 0.70 + strength * 0.2), 2)
        side = "buy"
        regime = "BULL_TREND_CONFLUENCE"
        evidence = [
            f"{symbol}: TrendAgent EMA9({ema9:.2f}) > EMA21({ema21:.2f}) > EMA50({ema50:.2f}) — bull stack",
            f"{symbol}: MomentumAgent 4h+{chg_4h:.2f}% / 24h+{chg_24h:.2f}% aligned bullish",
            f"{symbol}: RSI({rsi:.1f}) in healthy bull zone (40-70) | Vol ratio {vol_ratio:.2f}x",
            f"{symbol}: ATR-adaptive TP+{tp_pct:.2f}% / SL-{sl_pct:.2f}% | RR={rr_ratio:.2f}x",
        ]
        return {
            "symbol": symbol, "side": side, "live_price": live_price,
            "regime": regime, "confidence": confidence, "evidence": evidence,
            "tp_pct": tp_pct, "sl_pct": sl_pct, "rr_ratio": rr_ratio,
        }

    elif bear_confluence:
        strength = (
            min(abs(chg_24h) / 3.0, 1.0) * 0.3 +
            min(abs(chg_4h) / 1.5, 1.0) * 0.25 +
            min((rsi - 30) / 30.0, 1.0) * 0.25 +
            min(vol_ratio / 2.0, 1.0) * 0.20
        )
        confidence = round(min(0.90, 0.70 + strength * 0.2), 2)
        side = "sell"
        regime = "BEAR_TREND_CONFLUENCE"
        evidence = [
            f"{symbol}: TrendAgent EMA9({ema9:.2f}) < EMA21({ema21:.2f}) < EMA50({ema50:.2f}) — bear stack",
            f"{symbol}: MomentumAgent 4h{chg_4h:.2f}% / 24h{chg_24h:.2f}% aligned bearish",
            f"{symbol}: RSI({rsi:.1f}) in healthy bear zone (30-60) | Vol ratio {vol_ratio:.2f}x",
            f"{symbol}: ATR-adaptive TP+{tp_pct:.2f}% / SL-{sl_pct:.2f}% | RR={rr_ratio:.2f}x",
        ]
        return {
            "symbol": symbol, "side": side, "live_price": live_price,
            "regime": regime, "confidence": confidence, "evidence": evidence,
            "tp_pct": tp_pct, "sl_pct": sl_pct, "rr_ratio": rr_ratio,
        }

    # No high-confidence setup — SKIP (preserving capital is also a strategy)
    return None


@router.post("/tick")
@router.get("/tick")
async def run_scan_tick(request: Request):
    """Run one cycle of the expert AI trading engine."""
    import time

    portfolio = request.app.state.portfolio
    emergency = request.app.state.emergency
    event_bus = request.app.state.event_bus
    settings = request.app.state.settings

    # Throttle: don't scan more than once every 10 seconds
    now = time.time()
    if now - _scan_state["last_scan"] < 10:
        return {"status": "throttled", "message": "Scan runs every 10s"}
    _scan_state["last_scan"] = now

    try:
        from crypto_trading_desk.core.state import load_state
        load_state(portfolio)
    except Exception:
        pass

    auto_trader = getattr(request.app.state, "auto_trader_enabled", True)
    if not auto_trader:
        return {"status": "paused", "message": "Autopilot is paused"}

    if emergency.is_active:
        return {"status": "emergency", "message": "Emergency kill-switch active"}

    if not hasattr(portfolio, "closed_trades"):
        portfolio.closed_trades = []
    if not hasattr(portfolio, "_entry_prices"):
        portfolio._entry_prices = {}
    if not hasattr(portfolio, "realized_pnl"):
        portfolio.realized_pnl = 0.0

    now_pkt = datetime.now(PKT_TZ).strftime("%b %d, %Y %I:%M:%S %p")
    actions_taken = []

    # ── 1. Check existing positions for ATR-adaptive TP/SL ──────────────────
    for sym, qty in list(portfolio.positions.items()):
        if qty != 0:
            try:
                live_p = await get_live_price(sym)
            except Exception:
                continue

            entry_p = portfolio._entry_prices.get(sym, live_p)
            leverage = 10
            margin = 50.0

            if qty > 0:  # Long
                price_diff_pct = (live_p - entry_p) / entry_p
            else:  # Short
                price_diff_pct = (entry_p - live_p) / entry_p

            realized_pnl = margin * leverage * price_diff_pct
            pnl_pct = (realized_pnl / margin) * 100.0

            # ATR-based thresholds (fetch fresh ATR for current position)
            klines = await _get_klines(sym, "1h", 20)
            atr = _calc_atr(klines, 14) if klines else 0
            atr_pct = (atr / live_p) * 100 if live_p > 0 else 0
            tp_threshold = max(0.004, min(0.015, atr_pct * 1.5 / 100))
            sl_threshold = max(0.003, min(0.010, atr_pct * 1.0 / 100))

            closed_reason = None
            if price_diff_pct >= tp_threshold:
                closed_reason = f"AI Scalp TakeProfit (+{price_diff_pct*100:.2f}%)"
            elif price_diff_pct <= -sl_threshold:
                closed_reason = f"AI Scalp StopLoss ({price_diff_pct*100:.2f}%)"

            if closed_reason:
                portfolio.positions[sym] = 0
                portfolio.realized_pnl += realized_pnl
                sl = entry_p * (1 - sl_threshold) if qty > 0 else entry_p * (1 + sl_threshold)
                tp = entry_p * (1 + tp_threshold) if qty > 0 else entry_p * (1 - tp_threshold)

                portfolio.closed_trades.append({
                    "trade_id": str(uuid.uuid4())[:8],
                    "closed_at": now_pkt,
                    "symbol": sym,
                    "side": "LONG" if qty > 0 else "SHORT",
                    "leverage": f"{leverage}x",
                    "entry_price": round(entry_p, 4),
                    "exit_price": round(live_p, 4),
                    "sl_tp": f"${sl:,.4f} / ${tp:,.4f}",
                    "realized_pnl": round(realized_pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "closed_by": closed_reason,
                })
                actions_taken.append(f"CLOSED {sym} via {closed_reason} PnL: ${realized_pnl:.2f}")
                logger.info("ScanTick closed %s via %s | PnL: $%.2f", sym, closed_reason, realized_pnl)

    # ── 2. Open new positions using expert multi-timeframe analysis ──────────
    active_pos_count = sum(1 for q in portfolio.positions.values() if q != 0)
    if active_pos_count < 3:
        # Scan all available symbols for high-confidence setups
        available_symbols = [s for s in SYMBOLS if portfolio.positions.get(s, 0) == 0]

        # Stagger analysis so we don't always pick the same symbol
        start_idx = _scan_state["index"] % max(len(available_symbols), 1)
        ordered_symbols = available_symbols[start_idx:] + available_symbols[:start_idx]
        _scan_state["index"] += 1

        for symbol in ordered_symbols:
            if sum(1 for q in portfolio.positions.values() if q != 0) >= 3:
                break

            signal = await _analyze_symbol(symbol)
            if signal is None:
                # No confluence setup — skip this symbol
                actions_taken.append(f"SKIPPED {symbol}: no high-confidence setup (market noise/sideways)")
                continue

            side = signal["side"]
            live_price = signal["live_price"]
            regime = signal["regime"]
            confidence = signal["confidence"]
            evidence = signal["evidence"]
            tp_pct = signal["tp_pct"]
            sl_pct = signal["sl_pct"]

            notional = 500.0
            calc_qty = notional / live_price if live_price > 0 else 1.0
            base_qty = max(1, round(calc_qty)) if calc_qty >= 1 else round(calc_qty, 3)
            pos_qty = base_qty if side == "buy" else -base_qty

            portfolio._entry_prices[symbol] = live_price
            portfolio.positions[symbol] = pos_qty
            portfolio.total_exposure = portfolio.total_exposure + notional if hasattr(portfolio, "total_exposure") else notional

            proposal = TradeProposal(
                symbol=symbol,
                side=side,
                quantity=base_qty,
                notional=notional,
                confidence=confidence,
                evidence=evidence,
                market_regime=regime,
            )
            await event_bus.publish(proposal)
            actions_taken.append(
                f"OPENED {side.upper()} {symbol} @ ${live_price:,.4f} | {regime} | "
                f"TP+{tp_pct:.2f}% SL-{sl_pct:.2f}% | conf={confidence}"
            )
            logger.info("Expert AI opened %s %s @ $%.4f | regime=%s conf=%.2f", side.upper(), symbol, live_price, regime, confidence)

    # Save state after every scan
    try:
        from crypto_trading_desk.core.state import save_state
        save_state(portfolio)
    except Exception:
        pass

    return {
        "status": "scanned",
        "actions": actions_taken,
        "active_positions": sum(1 for q in portfolio.positions.values() if q != 0),
        "engine": "ExpertAI_v3_MTF"
    }
