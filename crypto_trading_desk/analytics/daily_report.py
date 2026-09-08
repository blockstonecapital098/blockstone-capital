"""
DailyReportGenerator produces a summary of the day's trading activity.

It aggregates trade post‑mortems and agent performance stats into a human‑readable
report that can be sent via the AlertManager (email, Telegram, etc.).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List

from crypto_trading_desk.analytics.agent_tracker import AgentPerformanceTracker
from crypto_trading_desk.analytics.trade_postmortem import TradePostMortemGenerator, PostMortem

logger = logging.getLogger(__name__)


class DailyReportGenerator:
    """Generates a markdown daily report."""

    def __init__(self, tracker: AgentPerformanceTracker, postmortem_gen: TradePostMortemGenerator):
        self.tracker = tracker
        self.postmortem_gen = postmortem_gen

    def generate(self, report_date: date | None = None) -> str:
        report_date = report_date or date.today()
        records: List[PostMortem] = [
            r for r in self.postmortem_gen.all_records()
            if r.exit_time.date() == report_date
        ]
        total_trades = len(records)
        total_pnl = sum(r.pnl for r in records)
        winners = [r for r in records if r.pnl > 0]
        losers = [r for r in records if r.pnl <= 0]
        agent_summary = self.tracker.summary()

        lines = [
            f"# Daily Trading Report – {report_date}",
            "",
            "## Summary",
            f"- **Total Trades**: {total_trades}",
            f"- **Total P&L**: ${total_pnl:,.2f}",
            f"- **Winning Trades**: {len(winners)}",
            f"- **Losing Trades**: {len(losers)}",
            f"- **Win Rate**: {(len(winners)/total_trades*100 if total_trades else 0):.1f}%",
            "",
            "## Trade Log",
        ]
        for r in records:
            lines.append(
                f"- `{r.trade_id[:8]}` {r.side.upper()} {r.symbol} "
                f"qty={r.quantity} pnl=${r.pnl:+.2f} ({r.pnl_pct*100:+.2f}%)"
            )

        lines += [
            "",
            "## Agent Performance",
            "| Agent | Signals | Hit Rate | P&L |",
            "|-------|---------|----------|-----|",
        ]
        for s in agent_summary:
            lines.append(
                f"| {s['agent_id']} | {s['total_signals']} | "
                f"{s['hit_rate']*100:.1f}% | ${s['total_pnl']:+,.2f} |"
            )

        lines += ["", f"*Report generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC*"]
        report = "\n".join(lines)
        logger.info("DailyReportGenerator: report generated for %s (%d trades)", report_date, total_trades)
        return report
