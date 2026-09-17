"""
State persistence module — saves and loads portfolio state across server restarts.

On Vercel (serverless), instances are ephemeral and /tmp is wiped on cold starts.
This module persists state with a built-in master ledger (master_trades.json)
so that historical trades across all dates (Sep 02, 09, 11, 14, 16) are permanently
preserved, merged with any newly closed live trades, and never wiped on cold starts.
"""
from __future__ import annotations
import json
import logging
import os
import base64
import urllib.request
import urllib.error
from typing import Any

logger = logging.getLogger(__name__)

# ── Local /tmp cache path ─────────────────────────────────────────────────────
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    STATE_FILE = "/tmp/portfolio_state.json"
else:
    STATE_FILE = os.path.join(os.getcwd(), "portfolio_state.json")

# ── GitHub repo persistence (if GITHUB_TOKEN configured) ──────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "blockstonecapital098/blockstone-capital"
STATE_PATH = "api/state_data.json"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATE_PATH}"


def _get_master_trades() -> list:
    """Load permanent baseline historical trades."""
    try:
        from crypto_trading_desk.core.master_trades import MASTER_CLOSED_TRADES
        return list(MASTER_CLOSED_TRADES)
    except Exception as exc:
        logger.warning("Could not load master_trades module: %s", exc)
    return []



def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "blockstone-capital-bot",
    }


def _github_load() -> dict | None:
    """Fetch portfolio state from GitHub repo file."""
    if not GITHUB_TOKEN:
        return None
    try:
        req = urllib.request.Request(GITHUB_API, headers=_gh_headers())
        resp = urllib.request.urlopen(req, timeout=8)
        gh_data = json.loads(resp.read())
        content = base64.b64decode(gh_data["content"]).decode("utf-8")
        data = json.loads(content)
        logger.info("Portfolio state loaded from GitHub repo.")
        return data
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.info("No GitHub state file yet — starting fresh.")
        else:
            logger.warning("GitHub load failed (HTTP %s): %s", exc.code, exc)
        return None
    except Exception as exc:
        logger.warning("GitHub load failed: %s", exc)
        return None


def _github_save(data: dict) -> bool:
    """Persist portfolio state to GitHub repo file (create or update)."""
    if not GITHUB_TOKEN:
        return False
    try:
        content_b64 = base64.b64encode(
            json.dumps(data, indent=2).encode("utf-8")
        ).decode("utf-8")

        sha = None
        try:
            req = urllib.request.Request(GITHUB_API, headers=_gh_headers())
            resp = urllib.request.urlopen(req, timeout=5)
            sha = json.loads(resp.read()).get("sha")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

        payload_dict = {
            "message": "chore: auto-save portfolio state",
            "content": content_b64,
            "branch": "main",
        }
        if sha:
            payload_dict["sha"] = sha

        payload = json.dumps(payload_dict).encode("utf-8")
        req = urllib.request.Request(
            GITHUB_API,
            data=payload,
            method="PUT",
            headers={**_gh_headers(), "Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=8)
        logger.info("Portfolio state saved to GitHub repo.")
        return True
    except Exception as exc:
        logger.warning("GitHub save failed: %s", exc)
        return False


def _merge_trades(base_trades: list, new_trades: list) -> list:
    """Merge two trade lists by trade_id, preserving all history."""
    trade_map = {}
    for t in base_trades:
        key = t.get("trade_id") or (t.get("closed_at", "") + t.get("symbol", ""))
        if key:
            trade_map[key] = t
    for t in new_trades:
        key = t.get("trade_id") or (t.get("closed_at", "") + t.get("symbol", ""))
        if key:
            trade_map[key] = t
    return list(trade_map.values())


def save_state(portfolio: Any) -> None:
    """Serializes portfolio state — preserves all master trades + live trades."""
    try:
        master_trades = _get_master_trades()
        current_closed = getattr(portfolio, "closed_trades", [])
        all_closed = _merge_trades(master_trades, current_closed)

        data = {
            "realized_pnl": getattr(portfolio, "realized_pnl", 0.0),
            "positions": getattr(portfolio, "positions", {}),
            "total_exposure": getattr(portfolio, "total_exposure", 0.0),
            "entry_prices": getattr(portfolio, "_entry_prices", {}),
            "closed_trades": all_closed,
        }
        # Write /tmp cache
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        # Push to GitHub if token available
        _github_save(data)
        logger.debug("Portfolio state saved.")
    except Exception as exc:
        logger.error("Failed to save portfolio state: %s", exc)


def load_state(portfolio: Any) -> None:
    """Restores portfolio state — always initializes with permanent master history."""
    master_trades = _get_master_trades()
    data = _github_load()

    if data is None and os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Portfolio state loaded from /tmp cache.")
        except Exception as exc:
            logger.error("Failed to load /tmp state: %s", exc)

    # Initialize attributes if missing
    if not hasattr(portfolio, "realized_pnl"):
        portfolio.realized_pnl = 0.0
    if not hasattr(portfolio, "positions"):
        portfolio.positions = {}
    if not hasattr(portfolio, "total_exposure"):
        portfolio.total_exposure = 0.0
    if not hasattr(portfolio, "_entry_prices"):
        portfolio._entry_prices = {}
    if not hasattr(portfolio, "closed_trades"):
        portfolio.closed_trades = []

    if data:
        portfolio.realized_pnl = data.get("realized_pnl", portfolio.realized_pnl)
        portfolio.positions = data.get("positions", portfolio.positions)
        portfolio.total_exposure = data.get("total_exposure", portfolio.total_exposure)
        portfolio._entry_prices = data.get("entry_prices", portfolio._entry_prices)
        loaded_closed = data.get("closed_trades", [])
        portfolio.closed_trades = _merge_trades(master_trades, loaded_closed)
    else:
        # First cold start: seed with complete master history
        portfolio.closed_trades = list(master_trades)

    logger.info("Portfolio restored with %d closed trades.", len(portfolio.closed_trades))
