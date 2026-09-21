"""
Blockstone Capital — Aladdin-Class AI Swing Trading Engine v6.0

Transformed from Scalping to Institutional Swing Trading:
  - Multi-Timeframe Architecture: 4-Hour (4H) primary execution + 1-Day (1D) macro trend filter
  - Swing Targets: Realistic 3.5% to 8.5% Take-Profit, 1.8% to 3.5% Stop-Loss (R:R 2.0x - 3.0x)
  - Wide stops survive normal intra-day noise, wicks, and volatility
  - Swing Pullback Detection: Enters on pullbacks to 4H EMA21/50, never chasing tops/bottoms
  - 1D Macro Confluence: Never swing trade against the Daily institutional tide
  - 3-Stage Swing Trailing Ratchet: Moves to Breakeven at +2.0% profit, trails to lock 50-75% at higher tiers
  - Aladdin Portfolio Correlation Guard: Max 1 position per correlated bucket
  - Dynamic Conviction Sizing: $400 / $500 / $650 notional based on multi-factor swing score
  - Cloud-Grade Multi-Exchange Pipeline: MEXC + Bybit + Binance fallback with in-memory caching
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

# Minimum Aladdin Swing Score to enter a position (out of 107 max points)
BASE_MIN_SWING_SCORE = 60

_scan_state = {"index": 0, "last_scan": 0}
_http_client: httpx.AsyncClient | None = None
_fear_greed_cache: dict = {"value": 50, "label": "Neutral", "ts": 0}

# Kline cache: {symbol+interval -> {"data": [...], "ts": float}}
_kline_cache: dict = {}
KLINE_CACHE_TTL = 90  # 90 seconds TTL for 4h/1d candles


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=8.0)
    return _http_client


async def _get_klines(symbol: str, interval: str = "4h", limit: int = 60) -> list:
    """
    Fetch OHLCV klines with robust multi-exchange fallback:
    1. MEXC Spot (open access, standard Binance schema, works reliably on Vercel/AWS)
    2. Bybit Linear (robust fallback, converted to standard schema)
    3. Binance Spot (fallback for non-blocked environments)
    """
    global _kline_cache
    cache_key = f"{symbol}_{interval}_{limit}"
    now = time.time()
    cached = _kline_cache.get(cache_key)
    if cached and (now - cached["ts"] < KLINE_CACHE_TTL):
        return cached["data"]

    clean = symbol.replace("/", "").upper()
    client = _get_http_client()

    # Source 1: MEXC Spot
    try:
        mexc_interval = "60m" if interval in ("1h", "60m") else "4h" if interval == "4h" else "1d"
        url = f"https://api.mexc.com/api/v3/klines?symbol={clean}&interval={mexc_interval}&limit={limit}"
        res = await client.get(url, timeout=5.0)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) >= 10:
                _kline_cache[cache_key] = {"data": data, "ts": now}
                return data
    except Exception as e:
        logger.debug("MEXC %s %s failed: %s", symbol, interval, e)

    # Source 2: Bybit Linear
    try:
        bybit_interval = "60" if interval in ("1h", "60m") else "240" if interval == "4h" else "D"
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={clean}&interval={bybit_interval}&limit={limit}"
        res = await client.get(url, timeout=5.0)
        if res.status_code == 200:
            raw_list = res.json().get("result", {}).get("list", [])
            if raw_list and len(raw_list) >= 10:
                converted = []
                for row in reversed(raw_list):
                    converted.append([
                        int(row[0]),
                        str(row[1]),
                        str(row[2]),
                        str(row[3]),
                        str(row[4]),
                        str(row[5]),
                        int(row[0]) + 14399999,
                        "0", "0", "0", "0", "0"
                    ])
                _kline_cache[cache_key] = {"data": converted, "ts": now}
                return converted
    except Exception as e:
        logger.debug("Bybit %s %s failed: %s", symbol, interval, e)

    # Source 3: Binance Spot
    for binance_host in ["api.binance.com", "api1.binance.com", "api2.binance.com"]:
        try:
            url = f"https://{binance_host}/api/v3/klines?symbol={clean}&interval={interval}&limit={limit}"
            res = await client.get(url, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) >= 10:
                    _kline_cache[cache_key] = {"data": data, "ts": now}
                    return data
        except Exception as e:
            logger.debug("Binance %s %s failed: %s", symbol, interval, e)

    return []


async def _get_fear_greed() -> dict:
    """Crypto Fear & Greed Index — cached 5 minutes."""
    global _fear_greed_cache
    now = time.time()
    if now - _fear_greed_cache["ts"] < 300:
        return _fear_greed_cache
    client = _get_http_client()
    try:
        res = await client.get("https://api.alternative.me/fng/?limit=1", timeout=4.0)
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
    """Accurate MACD: EMA12 and EMA26 built incrementally."""
    if len(closes) < 26:
        return 0.0, 0.0, 0.0
    k12, k26 = 2.0 / 13, 2.0 / 27
    e12 = sum(closes[:12]) / 12
    e26 = sum(closes[:26]) / 26
    for i in range(12, 26):
        e12 = closes[i] * k12 + e12 * (1 - k12)
    macd_series = []
    for i in range(26, len(closes)):
        e12 = closes[i] * k12 + e12 * (1 - k12)
        e26 = closes[i] * k26 + e26 * (1 - k26)
        macd_series.append(e12 - e26)
    if not macd_series:
        return 0.0, 0.0, 0.0
    macd_line = macd_series[-1]
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
        return m * 1.05, m, m * 0.95, 0.5
    window = closes[-period:]
    mid = sum(window) / period
    std = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
    upper = mid + 2 * std
    lower = mid - 2 * std
    live = closes[-1]
    bb_pos = (live - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
    return upper, mid, lower, bb_pos


def _check_higher_highs(closes: list[float], side: str, lookback: int = 8) -> bool:
    """Detect higher-lows (bull swing structure) or lower-highs (bear swing structure)."""
    if len(closes) < lookback + 1:
        return False
    recent = closes[-lookback:]
    if side == "buy":
        # Check rising troughs (higher lows = bull accumulation)
        troughs = [recent[i] for i in range(1, len(recent) - 1) if recent[i] < recent[i-1] and recent[i] < recent[i+1]]
        return len(troughs) >= 2 and troughs[-1] > troughs[-2] if len(troughs) >= 2 else False
    else:
        # Check falling peaks (lower highs = bear distribution)
        peaks = [recent[i] for i in range(1, len(recent) - 1) if recent[i] > recent[i-1] and recent[i] > recent[i+1]]
        return len(peaks) >= 2 and peaks[-1] < peaks[-2] if len(peaks) >= 2 else False


# ── Aladdin Swing Trading Multi-Factor Matrix (0–107 pts) ─────────────────────

def _score_symbol_swing(
    c4h: list[float],
    o4h: list[float],
    k4h: list,
    c1d: list[float],
    k1d: list,
    side: str,
    fg_value: int,
) -> dict:
    """
    Multi-Timeframe Swing Factor Scoring (4H primary execution + 1D macro trend filter).
    Designed specifically to catch high-probability multi-day swing expansions.
    """
    live = c4h[-1]
    ema9_4h = _calc_ema(c4h, 9)
    ema21_4h = _calc_ema(c4h, 21)
    ema50_4h = _calc_ema(c4h, 50)
    rsi_4h = _calc_rsi(c4h, 14)
    macd_line, signal_line, histogram = _calc_macd(c4h)
    bb_upper, bb_mid, bb_lower, bb_pos = _calc_bollinger(c4h, 20)
    atr_4h = _calc_atr(k4h, 14)
    atr_pct_4h = (atr_4h / live) * 100 if live > 0 else 0

    # 1D Macro Trend
    ema20_1d = _calc_ema(c1d, 20) if len(c1d) >= 10 else live
    ema50_1d = _calc_ema(c1d, 50) if len(c1d) >= 20 else ema20_1d

    # Swing Momentum: 24h (6x 4h bars) and 72h (18x 4h bars)
    chg_24h = (c4h[-1] - c4h[-7]) / c4h[-7] * 100 if len(c4h) >= 7 else 0.0
    chg_72h = (c4h[-1] - c4h[-19]) / c4h[-19] * 100 if len(c4h) >= 19 else 0.0

    factors = {}

    # ── Factor 1: 4H Trend Structure (max 20 pts) ─────────────────────────────
    if side == "buy":
        if ema9_4h > ema21_4h > ema50_4h:
            f1 = 20  # Full bull swing stack
        elif ema9_4h > ema21_4h:
            f1 = 12  # Bullish cross active
        elif live > ema50_4h:
            f1 = 6
        else:
            f1 = 0
    else:
        if ema9_4h < ema21_4h < ema50_4h:
            f1 = 20  # Full bear swing stack
        elif ema9_4h < ema21_4h:
            f1 = 12  # Bearish cross active
        elif live < ema50_4h:
            f1 = 6
        else:
            f1 = 0
    factors["Trend_Stack_4H"] = f1

    # ── Factor 2: 1D Macro Confluence Filter (max 20 pts) ─────────────────────
    # Essential for swing trading: never trade against the Daily tide
    if side == "buy":
        if live > ema20_1d > ema50_1d:
            f2 = 20  # Full macro daily bull confluence
        elif live > ema20_1d:
            f2 = 12  # Above daily 20 EMA
        elif live > ema50_1d:
            f2 = 6
        else:
            f2 = 0
    else:
        if live < ema20_1d < ema50_1d:
            f2 = 20  # Full macro daily bear confluence
        elif live < ema20_1d:
            f2 = 12
        elif live < ema50_1d:
            f2 = 6
        else:
            f2 = 0
    factors["Macro_Confluence_1D"] = f2

    # ── Factor 3: Swing Value / Pullback Entry Zone (max 15 pts) ──────────────
    # Golden rule: Buy value on the dip to EMA21, do NOT chase overextended moves
    dist_ema21_pct = ((live - ema21_4h) / ema21_4h) * 100

    if side == "buy":
        if 0.0 <= dist_ema21_pct <= 2.2:
            f3 = 15  # Prime sweet spot: resting right at EMA21 support
        elif -2.0 <= dist_ema21_pct < 0.0:
            f3 = 12  # Dip between EMA21 and EMA50 (discount value)
        elif 2.2 < dist_ema21_pct <= 4.5:
            f3 = 8   # Moderate extension
        elif dist_ema21_pct > 6.0:
            f3 = 1   # Overextended pump — DO NOT CHASE
        else:
            f3 = 4
    else:
        if -2.2 <= dist_ema21_pct <= 0.0:
            f3 = 15  # Prime sweet spot: retesting EMA21 resistance from below
        elif 0.0 < dist_ema21_pct <= 2.0:
            f3 = 12  # Relief rally to EMA21/50
        elif -4.5 <= dist_ema21_pct < -2.2:
            f3 = 8
        elif dist_ema21_pct < -6.0:
            f3 = 1   # Overextended dump — DO NOT SHORT THE BOTTOM
        else:
            f3 = 4
    factors["Swing_Pullback_Value"] = f3

    # ── Factor 4: Multi-Day Momentum Alignment (max 15 pts) ───────────────────
    if side == "buy":
        f4 = 0
        if chg_24h > 0.8:
            f4 += 8
        elif chg_24h > 0.0:
            f4 += 4
        if chg_72h > 2.0:
            f4 += 7
        elif chg_72h > 0.0:
            f4 += 3
    else:
        f4 = 0
        if chg_24h < -0.8:
            f4 += 8
        elif chg_24h < 0.0:
            f4 += 4
        if chg_72h < -2.0:
            f4 += 7
        elif chg_72h < 0.0:
            f4 += 3
    factors["MultiDay_Momentum"] = min(15, f4)

    # ── Factor 5: 4H MACD Swing Cycle (max 12 pts) ────────────────────────────
    if side == "buy":
        if macd_line > signal_line and histogram > 0:
            f5 = 12  # MACD bull cross + accelerating green momentum
        elif macd_line > signal_line:
            f5 = 8
        elif histogram > 0:
            f5 = 5   # Histogram turning positive (early cycle)
        else:
            f5 = 0
    else:
        if macd_line < signal_line and histogram < 0:
            f5 = 12  # MACD bear cross + accelerating red momentum
        elif macd_line < signal_line:
            f5 = 8
        elif histogram < 0:
            f5 = 5
        else:
            f5 = 0
    factors["MACD_4H_Cycle"] = f5

    # ── Factor 6: 4H Swing RSI (max 10 pts) ───────────────────────────────────
    if side == "buy":
        if 44.0 <= rsi_4h <= 62.0:
            f6 = 10  # Optimal swing accumulation band
        elif 62.0 < rsi_4h <= 70.0:
            f6 = 6   # Bullish but getting warm
        elif 36.0 <= rsi_4h < 44.0:
            f6 = 7   # Oversold pullback in uptrend
        elif rsi_4h > 75.0:
            f6 = 0   # Severely overbought — risk of swing reversal
        else:
            f6 = 2
    else:
        if 38.0 <= rsi_4h <= 56.0:
            f6 = 10  # Optimal swing distribution band
        elif 30.0 <= rsi_4h < 38.0:
            f6 = 6
        elif 56.0 < rsi_4h <= 64.0:
            f6 = 7   # Relief rally in downtrend
        elif rsi_4h < 25.0:
            f6 = 0   # Severely oversold — risk of short squeeze
        else:
            f6 = 2
    factors["RSI_4H_Swing"] = f6

    # ── Factor 7: 4H Market Structure / Pivots (max 10 pts) ───────────────────
    hh_ll = _check_higher_highs(c4h, side, lookback=8)
    f7 = 10 if hh_ll else 0
    factors["Structure_HigherLows"] = f7

    # ── Factor 8: Macro Fear & Greed (max 5 pts) ──────────────────────────────
    if side == "buy":
        if 35 <= fg_value <= 75:
            f8 = 5
        elif fg_value > 75:
            f8 = 2   # High greed caution
        else:
            f8 = 3
    else:
        if 25 <= fg_value <= 65:
            f8 = 5
        elif fg_value < 25:
            f8 = 2   # High fear caution
        else:
            f8 = 3
    factors["FearGreed_Macro"] = f8

    total = sum(factors.values())

    return {
        "score": total,
        "factors": factors,
        "ema9_4h": ema9_4h, "ema21_4h": ema21_4h, "ema50_4h": ema50_4h,
        "ema20_1d": ema20_1d, "ema50_1d": ema50_1d,
        "rsi_4h": rsi_4h,
        "macd_line": macd_line, "signal_line": signal_line, "histogram": histogram,
        "atr_pct_4h": atr_pct_4h,
        "chg_24h": chg_24h, "chg_72h": chg_72h,
        "dist_ema21_pct": dist_ema21_pct,
        "fg_value": fg_value,
    }


def _get_swing_tp_sl(atr_pct_4h: float, score: int) -> tuple[float, float]:
    """
    Institutional Swing TP/SL Targets:
      - Take Profit: 3.5% to 8.5% price target (based on 2.4x 4H ATR)
      - Stop Loss:   1.8% to 3.5% stop buffer (based on 1.0x 4H ATR)
      - Guaranteed Risk:Reward Ratio >= 2.0x (typically 2.2x - 2.8x)
    """
    # Base ATR multiplier
    tp_mult = 2.4 if score >= 80 else 2.2
    sl_mult = 1.0

    tp_pct = max(3.5, min(8.5, atr_pct_4h * tp_mult))
    sl_pct = max(1.8, min(3.5, atr_pct_4h * sl_mult))

    # Enforce minimum 2.0x R:R
    if tp_pct < sl_pct * 2.0:
        tp_pct = round(sl_pct * 2.1, 2)

    return round(tp_pct, 2), round(sl_pct, 2)


def _get_symbol_bucket(symbol: str) -> str:
    for bucket, syms in CORRELATION_BUCKETS.items():
        if symbol in syms:
            return bucket
    return "B"


async def _analyze_symbol_swing(symbol: str, fg_value: int) -> dict | None:
    """
    Analyze symbol for institutional swing trade entry using 4H and 1D data.
    """
    try:
        k4h = await _get_klines(symbol, "4h", 60)
        k1d = await _get_klines(symbol, "1d", 30)
        if len(k4h) < 25 or len(k1d) < 10:
            return None

        c4h = [float(k[4]) for k in k4h]
        o4h = [float(k[1]) for k in k4h]
        c1d = [float(k[4]) for k in k1d]
        live_price = c4h[-1]

        # Score both swing directions
        bull = _score_symbol_swing(c4h, o4h, k4h, c1d, k1d, "buy", fg_value)
        bear = _score_symbol_swing(c4h, o4h, k4h, c1d, k1d, "sell", fg_value)

        # Require minimum swing conviction (60/107)
        if bull["score"] >= bear["score"] and bull["score"] >= BASE_MIN_SWING_SCORE:
            chosen = bull
            side = "buy"
            regime = "BULL_SWING_4H"
        elif bear["score"] > bull["score"] and bear["score"] >= BASE_MIN_SWING_SCORE:
            chosen = bear
            side = "sell"
            regime = "BEAR_SWING_4H"
        else:
            return None

        score = chosen["score"]
        atr_pct = chosen["atr_pct_4h"]
        tp_pct, sl_pct = _get_swing_tp_sl(atr_pct, score)
        rr = round(tp_pct / sl_pct, 2)
        confidence = round(min(0.95, 0.60 + score / 200), 2)

        evidence = [
            f"{symbol}: Aladdin Swing Score {score}/107 ({side.upper()}) | Mode: Swing Trader",
            f"{symbol}: 4H EMA Stack {round(chosen['ema9_4h'],1)}/{round(chosen['ema21_4h'],1)}/{round(chosen['ema50_4h'],1)} | 1D EMA20 {round(chosen['ema20_1d'],1)}",
            f"{symbol}: Pullback Gap {chosen['dist_ema21_pct']:+.2f}% | 4H RSI {round(chosen['rsi_4h'],1)} | MACD {round(chosen['macd_line'],2)}",
            f"{symbol}: 24h{chosen['chg_24h']:+.2f}% 72h{chosen['chg_72h']:+.2f}% | 4H ATR {atr_pct:.2f}%",
            f"{symbol}: Swing TP +{tp_pct:.2f}% | SL -{sl_pct:.2f}% | R:R = {rr}x | Conf = {confidence}",
        ]

        return {
            "symbol": symbol, "side": side, "live_price": live_price,
            "regime": regime, "confidence": confidence, "evidence": evidence,
            "tp_pct": tp_pct, "sl_pct": sl_pct, "rr_ratio": rr,
            "score": score,
            "bull_score": bull["score"], "bear_score": bear["score"],
            "factors": chosen["factors"], "atr_pct": atr_pct,
        }
    except Exception as e:
        logger.debug("Swing analysis error for %s: %s", symbol, e)
        return None


@router.post("/tick")
@router.get("/tick")
async def run_scan_tick(request: Request):
    """Aladdin v6 Swing Trading Engine — execution cycle."""
    import time as _time

    portfolio = request.app.state.portfolio
    emergency = request.app.state.emergency
    event_bus = request.app.state.event_bus

    now = _time.time()
    if now - _scan_state["last_scan"] < 10:
        return {"status": "throttled", "message": "Scan runs every 10s"}
    _scan_state["last_scan"] = now

    # ── Pre-warm ALL 4H and 1D klines in parallel (fast ~1.5s total) ──────────
    prefetch_tasks = []
    for s in SYMBOLS:
        prefetch_tasks.append(_get_klines(s, "4h", 60))
        prefetch_tasks.append(_get_klines(s, "1d", 30))
    await asyncio.gather(*prefetch_tasks, return_exceptions=True)

    klines_ok = [s for s in SYMBOLS if len(_kline_cache.get(f"{s}_4h_60", {}).get("data", [])) >= 10]
    klines_failed = [s for s in SYMBOLS if s not in klines_ok]

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
    # In swing trading, allow normal breathing room: halt new entries if open loss exceeds -$18
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
    portfolio_heat_ok = unrealized_pnl > -18.0

    # ── 2. Monitor Open Positions (3-Stage Swing Trailing Ratchet) ─────────────
    for sym, qty in list(portfolio.positions.items()):
        if qty == 0:
            continue
        try:
            live_p = await get_live_price(sym)
        except Exception:
            continue

        entry_p = portfolio._entry_prices.get(sym, live_p)
        stored = portfolio._entry_tp_sl.get(sym, (4.5, 2.2))
        tp_threshold = stored[0] / 100.0   # e.g. 0.045 (4.5%)
        sl_threshold = stored[1] / 100.0   # e.g. 0.022 (2.2%)

        diff = (live_p - entry_p) / entry_p if qty > 0 else (entry_p - live_p) / entry_p
        realized_pnl = margin * leverage * diff
        pnl_pct = (realized_pnl / margin) * 100

        # Swing Trailing Ratchet:
        # Stage 1: Profit reaches +2.0% (or 45% of TP) -> Move SL to Breakeven +0.2%
        # Stage 2: Profit reaches +4.0% (or 70% of TP) -> Trail SL to lock in 50% of gain
        # Stage 3: Profit reaches 85% of TP           -> Trail SL to lock in 75% of gain
        trail_level = portfolio._trailing_state.get(sym, 0)

        if diff >= tp_threshold * 0.85 and trail_level < 3:
            sl_threshold = -(diff * 0.75)  # Lock in 75% of peak profit
            portfolio._trailing_state[sym] = 3
            actions_taken.append(f"SWING_TRAIL3 {sym}: Locked 75% gain (SL at +{abs(sl_threshold)*100:.2f}%)")
        elif (diff >= tp_threshold * 0.70 or diff >= 0.040) and trail_level < 2:
            sl_threshold = -(diff * 0.50)  # Lock in 50% of peak profit
            portfolio._trailing_state[sym] = 2
            actions_taken.append(f"SWING_TRAIL2 {sym}: Locked 50% gain (SL at +{abs(sl_threshold)*100:.2f}%)")
        elif (diff >= tp_threshold * 0.45 or diff >= 0.020) and trail_level < 1:
            sl_threshold = -0.002          # Breakeven + 0.2% buffer
            portfolio._trailing_state[sym] = 1
            actions_taken.append(f"SWING_TRAIL1 {sym}: SL moved to Breakeven (+0.2%) — trade is now RISK-FREE")

        closed_reason = None
        if diff >= tp_threshold:
            closed_reason = f"Aladdin Swing TakeProfit (+{diff*100:.2f}%)"
        elif sl_threshold < 0 and diff <= abs(sl_threshold):
            # Trailed stop triggered in profit
            closed_reason = f"Aladdin Swing Trailing Profit (+{diff*100:.2f}%)"
        elif sl_threshold > 0 and diff <= -sl_threshold:
            closed_reason = f"Aladdin Swing StopLoss ({diff*100:.2f}%)"

        if closed_reason:
            portfolio.positions[sym] = 0
            portfolio.realized_pnl += realized_pnl
            portfolio._trailing_state.pop(sym, None)
            portfolio._entry_tp_sl.pop(sym, None)
            sl_p = entry_p * (1 - abs(sl_threshold)) if qty > 0 else entry_p * (1 + abs(sl_threshold))
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
            logger.info("Aladdin Swing closed %s | %s | PnL $%.2f", sym, closed_reason, realized_pnl)

    # ── 3. Open New Swing Positions ───────────────────────────────────────────
    active_count = sum(1 for q in portfolio.positions.values() if q != 0)
    if active_count < 3 and portfolio_heat_ok:
        available = [s for s in SYMBOLS if portfolio.positions.get(s, 0) == 0]
        start = _scan_state["index"] % max(len(available), 1)
        ordered = available[start:] + available[:start]
        _scan_state["index"] += 1

        for symbol in ordered:
            if sum(1 for q in portfolio.positions.values() if q != 0) >= 3:
                break

            # Correlation guard: max 1 per bucket
            bucket = _get_symbol_bucket(symbol)
            bucket_held = sum(1 for s in CORRELATION_BUCKETS.get(bucket, [])
                              if portfolio.positions.get(s, 0) != 0)
            if bucket_held >= MAX_PER_BUCKET.get(bucket, 1):
                actions_taken.append(f"CORR_GUARD {symbol}: Bucket {bucket} full ({bucket_held}/{MAX_PER_BUCKET[bucket]})")
                continue

            signal = await _analyze_symbol_swing(symbol, fg_value)
            if signal is None:
                # Quick debug scores
                score_info = ""
                try:
                    k4 = _kline_cache.get(f"{symbol}_4h_60", {}).get("data", [])
                    k1 = _kline_cache.get(f"{symbol}_1d_30", {}).get("data", [])
                    if k4 and k1:
                        c4 = [float(x[4]) for x in k4]
                        o4 = [float(x[1]) for x in k4]
                        c1 = [float(x[4]) for x in k1]
                        b = _score_symbol_swing(c4, o4, k4, c1, k1, "buy", fg_value)
                        br = _score_symbol_swing(c4, o4, k4, c1, k1, "sell", fg_value)
                        score_info = f" [Bull={b['score']} Bear={br['score']} Min={BASE_MIN_SWING_SCORE}]"
                except Exception:
                    pass
                actions_taken.append(f"SKIPPED {symbol}: score below swing threshold{score_info}")
                continue

            side = signal["side"]
            live_price = signal["live_price"]
            score = signal["score"]
            tp_pct = signal["tp_pct"]
            sl_pct = signal["sl_pct"]

            # Dynamic Sizing for Swings:
            # Score >= 85: $650 notional
            # Score 75-84: $500 notional
            # Score 60-74: $400 notional
            if score >= 85:
                notional = 650.0
            elif score >= 75:
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
                f"OPENED SWING {side.upper()} {symbol} @ ${live_price:,.2f} | "
                f"Score={score}/107 | Swing TP+{tp_pct:.2f}% SL-{sl_pct:.2f}% RR={signal['rr_ratio']}x | "
                f"Notional=${notional:.0f} | F&G={fg_value}({fg_label})"
            )
            logger.info("Aladdin Swing opened %s %s @ $%.2f | score=%d | tp=%.2f%% sl=%.2f%%",
                        side.upper(), symbol, live_price, score, tp_pct, sl_pct)

    try:
        from crypto_trading_desk.core.state import save_state
        save_state(portfolio)
    except Exception:
        pass

    return {
        "status": "scanned",
        "engine": "Aladdin_v6_SwingTrader",
        "timeframes": "4H Primary / 1D Macro Confluence",
        "actions": actions_taken,
        "active_positions": sum(1 for q in portfolio.positions.values() if q != 0),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "fear_greed": {"value": fg_value, "label": fg_label},
        "min_score_bar": BASE_MIN_SWING_SCORE,
        "klines_ok": len(klines_ok),
        "klines_failed": klines_failed,
    }
