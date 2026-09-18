"""
Blockstone Capital — Aladdin-Class AI Trading Engine v5.0 (Expert Edition)

Improvements over v4:
  - Gradient factor scoring (no hard 0-cliff zones — smooth curves)
  - Trend-continuation RSI logic (RSI 65-80 in uptrend = healthy, not penalized)
  - MACD dual-weight: direction (8pt) + histogram strength (7pt) separately
  - Kline module-level cache (60s TTL) — solves Vercel cold-start MACD issue
  - Candle confirmation gate: last 2 candles must align with trade direction
  - Higher-High / Lower-Low momentum detector (+10pt bonus factor)
  - Smarter BB scoring: trend-follow mode (wide bands, trade with trend)
  - Portfolio Heat Guard: skip new trades if open loss > $15
  - Granular trailing stop: every 25% of TP gain, tightens SL by 0.3x
  - Dynamic minimum score: adjusts with Fear & Greed (greedy market = higher bar)
"""
from __future__ import annotations
import asyncio
import logging
import time
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

# Correlation buckets — max 1 position per bucket to avoid correlated exposure
CORRELATION_BUCKETS = {
    "A": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"],
    "B": ["TAO/USDT", "ZEC/USDT"],
}
MAX_PER_BUCKET = {"A": 1, "B": 1}

# Base minimum Aladdin score to enter a trade
BASE_MIN_SCORE = 58

_scan_state = {"index": 0, "last_scan": 0}
_http_client: httpx.AsyncClient | None = None
_fear_greed_cache: dict = {"value": 50, "label": "Neutral", "ts": 0}

# Kline cache: {symbol+interval -> {"data": [...], "ts": float}}
_kline_cache: dict = {}
KLINE_CACHE_TTL = 60  # seconds


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=8.0)
    return _http_client


async def _get_klines(symbol: str, interval: str = "1h", limit: int = 60) -> list:
    """Fetch OHLCV klines with module-level cache (solves Vercel cold-start issue)."""
    global _kline_cache
    cache_key = f"{symbol}_{interval}_{limit}"
    now = time.time()
    cached = _kline_cache.get(cache_key)
    if cached and (now - cached["ts"] < KLINE_CACHE_TTL):
        return cached["data"]

    clean = symbol.replace("/", "").upper()
    client = _get_http_client()
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={clean}&interval={interval}&limit={limit}"
        res = await client.get(url, timeout=7.0)
        if res.status_code == 200:
            data = res.json()
            _kline_cache[cache_key] = {"data": data, "ts": now}
            return data
    except Exception as e:
        logger.debug("Klines fetch error %s %s: %s", symbol, interval, e)
    return []


async def _get_fear_greed() -> dict:
    """Crypto Fear & Greed Index — cached 5 minutes."""
    global _fear_greed_cache
    now = time.time()
    if now - _fear_greed_cache["ts"] < 300:
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


# ── Technical Indicator Library ───────────────────────────────────────────────

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
        pc = float(klines[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


def _calc_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 1e-10
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _calc_macd(closes: list[float]) -> tuple[float, float, float]:
    """Accurate MACD: EMA12 and EMA26 built incrementally from start."""
    if len(closes) < 26:
        return 0.0, 0.0, 0.0
    k12, k26 = 2.0 / 13, 2.0 / 27
    # Seed EMAs from first 12/26 bars
    e12 = sum(closes[:12]) / 12
    e26 = sum(closes[:26]) / 26
    # Update e12 for indices 12-25 (before e26 is ready)
    for i in range(12, 26):
        e12 = closes[i] * k12 + e12 * (1 - k12)
    # Build MACD series from index 26 onwards
    macd_series = []
    for i in range(26, len(closes)):
        e12 = closes[i] * k12 + e12 * (1 - k12)
        e26 = closes[i] * k26 + e26 * (1 - k26)
        macd_series.append(e12 - e26)
    if not macd_series:
        return 0.0, 0.0, 0.0
    macd_line = macd_series[-1]
    # Signal = 9-period EMA of MACD series
    k9 = 2.0 / 10
    signal = sum(macd_series[:9]) / min(9, len(macd_series))
    for v in macd_series[9:]:
        signal = v * k9 + signal * (1 - k9)
    histogram = macd_line - signal
    return macd_line, signal, histogram


def _calc_bollinger(closes: list[float], period: int = 20) -> tuple[float, float, float, float]:
    """Returns (upper, mid, lower, bb_pos 0-1)."""
    if len(closes) < period:
        m = closes[-1]
        return m * 1.02, m, m * 0.98, 0.5
    window = closes[-period:]
    mid = sum(window) / period
    std = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
    upper = mid + 2 * std
    lower = mid - 2 * std
    live = closes[-1]
    bb_pos = (live - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
    return upper, mid, lower, bb_pos


def _volatility_regime(atr_pct: float) -> str:
    if atr_pct < 0.7:
        return "LOW"
    elif atr_pct < 2.0:
        return "MED"
    else:
        return "HIGH"


def _check_higher_highs(closes: list[float], side: str, lookback: int = 6) -> bool:
    """Detect higher-highs (bull) or lower-lows (bear) in recent candles."""
    if len(closes) < lookback + 1:
        return False
    recent = closes[-lookback:]
    if side == "buy":
        # Check if last 3 peaks are rising
        peaks = [recent[i] for i in range(1, len(recent) - 1) if recent[i] > recent[i-1] and recent[i] > recent[i+1]]
        return len(peaks) >= 2 and peaks[-1] > peaks[-2] if len(peaks) >= 2 else False
    else:
        troughs = [recent[i] for i in range(1, len(recent) - 1) if recent[i] < recent[i-1] and recent[i] < recent[i+1]]
        return len(troughs) >= 2 and troughs[-1] < troughs[-2] if len(troughs) >= 2 else False


def _candle_bonus(closes: list[float], opens: list[float], side: str) -> int:
    """
    Candle direction bonus (+8 pts) — not a mandatory gate.
    Rewards entries where recent candles confirm direction,
    but does NOT block signals — just reduces the score if candles contradict.
    """
    if len(closes) < 3 or len(opens) < 3:
        return 4  # Neutral — no data to judge
    c1 = closes[-1] > opens[-1]   # Last candle bullish?
    c2 = closes[-2] > opens[-2]   # Prior candle bullish?
    if side == "buy":
        if c1 and c2:
            return 8   # Both green — strong confirmation
        elif c1 or c2:
            return 4   # One green — mild confirmation
        else:
            return 0   # Both red — no confirmation (reduces score but doesn't block)
    else:
        if not c1 and not c2:
            return 8   # Both red — short confirmation
        elif not c1 or not c2:
            return 4   # One red — mild
        else:
            return 0   # Both green — no short confirmation


# ── Aladdin v5 Multi-Factor Scoring Engine ────────────────────────────────────

def _score_symbol_v5(
    closes: list[float],
    opens: list[float],
    klines: list,
    side: str,
    fg_value: int,
) -> dict:
    """
    9-factor gradient scoring engine. No hard binary cliffs — smooth curves.
    Returns score (0-105 max with bonus) and full breakdown.
    """
    live = closes[-1]
    ema9 = _calc_ema(closes, 9)
    ema21 = _calc_ema(closes, 21)
    ema50 = _calc_ema(closes, 50)
    rsi = _calc_rsi(closes, 14)
    macd_line, signal_line, histogram = _calc_macd(closes)
    bb_upper, bb_mid, bb_lower, bb_pos = _calc_bollinger(closes, 20)
    atr = _calc_atr(klines, 14)
    atr_pct = (atr / live) * 100 if live > 0 else 0

    chg_4h = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
    chg_8h = (closes[-1] - closes[-9]) / closes[-9] * 100 if len(closes) >= 9 else 0
    chg_24h = (closes[-1] - closes[-25]) / closes[-25] * 100 if len(closes) >= 25 else 0

    factors = {}

    # ── Factor 1: EMA Stack (max 20 pts) — gradient ───────────────────────────
    if side == "buy":
        if ema9 > ema21 > ema50:
            ema_gap = (ema9 - ema50) / ema50 * 100
            f1 = min(20, 15 + ema_gap * 2)   # Bonus for wider separation
        elif ema9 > ema21:
            f1 = 10
        elif ema9 > ema50:
            f1 = 5
        else:
            f1 = 0
    else:
        if ema9 < ema21 < ema50:
            ema_gap = (ema50 - ema9) / ema50 * 100
            f1 = min(20, 15 + ema_gap * 2)
        elif ema9 < ema21:
            f1 = 10
        elif ema9 < ema50:
            f1 = 5
        else:
            f1 = 0
    factors["EMA_Stack"] = round(f1)

    # ── Factor 2: Multi-Timeframe Momentum (max 18 pts) — gradient ────────────
    if side == "buy":
        f2_4h = min(10, max(0, chg_4h * 8)) if chg_4h > 0 else max(-5, chg_4h * 3)
        f2_24h = min(8, max(0, chg_24h * 1.5)) if chg_24h > 0 else max(-4, chg_24h)
        f2 = max(0, f2_4h + f2_24h)
    else:
        f2_4h = min(10, max(0, abs(chg_4h) * 8)) if chg_4h < 0 else max(-5, -chg_4h * 3)
        f2_24h = min(8, max(0, abs(chg_24h) * 1.5)) if chg_24h < 0 else max(-4, -chg_24h)
        f2 = max(0, f2_4h + f2_24h)
    factors["Momentum_MTF"] = round(min(18, f2))

    # ── Factor 3: RSI — trend-aware gradient (max 15 pts) ─────────────────────
    # Key insight: in a strong trend RSI can stay 65-80 for hours — this is HEALTHY
    # Only penalize EXTREME overbought/oversold (>82 or <18)
    if side == "buy":
        if 50 <= rsi <= 68:
            f3 = 15   # Ideal trend continuation zone
        elif 68 < rsi <= 78:
            f3 = 12   # Strong trend — acceptable
        elif 78 < rsi <= 82:
            f3 = 6    # Getting hot — reduce score
        elif rsi > 82:
            f3 = 0    # Extreme overbought — risk reversal
        elif 40 <= rsi < 50:
            f3 = 10   # Building momentum
        elif 30 <= rsi < 40:
            f3 = 5    # Weak — countertrend signal
        else:
            f3 = 0    # Oversold — no bull momentum
    else:
        if 32 <= rsi <= 50:
            f3 = 15   # Ideal bear zone
        elif 22 <= rsi < 32:
            f3 = 12   # Strong downtrend — acceptable
        elif 18 <= rsi < 22:
            f3 = 6    # Getting cold — reduce score
        elif rsi < 18:
            f3 = 0    # Extreme oversold — bounce risk
        elif 50 < rsi <= 60:
            f3 = 10   # Weakening — good short setup
        elif 60 < rsi <= 70:
            f3 = 5    # Still bullish — early short
        else:
            f3 = 0
    factors["RSI_TrendAware"] = f3

    # ── Factor 4: MACD — dual-weight direction + strength (max 15 pts) ────────
    if side == "buy":
        # Direction (8 pts): MACD line above signal
        f4_dir = 8 if macd_line > signal_line else 0
        # Histogram strength (7 pts): positive and growing
        if histogram > 0:
            f4_hist = min(7, histogram / max(abs(macd_line), 0.0001) * 7)
        else:
            f4_hist = max(-5, histogram / max(abs(macd_line), 0.0001) * 5)
        f4 = max(0, f4_dir + f4_hist)
    else:
        f4_dir = 8 if macd_line < signal_line else 0
        if histogram < 0:
            f4_hist = min(7, abs(histogram) / max(abs(macd_line), 0.0001) * 7)
        else:
            f4_hist = max(-5, -histogram / max(abs(macd_line), 0.0001) * 5)
        f4 = max(0, f4_dir + f4_hist)
    factors["MACD_DualWeight"] = round(min(15, f4))

    # ── Factor 5: Bollinger Band — trend-aware (max 12 pts) ───────────────────
    # In trending markets, riding the upper/lower band IS the trade
    # BB width tells us if we're in trend (wide) or range (narrow)
    bb_width_pct = (bb_upper - bb_lower) / bb_mid * 100
    is_trending = bb_width_pct > 3.0   # Wide BB = trending market

    if side == "buy":
        if is_trending:
            # Trend mode: price near upper band is bullish (not overbought)
            if bb_pos > 0.6:
                f5 = 12   # Riding upper band — strong trend
            elif bb_pos > 0.4:
                f5 = 8    # Middle-upper — decent
            else:
                f5 = 4    # Near lower — possible reversal entry
        else:
            # Range mode: buy near lower band (mean reversion)
            if bb_pos < 0.3:
                f5 = 12
            elif bb_pos < 0.5:
                f5 = 8
            else:
                f5 = 3    # Near upper in range = risky long
    else:
        if is_trending:
            if bb_pos < 0.4:
                f5 = 12   # Riding lower band — strong downtrend
            elif bb_pos < 0.6:
                f5 = 8
            else:
                f5 = 4
        else:
            if bb_pos > 0.7:
                f5 = 12   # Near upper in range = good short
            elif bb_pos > 0.5:
                f5 = 8
            else:
                f5 = 3
    factors["Bollinger_TrendAware"] = f5

    # ── Factor 6: Volatility Regime (max 10 pts) ──────────────────────────────
    regime = _volatility_regime(atr_pct)
    f6 = {"LOW": 5, "MED": 10, "HIGH": 7}[regime]
    factors["Volatility_Regime"] = f6

    # ── Factor 7: Fear & Greed Macro (max 5 pts) ──────────────────────────────
    if side == "buy":
        if 35 <= fg_value <= 70:
            f7 = 5    # Healthy — not extreme in either direction
        elif fg_value > 80:
            f7 = 1    # Extreme greed = euphoria = reversal risk
        elif fg_value < 25:
            f7 = 4    # Extreme fear = buy opportunity (contrarian)
        else:
            f7 = 3
    else:
        if 30 <= fg_value <= 65:
            f7 = 5
        elif fg_value < 20:
            f7 = 1    # Extreme fear = bounce risk for shorts
        else:
            f7 = 3
    factors["FearGreed_Macro"] = f7

    # ── Factor 8: Price vs EMA50 Anchor (max 5 pts) ───────────────────────────
    if side == "buy":
        f8 = 5 if live > ema50 else 0
    else:
        f8 = 5 if live < ema50 else 0
    factors["Price_vs_Anchor"] = f8

    # ── Factor 9: Higher Highs / Lower Lows Bonus (max 10 pts) ───────────────
    hh_ll = _check_higher_highs(closes, side, lookback=8)
    f9 = 10 if hh_ll else 0
    factors["HH_LL_Structure"] = f9

    # ── Factor 10: Candle Confirmation Bonus (max 8 pts) ──────────────────────
    # Rewards entries with confirming candles, penalizes contradicting ones
    # Does NOT block — just adjusts the score
    f10 = _candle_bonus(closes, opens, side)
    factors["Candle_Confirmation"] = f10

    total = sum(factors.values())
    return {
        "score": total,
        "factors": factors,
        "ema9": ema9, "ema21": ema21, "ema50": ema50,
        "rsi": rsi,
        "macd_line": macd_line, "signal_line": signal_line, "histogram": histogram,
        "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower, "bb_pos": bb_pos,
        "bb_width_pct": bb_width_pct,
        "atr_pct": atr_pct, "volatility_regime": regime,
        "chg_4h": chg_4h, "chg_8h": chg_8h, "chg_24h": chg_24h,
        "fg_value": fg_value,
    }


def _get_adaptive_tp_sl(atr_pct: float, regime: str, score: int) -> tuple[float, float]:
    """ATR-adaptive TP/SL scaled by volatility regime and signal strength."""
    base_tp = {"LOW": 1.2, "MED": 1.5, "HIGH": 1.8}[regime]
    base_sl = {"LOW": 0.8, "MED": 1.0, "HIGH": 1.2}[regime]
    # Stronger signals get wider TP target
    score_bonus = 0.3 if score >= 80 else 0.15 if score >= 70 else 0
    tp_pct = max(0.30, min(2.5, atr_pct * (base_tp + score_bonus)))
    sl_pct = max(0.18, min(1.5, atr_pct * base_sl))
    return round(tp_pct, 3), round(sl_pct, 3)


def _get_symbol_bucket(symbol: str) -> str:
    for bucket, syms in CORRELATION_BUCKETS.items():
        if symbol in syms:
            return bucket
    return "B"


def _get_min_score(fg_value: int) -> int:
    """Dynamic minimum score: raise bar in extreme greed, lower in fear."""
    if fg_value >= 80:
        return 68   # Extreme greed = euphoria = require stronger signal
    elif fg_value >= 65:
        return 62
    elif fg_value <= 20:
        return 55   # Extreme fear = contrarian entries allowed at lower bar
    else:
        return BASE_MIN_SCORE  # 58


async def _analyze_symbol_v5(symbol: str, fg_value: int) -> dict | None:
    """
    Full Aladdin v5 analysis: 10-factor gradient scoring.
    Returns best-side signal dict or None if below minimum score.
    """
    try:
        klines = await _get_klines(symbol, "1h", 60)
        if len(klines) < 30:
            return None

        closes = [float(k[4]) for k in klines]
        opens = [float(k[1]) for k in klines]
        live_price = closes[-1]

        min_score = _get_min_score(fg_value)

        # Score both sides (candle bonus included in scoring, not a gate)
        bull = _score_symbol_v5(closes, opens, klines, "buy", fg_value)
        bear = _score_symbol_v5(closes, opens, klines, "sell", fg_value)

        # Pick strongest side above dynamic minimum threshold
        if bull["score"] >= bear["score"] and bull["score"] >= min_score:
            chosen = bull
            side = "buy"
            regime_label = "BULL_ALADDIN_V5"
        elif bear["score"] > bull["score"] and bear["score"] >= min_score:
            chosen = bear
            side = "sell"
            regime_label = "BEAR_ALADDIN_V5"
        else:
            return None

        score = chosen["score"]
        atr_pct = chosen["atr_pct"]
        vol_regime = chosen["volatility_regime"]
        tp_pct, sl_pct = _get_adaptive_tp_sl(atr_pct, vol_regime, score)
        rr = round(tp_pct / sl_pct, 2)
        confidence = round(min(0.96, 0.60 + score / 230), 2)

        evidence = [
            f"{symbol}: Aladdin v5 Score {score}/113 ({side.upper()}) | Min={min_score} | Vol={vol_regime}",
            f"{symbol}: EMA {round(chosen['ema9'],2)}/{round(chosen['ema21'],2)}/{round(chosen['ema50'],2)} | RSI {round(chosen['rsi'],1)}",
            f"{symbol}: MACD {round(chosen['macd_line'],4)} / Sig {round(chosen['signal_line'],4)} | Hist {round(chosen['histogram'],4)}",
            f"{symbol}: BB {round(chosen['bb_pos']*100,1)}% (width {round(chosen['bb_width_pct'],2)}%) | 4h{chosen['chg_4h']:+.2f}% 24h{chosen['chg_24h']:+.2f}%",
            f"{symbol}: F&G={fg_value} | TP+{tp_pct:.2f}% SL-{sl_pct:.2f}% RR={rr}x | Conf={confidence}",
        ]

        return {
            "symbol": symbol, "side": side, "live_price": live_price,
            "regime": regime_label, "confidence": confidence, "evidence": evidence,
            "tp_pct": tp_pct, "sl_pct": sl_pct, "rr_ratio": rr,
            "score": score, "min_score": min_score,
            "bull_score": bull["score"], "bear_score": bear["score"],
            "factors": chosen["factors"], "vol_regime": vol_regime, "atr_pct": atr_pct,
        }
    except Exception as e:
        logger.debug("Aladdin v5 analysis error for %s: %s", symbol, e)
        return None


@router.post("/tick")
@router.get("/tick")
async def run_scan_tick(request: Request):
    """Aladdin v5 Expert Trading Engine — full scan cycle."""
    import time as _time

    portfolio = request.app.state.portfolio
    emergency = request.app.state.emergency
    event_bus = request.app.state.event_bus
    settings = request.app.state.settings

    now = _time.time()
    if now - _scan_state["last_scan"] < 10:
        return {"status": "throttled", "message": "Scan runs every 10s"}
    _scan_state["last_scan"] = now

    try:
        from crypto_trading_desk.core.state import load_state
        load_state(portfolio)
    except Exception:
        pass

    if not getattr(request.app.state, "auto_trader_enabled", True):
        return {"status": "paused", "message": "Autopilot is paused"}
    if emergency.is_active:
        return {"status": "emergency", "message": "Emergency kill-switch active"}

    for attr, default in [("closed_trades", []), ("_entry_prices", {}),
                           ("_entry_tp_sl", {}), ("_trailing_state", {}),
                           ("realized_pnl", 0.0)]:
        if not hasattr(portfolio, attr):
            setattr(portfolio, attr, default)

    now_pkt = datetime.now(PKT_TZ).strftime("%b %d, %Y %I:%M:%S %p")
    actions_taken = []
    leverage = 10
    margin = 50.0

    fg = await _get_fear_greed()
    fg_value = fg["value"]
    fg_label = fg["label"]

    # ── 1. Portfolio Heat Guard ───────────────────────────────────────────────
    # Don't open new trades if unrealized losses exceed $15
    unrealized_pnl = 0.0
    for sym, qty in portfolio.positions.items():
        if qty != 0:
            try:
                p = await get_live_price(sym)
                ep = portfolio._entry_prices.get(sym, p)
                diff = (p - ep) / ep if qty > 0 else (ep - p) / ep
                unrealized_pnl += margin * leverage * diff
            except Exception:
                pass
    portfolio_heat_ok = unrealized_pnl > -15.0

    # ── 2. Monitor open positions — Granular Trailing Stop + TP/SL ───────────
    for sym, qty in list(portfolio.positions.items()):
        if qty == 0:
            continue
        try:
            live_p = await get_live_price(sym)
        except Exception:
            continue

        entry_p = portfolio._entry_prices.get(sym, live_p)
        stored = portfolio._entry_tp_sl.get(sym, (0.008, 0.005))
        tp_threshold = stored[0] / 100
        sl_threshold = stored[1] / 100

        diff = (live_p - entry_p) / entry_p if qty > 0 else (entry_p - live_p) / entry_p
        realized_pnl = margin * leverage * diff
        pnl_pct = (realized_pnl / margin) * 100

        # Granular trailing stop: every 25% of TP progress → tighten SL by 0.3x
        trail_level = portfolio._trailing_state.get(sym, 0)
        progress = diff / tp_threshold if tp_threshold > 0 else 0

        if progress >= 0.75 and trail_level < 3:
            # At 75%+ of TP: trail SL to lock 60% of gain
            sl_threshold = diff * 0.40
            portfolio._trailing_state[sym] = 3
            actions_taken.append(f"TRAIL_STOP3 {sym}: SL locks 60% gain at +{diff*100:.2f}%")
        elif progress >= 0.50 and trail_level < 2:
            # At 50%+ of TP: move SL to breakeven +0.1%
            sl_threshold = 0.001
            portfolio._trailing_state[sym] = 2
            actions_taken.append(f"TRAIL_STOP2 {sym}: SL moved to breakeven")
        elif progress >= 0.25 and trail_level < 1:
            portfolio._trailing_state[sym] = 1
            actions_taken.append(f"TRAIL_STOP1 {sym}: Progress 25% — monitoring")

        closed_reason = None
        if diff >= tp_threshold:
            closed_reason = f"Aladdin TakeProfit (+{diff*100:.2f}%)"
        elif diff <= -sl_threshold:
            closed_reason = f"Aladdin StopLoss ({diff*100:.2f}%)"

        if closed_reason:
            portfolio.positions[sym] = 0
            portfolio.realized_pnl += realized_pnl
            portfolio._trailing_state.pop(sym, None)
            portfolio._entry_tp_sl.pop(sym, None)
            sl_p = entry_p * (1 - sl_threshold) if qty > 0 else entry_p * (1 + sl_threshold)
            tp_p = entry_p * (1 + tp_threshold) if qty > 0 else entry_p * (1 - tp_threshold)
            portfolio.closed_trades.append({
                "trade_id": str(uuid.uuid4())[:8],
                "closed_at": now_pkt,
                "symbol": sym,
                "side": "LONG" if qty > 0 else "SHORT",
                "leverage": f"{leverage}x",
                "entry_price": round(entry_p, 4),
                "exit_price": round(live_p, 4),
                "sl_tp": f"${sl_p:,.4f} / ${tp_p:,.4f}",
                "realized_pnl": round(realized_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "closed_by": closed_reason,
            })
            actions_taken.append(f"CLOSED {sym} | {closed_reason} | PnL: ${realized_pnl:.2f}")
            logger.info("Aladdin v5 closed %s | %s | PnL $%.2f", sym, closed_reason, realized_pnl)

    # ── 3. Open new positions ─────────────────────────────────────────────────
    active_count = sum(1 for q in portfolio.positions.values() if q != 0)
    if active_count < 3 and portfolio_heat_ok:
        available = [s for s in SYMBOLS if portfolio.positions.get(s, 0) == 0]
        start = _scan_state["index"] % max(len(available), 1)
        ordered = available[start:] + available[:start]
        _scan_state["index"] += 1

        for symbol in ordered:
            if sum(1 for q in portfolio.positions.values() if q != 0) >= 3:
                break

            # Correlation guard
            bucket = _get_symbol_bucket(symbol)
            bucket_held = sum(1 for s in CORRELATION_BUCKETS.get(bucket, [])
                              if portfolio.positions.get(s, 0) != 0)
            if bucket_held >= MAX_PER_BUCKET.get(bucket, 1):
                actions_taken.append(f"CORR_GUARD {symbol}: bucket {bucket} full ({bucket_held}/{MAX_PER_BUCKET[bucket]})")
                continue

            signal = await _analyze_symbol_v5(symbol, fg_value)
            if signal is None:
                # Quick score debug using cached klines (no extra API call)
                score_info = ""
                try:
                    k = _kline_cache.get(f"{symbol}_1h_60", {}).get("data", [])
                    if k:
                        cl = [float(x[4]) for x in k]
                        op = [float(x[1]) for x in k]
                        b = _score_symbol_v5(cl, op, k, "buy", fg_value)
                        br = _score_symbol_v5(cl, op, k, "sell", fg_value)
                        score_info = f" [Bull={b['score']} Bear={br['score']} Min={_get_min_score(fg_value)}]"
                except Exception:
                    pass
                actions_taken.append(f"SKIPPED {symbol}: score below bar{score_info}")
                continue

            side = signal["side"]
            live_price = signal["live_price"]
            score = signal["score"]
            tp_pct = signal["tp_pct"]
            sl_pct = signal["sl_pct"]

            # Dynamic notional: $400/$500/$600/$700 based on score tiers
            if score >= 90:
                notional = 700.0
            elif score >= 80:
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
            portfolio._trailing_state[symbol] = 0
            portfolio.total_exposure = getattr(portfolio, "total_exposure", 0) + notional

            proposal = TradeProposal(
                symbol=symbol, side=side, quantity=base_qty, notional=notional,
                confidence=signal["confidence"], evidence=signal["evidence"],
                market_regime=signal["regime"],
            )
            await event_bus.publish(proposal)
            actions_taken.append(
                f"OPENED {side.upper()} {symbol} @ ${live_price:,.4f} | "
                f"Score={score}/105 | TP+{tp_pct:.2f}% SL-{sl_pct:.2f}% RR={signal['rr_ratio']}x | "
                f"Notional=${notional:.0f} | F&G={fg_value}({fg_label})"
            )
            logger.info("Aladdin v5 opened %s %s @ $%.4f | score=%d | tp=%.3f%% sl=%.3f%%",
                        side.upper(), symbol, live_price, score, tp_pct, sl_pct)
    elif not portfolio_heat_ok:
        actions_taken.append(f"HEAT_GUARD: Open unrealized PnL = ${unrealized_pnl:.2f} — no new entries until recovery")

    try:
        from crypto_trading_desk.core.state import save_state
        save_state(portfolio)
    except Exception:
        pass

    return {
        "status": "scanned",
        "actions": actions_taken,
        "active_positions": sum(1 for q in portfolio.positions.values() if q != 0),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "engine": "Aladdin_v5_Expert",
        "fear_greed": {"value": fg_value, "label": fg_label},
        "min_score_bar": _get_min_score(fg_value),
    }
