# TradingEngineer — Operator Runbook

Paperclip agent for the CMTG Agentic Trading System.

## What This Agent Does

Monitors the autonomous trading engine on ThinkPad P70, reviews journal performance, analyzes policy intelligence signals, and manages the wheel strategy pipeline.

| Routine | Schedule | Output |
|---------|----------|--------|
| Daily Strategy Health | Weekdays 7am | Engine status + position check |
| Weekly Performance Review | Monday 9am | P&L + signal attribution |
| Policy Signal Analysis | Manual | Sector + ticker analysis |

## Hire

```bash
COMPANY=ed43b902-3d91-476a-b0d0-24f629951a1d
curl -s -X POST "http://127.0.0.1:3100/api/companies/$COMPANY/agents" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "TradingEngineer",
    "role": "engineer",
    "description": "Agentic trading system operations — wheel strategy monitoring, policy intelligence analysis, Alpaca Markets paper trading, trade journal review",
    "adapterType": "claude_local",
    "projectId": "91c4859c-741b-4318-9026-0106716f8489"
  }'
```

## CRITICAL

This agent operates on PAPER TRADING only. Never switch to live mode without explicit written confirmation from Chris Marsh.

## Key Skill

`/home/stacksbyc/projects/.skills-db/stock-trading-advisor.skill` — wheel strategy, CSP/CC mechanics, congressional trade analysis
