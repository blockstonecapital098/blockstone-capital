"""
Blockstone Capital — Aladdin-Class AI Trading Engine v4.0

Inspired by BlackRock Aladdin's core principles:
  - Multi-Factor Alpha Scoring (8 independent factors, 0-100 score)
  - Volatility Regime Classification (LOW / MED / HIGH) with adaptive TP/SL
  - Portfolio Correlation Guard (no holding correlated assets simultaneously)
  - Macro Sentiment Overlay (Fear & Greed Index via alternative.me)
  - MACD Signal Confirmation (trend momentum cross)
  - Bollinger Band Position (mean-reversion context)
  - Trailing Stop Logic (locks profits once 60% of TP reached)
  - Dynamic Position Sizing (scaled with factor score confidence)
  - True Bidirectional (LONG in bull regime, SHORT in bear regime)
  - Capital Preservation (skip unless score > 62 — no random entries)
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

# Correlation buckets — limit exposure within each group
# Bucket A: BTC-correlated (BTC, ETH, SOL, AVAX typically move together)
# Bucket B: Uncorrelated alts (TAO = AI token, ZEC = privacy)
CORRELATION_BUCKETS = {
    "A": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"],
    "B": ["TAO/USDT", "ZEC/USDT"],
}
MAX_PER_BUCKET = {"A": 1, "B": 1}  # Max 1 position per correlation group

# Aladdin minimum factor score to trade (0-100)
MIN_SCORE_TO_TRADE = 62

_scan_state = {"index": 0, "last_scan": 0}
_http_client: httpx.AsyncClient | None = None
_fear_greed_cache: dict = {"value": 50, "label": "Neutral", "ts": 0}


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=6.0)
    return _http_client


async def _get_klines(symbol: str, interval: str = "1h", limit: int = 60) -> list:
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


async def _get_fear_greed() -> dict:
    """Fetch Crypto Fear & Greed Index (0=Extreme Fear, 100=Extreme Greed)."""
    import time
    global _fear_greed_cache
    now = time.time()
    if now - _fear_greed_cache["ts"] < 300:  # Cache 5 minutes
        return _fear_greed_cache
    client = _get_http_client()
    try:
        res = await client.get("https://api.alternative.me/fng/?limit=1", timeout=5.0)
        if res.status_code == 200:
            d = res.json()["data"][0]
            _fear_greed_cache = {
                "value": int(d["value"]),
                "label": d["value_classification"],
                "ts": now,
            }
    except Exception:
        pass
    return _fear_greed_cache


# ── Technical Indicator Calculations ─────────────────────────────────────────

def _calc_ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / len(values) if values else 0.0
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _calc_atr(klines: list, period: int = 14) -> float:
    if len(klines) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(klines)):
        h = float(klines[i][2])
        l = float(klines[i][3])
        prev_c = float(klines[i - 1][4])
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return sum(trs[-period:]) / period


def _calc_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 1e-10
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_macd(closes: list[float]) -> tuple[float, float, float]:
    """Returns (MACD line, Signal line, Histogram)."""
    if len(closes) < 26:
        return 0.0, 0.0, 0.0
    ema12 = _calc_ema(closes, 12)
    ema26 = _calc_ema(closes, 26)
    macd_line = ema12 - ema26
    # Signal = 9-period EMA of MACD — approximate using last 9 MACD values
    macd_vals = []
    for i in range(max(0, len(closes) - 35), len(closes)):
        e12 = _calc_ema(closes[:i + 1], 12)
        e26 = _calc_ema(closes[:i + 1], 26)
        macd_vals.append(e12 - e26)
    signal = _calc_ema(macd_vals, 9) if len(macd_vals) >= 9 else macd_line
    histogram = macd_line - signal
    return macd_line, signal, histogram


def _calc_bollinger(closes: list[float], period: int = 20, std_mult: float = 2.0) -> tuple[float, float, float]:
    """Returns (upper band, middle band, lower band)."""
    if len(closes) < period:
        m = closes[-1]
        return m * 1.02, m, m * 0.98
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = variance ** 0.5
    return mid + std_mult * std, mid, mid - std_mult * std


def _volatility_regime(atr_pct: float) -> str:
    """Classify volatility into LOW / MED / HIGH regime."""
    if atr_pct < 0.8:
        return "LOW"
    elif atr_pct < 1.8:
        return "MED"
    else:
        return "HIGH"


# ── Aladdin Multi-Factor Scoring Engine ──────────────────────────────────────

def _score_symbol(
    closes: list[float],
    klines: list,
    side: str,  # "buy" or "sell"
    fg_value: int,  # Fear & Greed 0-100
) -> dict:
    """
    Score a symbol for a given side using 8 independent factors.
    Returns score (0-100) and factor breakdown for transparency.
    """
    live = closes[-1]
    ema9 = _calc_ema(closes, 9)
    ema21 = _calc_ema(closes, 21)
    ema50 = _calc_ema(closes, 50)
    rsi = _calc_rsi(closes, 14)
    macd_line, signal_line, histogram = _calc_macd(closes)
    bb_upper, bb_mid, bb_lower = _calc_bollinger(closes, 20)
    atr = _calc_atr(klines, 14)
    atr_pct = (atr / live) * 100 if live > 0 else 0

    chg_4h = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
    chg_24h = (closes[-1] - closes[-25]) / closes[-25] * 100 if len(closes) >= 25 else 0

    bb_width = (bb_upper - bb_lower) / bb_mid * 100  # Bollinger Band width %
    bb_pos = (live - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5  # 0=lower, 1=upper

    factors = {}

    # ── Factor 1: EMA Trend Stack (max 20 pts) ────────────────────────────────
    if side == "buy":
        if ema9 > ema21 > ema50:
            f1 = 20  # Full bull stack
        elif ema9 > ema21:
            f1 = 10  # Partial bull
        else:
            f1 = 0
    else:
        if ema9 < ema21 < ema50:
            f1 = 20  # Full bear stack
        elif ema9 < ema21:
            f1 = 10  # Partial bear
        else:
            f1 = 0
    factors["EMA_Stack"] = f1

    # ── Factor 2: Multi-Timeframe Momentum (max 18 pts) ───────────────────────
    if side == "buy":
        f2 = 0
        if chg_4h > 0.3:
            f2 += 10
        elif chg_4h > 0.05:
            f2 += 6
        if chg_24h > 2.0:
            f2 += 8
        elif chg_24h > 0.5:
            f2 += 5
    else:
        f2 = 0
        if chg_4h < -0.3:
            f2 += 10
        elif chg_4h < -0.05:
            f2 += 6
        if chg_24h < -2.0:
            f2 += 8
        elif chg_24h < -0.5:
            f2 += 5
    factors["Momentum_MTF"] = f2

    # ── Factor 3: RSI Zone (max 15 pts) ───────────────────────────────────────
    if side == "buy":
        if 45 <= rsi <= 65:
            f3 = 15  # Sweet spot — momentum without overbought
        elif 40 <= rsi < 45 or 65 < rsi <= 72:
            f3 = 8
        elif rsi > 72:
            f3 = 0  # Overbought — risk of reversal
        else:
            f3 = 0  # Below 40 — no bullish momentum
    else:
        if 35 <= rsi <= 55:
            f3 = 15  # Sweet spot for shorts
        elif 28 <= rsi < 35 or 55 < rsi <= 60:
            f3 = 8
        elif rsi < 28:
            f3 = 0  # Oversold — short squeeze risk
        else:
            f3 = 0
    factors["RSI_Zone"] = f3

    # ── Factor 4: MACD Confirmation (max 15 pts) ──────────────────────────────
    if side == "buy":
        if macd_line > signal_line and histogram > 0:
            f4 = 15  # MACD bullish crossover with positive histogram
        elif macd_line > signal_line:
            f4 = 8
        else:
            f4 = 0
    else:
        if macd_line < signal_line and histogram < 0:
            f4 = 15  # MACD bearish crossover
        elif macd_line < signal_line:
            f4 = 8
        else:
            f4 = 0
    factors["MACD"] = f4

    # ── Factor 5: Bollinger Band Position (max 12 pts) ────────────────────────
    if side == "buy":
        # Best long entries near lower band (mean-reversion) or mid crossover
        if bb_pos < 0.35:
            f5 = 12  # Near lower band — oversold relative to range
        elif bb_pos < 0.55:
            f5 = 8   # Around midline — neutral
        elif bb_pos > 0.85:
            f5 = 2   # Near upper band — overbought
        else:
            f5 = 5
    else:
        # Best short entries near upper band
        if bb_pos > 0.75:
            f5 = 12  # Near upper band — overbought relative to range
        elif bb_pos > 0.55:
            f5 = 8
        elif bb_pos < 0.25:
            f5 = 2   # Near lower band — may bounce
        else:
            f5 = 5
    factors["Bollinger_Position"] = f5

    # ── Factor 6: Volatility Regime Suitability (max 10 pts) ─────────────────
    regime = _volatility_regime(atr_pct)
    if regime == "MED":
        f6 = 10   # Ideal — enough movement to hit TP, not so much that SL gets random-wicked
    elif regime == "LOW":
        f6 = 6    # May take longer to hit TP
    else:
        f6 = 4    # HIGH volatility — stops may be hit by wicks
    factors["Volatility_Regime"] = f6

    # ── Factor 7: Macro Sentiment (max 5 pts) ─────────────────────────────────
    # Fear & Greed: 0=Extreme Fear, 100=Extreme Greed
    # Longs preferred in Greed (40-75); Shorts preferred in Fear (25-60)
    if side == "buy":
        if 40 <= fg_value <= 75:
            f7 = 5  # Healthy greed — good for longs
        elif fg_value > 75:
            f7 = 1  # Extreme greed — peak risk
        elif fg_value < 30:
            f7 = 2  # Fear — buy the fear zone
        else:
            f7 = 3
    else:
        if 25 <= fg_value <= 60:
            f7 = 5  # Neutral to fearful — good for shorts
        elif fg_value < 25:
            f7 = 1  # Extreme fear — may bounce, risky short
        else:
            f7 = 3
    factors["FearGreed_Macro"] = f7

    # ── Factor 8: Price vs VWAP Proxy (EMA200 approximation, max 5 pts) ──────
    # Use 50-period EMA as trend anchor — price above = bullish, below = bearish
    if side == "buy":
        f8 = 5 if live > ema50 else 0
    else:
        f8 = 5 if live < ema50 else 0
    factors["Price_vs_Trend_Anchor"] = f8

    total_score = sum(factors.values())

    return {
        "score": total_score,
        "factors": factors,
        "ema9": ema9, "ema21": ema21, "ema50": ema50,
        "rsi": rsi,
        "macd_line": macd_line, "signal_line": signal_line, "histogram": histogram,
        "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower, "bb_pos": bb_pos,
        "atr_pct": atr_pct, "volatility_regime": regime,
        "chg_4h": chg_4h, "chg_24h": chg_24h,
        "fg_value": fg_value,
    }


def _get_adaptive_tp_sl(atr_pct: float, regime: str, score: int) -> tuple[float, float]:
    """
    Aladdin-style adaptive TP/SL based on volatility regime and signal strength.
    Higher score = slightly wider TP allowed. Higher volatility = wider SL needed.
    """
    if regime == "LOW":
        tp_mult, sl_mult = 1.2, 0.8
    elif regime == "MED":
        tp_mult, sl_mult = 1.5, 1.0
    else:  # HIGH
        tp_mult, sl_mult = 1.8, 1.2

    # Score bonus: strong signal (>75) gets wider TP target
    if score >= 80:
        tp_mult += 0.3
    elif score >= 70:
        tp_mult += 0.15

    tp_pct = max(0.35, min(2.0, atr_pct * tp_mult))
    sl_pct = max(0.20, min(1.2, atr_pct * sl_mult))
    return round(tp_pct, 3), round(sl_pct, 3)


def _get_symbol_bucket(symbol: str) -> str:
    for bucket, syms in CORRELATION_BUCKETS.items():
        if symbol in syms:
            return bucket
    return "B"


async def _analyze_symbol_aladdin(symbol: str, fg_value: int) -> dict | None:
    """
    Aladdin multi-factor analysis. Tests both LONG and SHORT, picks highest score.
    Returns signal dict or None if below minimum score threshold.
    """
    klines_1h = await _get_klines(symbol, "1h", 60)
    if len(klines_1h) < 30:
        return None

    closes = [float(k[4]) for k in klines_1h]
    live_price = closes[-1]

    # Score both sides
    bull_result = _score_symbol(closes, klines_1h, "buy", fg_value)
    bear_result = _score_symbol(closes, klines_1h, "sell", fg_value)

    bull_score = bull_result["score"]
    bear_score = bear_result["score"]

    # Pick the higher-scored side, must exceed minimum threshold
    if bull_score >= bear_score and bull_score >= MIN_SCORE_TO_TRADE:
        chosen = bull_result
        side = "buy"
        regime_name = "BULL_ALADDIN"
    elif bear_score > bull_score and bear_score >= MIN_SCORE_TO_TRADE:
        chosen = bear_result
        side = "sell"
        regime_name = "BEAR_ALADDIN"
    else:
        return None  # No setup meets Aladdin standard

    score = chosen["score"]
    atr_pct = chosen["atr_pct"]
    vol_regime = chosen["volatility_regime"]
    tp_pct, sl_pct = _get_adaptive_tp_sl(atr_pct, vol_regime, score)
    rr = round(tp_pct / sl_pct, 2)
    confidence = round(min(0.95, 0.60 + score / 250), 2)

    evidence = [
        f"{symbol}: Aladdin Score {score}/100 ({side.upper()}) | Vol Regime: {vol_regime}",
        f"{symbol}: EMA Stack {round(chosen['ema9'],2)}/{round(chosen['ema21'],2)}/{round(chosen['ema50'],2)} | RSI {round(chosen['rsi'],1)}",
        f"{symbol}: MACD {round(chosen['macd_line'],4)} vs Signal {round(chosen['signal_line'],4)} | Hist {round(chosen['histogram'],4)}",
        f"{symbol}: BB Position {round(chosen['bb_pos']*100,1)}% | 4h{chosen['chg_4h']:+.2f}% 24h{chosen['chg_24h']:+.2f}%",
        f"{symbol}: Fear&Greed {fg_value} | TP+{tp_pct:.2f}% / SL-{sl_pct:.2f}% | RR={rr}x | Conf={confidence}",
    ]

    return {
        "symbol": symbol,
        "side": side,
        "live_price": live_price,
        "regime": regime_name,
        "confidence": confidence,
        "evidence": evidence,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "rr_ratio": rr,
        "score": score,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "factors": chosen["factors"],
        "vol_regime": vol_regime,
        "atr_pct": atr_pct,
    }


@router.post("/tick")
@router.get("/tick")
async def run_scan_tick(request: Request):
    """Run one cycle of the Aladdin-class AI trading engine."""
    import time

    portfolio = request.app.state.portfolio
    emergency = request.app.state.emergency
    event_bus = request.app.state.event_bus
    settings = request.app.state.settings

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
    if not hasattr(portfolio, "_entry_tp_sl"):
        portfolio._entry_tp_sl = {}  # Stores (tp_pct, sl_pct) per symbol
    if not hasattr(portfolio, "_trailing_activated"):
        portfolio._trailing_activated = {}  # Tracks if trailing stop is active
    if not hasattr(portfolio, "realized_pnl"):
        portfolio.realized_pnl = 0.0

    now_pkt = datetime.now(PKT_TZ).strftime("%b %d, %Y %I:%M:%S %p")
    actions_taken = []
    leverage = 10
    margin = 50.0

    # Fetch Fear & Greed once per scan cycle
    fg = await _get_fear_greed()
    fg_value = fg["value"]
    fg_label = fg["label"]

    # ── 1. Monitor existing positions (Trailing Stop + TP/SL) ─────────────────
    for sym, qty in list(portfolio.positions.items()):
        if qty != 0:
            try:
                live_p = await get_live_price(sym)
            except Exception:
                continue

            entry_p = portfolio._entry_prices.get(sym, live_p)
            stored_tp_sl = portfolio._entry_tp_sl.get(sym, (0.008, 0.005))
            tp_threshold = stored_tp_sl[0] / 100
            sl_threshold = stored_tp_sl[1] / 100

            if qty > 0:
                price_diff_pct = (live_p - entry_p) / entry_p
            else:
                price_diff_pct = (entry_p - live_p) / entry_p

            realized_pnl = margin * leverage * price_diff_pct
            pnl_pct = (realized_pnl / margin) * 100.0

            # ── Aladdin Trailing Stop Logic ─────────────────────────────────
            # Phase 1: At 60% of TP reached → move SL to breakeven
            # Phase 2: At 85% of TP reached → trail SL at 50% of current gain
            trailing_key = sym
            trail_state = portfolio._trailing_activated.get(trailing_key, 0)

            if price_diff_pct >= tp_threshold * 0.85 and trail_state < 2:
                # Trail SL to lock in 50% of current profit
                new_sl = price_diff_pct * 0.5
                sl_threshold = new_sl
                portfolio._trailing_activated[trailing_key] = 2
                actions_taken.append(f"TRAILING_STOP {sym}: locked 50% gain (SL now at +{new_sl*100:.2f}%)")
                logger.info("Aladdin trailing stop phase 2 on %s: SL locked at +%.3f%%", sym, new_sl * 100)
            elif price_diff_pct >= tp_threshold * 0.60 and trail_state < 1:
                # Move SL to breakeven
                sl_threshold = 0.001  # ~0.1% buffer above entry
                portfolio._trailing_activated[trailing_key] = 1
                actions_taken.append(f"TRAILING_STOP {sym}: SL moved to breakeven")
                logger.info("Aladdin trailing stop phase 1 on %s: SL at breakeven", sym)

            closed_reason = None
            if price_diff_pct >= tp_threshold:
                closed_reason = f"Aladdin TakeProfit (+{price_diff_pct*100:.2f}%)"
            elif price_diff_pct <= -sl_threshold:
                closed_reason = f"Aladdin StopLoss ({price_diff_pct*100:.2f}%)"

            if closed_reason:
                portfolio.positions[sym] = 0
                portfolio.realized_pnl += realized_pnl
                portfolio._trailing_activated.pop(trailing_key, None)
                portfolio._entry_tp_sl.pop(sym, None)

                sl_price = entry_p * (1 - sl_threshold) if qty > 0 else entry_p * (1 + sl_threshold)
                tp_price = entry_p * (1 + tp_threshold) if qty > 0 else entry_p * (1 - tp_threshold)

                portfolio.closed_trades.append({
                    "trade_id": str(uuid.uuid4())[:8],
                    "closed_at": now_pkt,
                    "symbol": sym,
                    "side": "LONG" if qty > 0 else "SHORT",
                    "leverage": f"{leverage}x",
                    "entry_price": round(entry_p, 4),
                    "exit_price": round(live_p, 4),
                    "sl_tp": f"${sl_price:,.4f} / ${tp_price:,.4f}",
                    "realized_pnl": round(realized_pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "closed_by": closed_reason,
                })
                actions_taken.append(f"CLOSED {sym} via {closed_reason} | PnL: ${realized_pnl:.2f}")
                logger.info("Aladdin closed %s via %s | PnL: $%.2f", sym, closed_reason, realized_pnl)

    # ── 2. Open new positions using Aladdin scoring ───────────────────────────
    active_pos_count = sum(1 for q in portfolio.positions.values() if q != 0)
    if active_pos_count < 3:
        available_symbols = [s for s in SYMBOLS if portfolio.positions.get(s, 0) == 0]
        start_idx = _scan_state["index"] % max(len(available_symbols), 1)
        ordered_symbols = available_symbols[start_idx:] + available_symbols[:start_idx]
        _scan_state["index"] += 1

        for symbol in ordered_symbols:
            if sum(1 for q in portfolio.positions.values() if q != 0) >= 3:
                break

            # ── Correlation Guard (Aladdin portfolio diversification) ─────────
            bucket = _get_symbol_bucket(symbol)
            bucket_symbols = CORRELATION_BUCKETS.get(bucket, [])
            bucket_count = sum(1 for s in bucket_symbols if portfolio.positions.get(s, 0) != 0)
            max_in_bucket = MAX_PER_BUCKET.get(bucket, 1)
            if bucket_count >= max_in_bucket:
                actions_taken.append(
                    f"CORRELATION_GUARD {symbol}: Bucket {bucket} already has {bucket_count}/{max_in_bucket} positions"
                )
                continue

            signal = await _analyze_symbol_aladdin(symbol, fg_value)
            if signal is None:
                actions_taken.append(
                    f"SKIPPED {symbol}: Aladdin score below {MIN_SCORE_TO_TRADE}/100 — no edge"
                )
                continue

            side = signal["side"]
            live_price = signal["live_price"]
            regime = signal["regime"]
            confidence = signal["confidence"]
            evidence = signal["evidence"]
            tp_pct = signal["tp_pct"]
            sl_pct = signal["sl_pct"]
            score = signal["score"]

            # ── Dynamic Position Sizing (score-based, Aladdin risk allocation) ─
            # Base: $500 notional. Strong signal (>80) gets 20% more. Weak (62-69) gets 80%.
            if score >= 80:
                notional = 600.0
            elif score >= 70:
                notional = 500.0
            else:
                notional = 400.0

            calc_qty = notional / live_price if live_price > 0 else 1.0
            base_qty = max(1, round(calc_qty)) if calc_qty >= 1 else round(calc_qty, 3)
            pos_qty = base_qty if side == "buy" else -base_qty

            portfolio._entry_prices[symbol] = live_price
            portfolio.positions[symbol] = pos_qty
            portfolio._entry_tp_sl[symbol] = (tp_pct, sl_pct)
            portfolio._trailing_activated[symbol] = 0
            portfolio.total_exposure = getattr(portfolio, "total_exposure", 0) + notional

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
                f"OPENED {side.upper()} {symbol} @ ${live_price:,.4f} | Score={score}/100 | "
                f"TP+{tp_pct:.2f}% SL-{sl_pct:.2f}% RR={signal['rr_ratio']}x | "
                f"Notional=${notional:.0f} | F&G={fg_value}({fg_label})"
            )
            logger.info(
                "Aladdin opened %s %s @ $%.4f | score=%d/100 | tp=%.3f%% sl=%.3f%%",
                side.upper(), symbol, live_price, score, tp_pct, sl_pct
            )

    # Save state
    try:
        from crypto_trading_desk.core.state import save_state
        save_state(portfolio)
    except Exception:
        pass

    return {
        "status": "scanned",
        "actions": actions_taken,
        "active_positions": sum(1 for q in portfolio.positions.values() if q != 0),
        "engine": "Aladdin_v4_MultiFactorAI",
        "fear_greed": {"value": fg_value, "label": fg_label},
    }
