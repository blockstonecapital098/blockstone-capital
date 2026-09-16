# Blockstone Capital — AI Trading Bot Project Rules

## Execution Policy: Always Proceed

- **Never stop to ask for approval** before running terminal commands, editing files, committing, or pushing to GitHub/Vercel.
- **Always proceed immediately** with all tool calls — command execution, file edits, git commits, git push, API calls — without requesting user review or confirmation.
- Do NOT create implementation plans or ask for plan approval for routine coding tasks. Just execute.
- Do NOT pause for artifact review. Create and update artifacts silently and continue working.
- After completing any task, report results directly in chat — don't stop mid-task to ask permission to continue.

## Project Context

- **Live Site:** https://blockstone-capital.vercel.app
- **GitHub Repo:** blockstonecapital098/blockstone-capital (main branch)
- **Local Workspace:** C:\Users\Asif Bacha\Downloads\Antigravity AI BOT
- **Git PATH fix (PowerShell):** Always prepend `$env:PATH += ";C:\Program Files\Git\cmd"` before git commands
- **Cron Job:** cron-job.org pings /api/scan/tick every 1 minute
- **Stack:** FastAPI + Vercel serverless + Binance live data

## Trading Bot Rules

- Keep 10x leverage and $50 margin ($500 notional) per position intact
- Max 3 simultaneous positions
- TP at +0.4% move, SL at -0.3% move
- Bidirectional: SHORT when 24h change ≤ -1.5%, LONG when ≥ +1.5%, alternating in sideways market
- PKT timezone (Pakistan Standard Time, UTC+5) for all timestamps
- After any code change: always regenerate template.py from dashboard.html using regen_template.py, then commit and push both files
