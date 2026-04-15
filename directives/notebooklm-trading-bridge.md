# NotebookLM → Trading Intelligence Bridge

**Problem:** Research insights trapped in NotebookLM can't flow into the live trading decision pipeline  
**Solution:** Webhook-triggered workflow that accepts pasted research briefs, scores them with Claude, and lands structured signals in Supabase  
**Trigger:** Webhook (POST) + optional Schedule Trigger for Google Docs polling  
**Est. Build Time:** ~5.5 hours

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    RESEARCH INTAKE LAYER                     │
│                                                             │
│  [NotebookLM]──export──▶[Google Doc]──poll──▶[n8n Trigger]  │
│       │                                                     │
│       └──copy/paste──▶[Webhook POST]──▶[n8n Trigger]        │
│                                                             │
│  Two intake paths: automated (Docs poll) + manual (webhook) │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  INTELLIGENCE SCORING LAYER                  │
│                                                             │
│  [Normalize Input]                                          │
│       │                                                     │
│       ▼                                                     │
│  [Claude API — Signal Extractor]                            │
│       │  Extracts: tickers, thesis, sentiment, catalysts,   │
│       │  risk factors, congressional refs, sector tags       │
│       ▼                                                     │
│  [Claude API — Conviction Scorer]                           │
│       │  Scores each signal 1-10 using your framework       │
│       │  Flags wheel-eligible candidates                     │
│       ▼                                                     │
│  [Code Node — Merge & Validate]                             │
│       │  Deduplicates against existing signals in Supabase   │
│       │  Validates required fields, rejects garbage          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    PERSISTENCE LAYER                         │
│                                                             │
│  [Supabase UPSERT — trading_signals]                        │
│       │                                                     │
│       ├──▶ [Supabase UPSERT — research_briefs] (raw archive)│
│       │                                                     │
│       └──▶ [Supabase INSERT — workflow_runs] (audit log)    │
│                                                             │
│  [Splunk HEC — optional event forward]                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    ALERT LAYER                               │
│                                                             │
│  [IF: conviction ≥ 7]──▶[Slack/SMS alert: "High-conviction  │
│                           signal from NotebookLM research"]  │
│                                                             │
│  [Respond to Webhook — confirmation payload]                │
└─────────────────────────────────────────────────────────────┘
```

---

## Node Sequence

### Path A: Manual Webhook (Primary — fastest to build)

| # | Node Name | Type | Purpose | Key Config |
|---|-----------|------|---------|------------|
| 1 | **Research Intake** | Webhook | Accept pasted research brief | POST `/trading/research-intake`, Header Auth `X-Webhook-Secret`, Response: Last Node |
| 2 | **Validate Payload** | IF | Reject empty or malformed input | `{{ $json.body.content.length > 50 }}` |
| 3 | **Normalize Input** | Code | Strip markdown artifacts, normalize whitespace, extract metadata | See code below |
| 4 | **Extract Signals** | HTTP Request (Claude API) | Pull structured trading signals from unstructured research | POST `api.anthropic.com/v1/messages` |
| 5 | **Parse Extraction** | Code | Safe JSON parse of Claude response | Standard parse pattern |
| 6 | **Score Signals** | HTTP Request (Claude API) | Apply Signal Strength framework + wheel eligibility check | POST `api.anthropic.com/v1/messages` |
| 7 | **Parse Scoring** | Code | Safe JSON parse + merge with extraction | Standard parse pattern |
| 8 | **Dedup Check** | HTTP Request (Supabase) | GET existing signals for same tickers in last 7 days | GET `/rest/v1/trading_signals?ticker=in.(...)` |
| 9 | **Merge & Validate** | Code | Deduplicate, validate required fields, flag updates vs inserts | See code below |
| 10 | **Upsert Signals** | HTTP Request (Supabase) | Write scored signals to `trading_signals` | POST `/rest/v1/trading_signals` with `Prefer: resolution=merge-duplicates` |
| 11 | **Archive Brief** | HTTP Request (Supabase) | Store raw research text in `research_briefs` | POST `/rest/v1/research_briefs` |
| 12 | **Log Run** | HTTP Request (Supabase) | Audit trail in `workflow_runs` | POST `/rest/v1/workflow_runs` |
| 13 | **High Conviction Alert** | IF → Slack/SMS | Alert if any signal scores ≥ 7 | `{{ $json.signals.some(s => s.conviction >= 7) }}` |
| 14 | **Respond** | Respond to Webhook | Return processed signal summary | JSON payload with signal count + top tickers |

### Path B: Google Docs Poll (Automated — for NotebookLM exports)

| # | Node Name | Type | Purpose | Key Config |
|---|-----------|------|---------|------------|
| 1 | **Poll Trigger** | Schedule Trigger | Check for new research docs | Every 4 hours, 9am-9pm market days |
| 2 | **Fetch Doc** | Google Docs (Get) | Pull latest doc from designated research folder | Folder ID parameterized |
| 3 | **Check Modified** | IF | Skip if doc hasn't changed since last poll | Compare `modifiedTime` vs last stored timestamp |
| 4 | **→ Merge into Path A at Node 3** | — | Same pipeline from Normalize onward | — |

---

## Claude Integration

### Node 4: Signal Extractor — System Prompt

```
You are a trading signal extraction engine for a wheel strategy (cash-secured puts, covered calls) portfolio.

Given a research brief from NotebookLM, extract every actionable trading signal.

For each signal found, output:
- ticker: stock symbol (uppercase)
- direction: "bullish" | "bearish" | "neutral"
- thesis: one-sentence rationale (max 100 chars)
- source_type: "congressional" | "flow" | "fundamental" | "technical" | "macro" | "catalyst"
- catalysts: array of upcoming events relevant to this signal
- risk_factors: array of risk items
- sector: GICS sector name
- congressional_refs: array of politician names if any congressional trading mentioned
- timeframe: "short" (< 30d) | "medium" (30-90d) | "long" (> 90d)

Respond ONLY with valid JSON. No markdown, no explanation.
Format: { "signals": [ { ... }, { ... } ] }

If no actionable signals found, return: { "signals": [] }
```

**Input construction:**
```
{{ "Research brief content:\n\n" + $json.normalized_content + "\n\nDate context: " + $now.format('YYYY-MM-DD') }}
```

**Output parsing (Node 5):**
```javascript
const raw = $input.first().json.content[0].text;
try {
  const parsed = JSON.parse(raw.replace(/```json|```/g, '').trim());
  return [{ json: parsed }];
} catch(e) {
  return [{ json: { error: 'parse_failed', raw, signals: [] } }];
}
```

### Node 6: Conviction Scorer — System Prompt

```
You are a trading conviction scorer for a wheel strategy portfolio.

Score each signal using this exact framework:

Signal Strength Score (1-10):
+3  Committee member trading in their committee's sector
+2  Trade size > $100K or major institutional flow
+2  Multiple independent sources confirming same thesis
+1  Party-line consensus (bipartisan buying)
+1  Trade made before known catalyst
+1  Stock is in S&P 500 (liquid)
+1  IV Rank likely > 30 (good premium environment)
-2  Stale data (> 30 days old)
-1  Single unconfirmed source
-1  Earnings within 14 days (assignment risk)

For each signal, also assess:
- wheel_eligible: true/false (liquid options, large cap, fundamentally sound)
- suggested_strategy: "CSP" | "CC" | "watch" | "avoid"
- premium_environment: "rich" | "fair" | "thin" (based on sector IV context)

Respond ONLY with valid JSON.
Format: { "scored_signals": [ { ...original_signal_fields, "conviction": N, "wheel_eligible": bool, "suggested_strategy": "...", "premium_environment": "..." } ] }
```

**Input construction:**
```
{{ "Signals to score:\n" + JSON.stringify($json.signals) }}
```

---

## Supabase Schema

```sql
-- Core signal table: your trading intelligence feed
CREATE TABLE trading_signals (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  ticker VARCHAR(10) NOT NULL,
  direction VARCHAR(10) NOT NULL CHECK (direction IN ('bullish','bearish','neutral')),
  thesis TEXT NOT NULL,
  source_type VARCHAR(20) NOT NULL,
  catalysts JSONB DEFAULT '[]',
  risk_factors JSONB DEFAULT '[]',
  sector VARCHAR(50),
  congressional_refs JSONB DEFAULT '[]',
  timeframe VARCHAR(10),
  conviction INT NOT NULL CHECK (conviction BETWEEN 1 AND 10),
  wheel_eligible BOOLEAN DEFAULT false,
  suggested_strategy VARCHAR(10),
  premium_environment VARCHAR(10),
  source_brief_id UUID REFERENCES research_briefs(id),
  status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active','acted','expired','dismissed')),
  acted_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(ticker, thesis, created_at::date)  -- deduplicate same-day same-thesis
);

-- Index for fast lookups
CREATE INDEX idx_signals_ticker ON trading_signals(ticker);
CREATE INDEX idx_signals_conviction ON trading_signals(conviction DESC);
CREATE INDEX idx_signals_status ON trading_signals(status);

-- Raw research archive
CREATE TABLE research_briefs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  content TEXT NOT NULL,
  source VARCHAR(50) DEFAULT 'notebooklm',
  signal_count INT DEFAULT 0,
  top_conviction INT DEFAULT 0,
  tickers_mentioned JSONB DEFAULT '[]',
  processed_at TIMESTAMPTZ DEFAULT now(),
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Workflow audit log
CREATE TABLE workflow_runs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workflow_name VARCHAR(100) NOT NULL,
  status VARCHAR(20) NOT NULL CHECK (status IN ('success','error','partial')),
  input_hash VARCHAR(64),
  signals_extracted INT DEFAULT 0,
  signals_upserted INT DEFAULT 0,
  error_message TEXT,
  duration_ms INT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- RLS policies (service key bypasses, but good practice)
ALTER TABLE trading_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE research_briefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY;

-- View: active high-conviction signals for dashboard
CREATE VIEW v_hot_signals AS
SELECT 
  ticker, direction, thesis, conviction, 
  suggested_strategy, premium_environment,
  sector, catalysts, risk_factors,
  created_at
FROM trading_signals
WHERE status = 'active' 
  AND conviction >= 6
  AND created_at > now() - interval '14 days'
ORDER BY conviction DESC, created_at DESC;

-- View: research intake stats
CREATE VIEW v_research_stats AS
SELECT 
  date_trunc('week', created_at) AS week,
  COUNT(*) AS briefs_processed,
  SUM(signal_count) AS total_signals,
  AVG(top_conviction) AS avg_top_conviction
FROM research_briefs
GROUP BY 1
ORDER BY 1 DESC;
```

---

## Key Code Nodes

### Node 3: Normalize Input

```javascript
const body = $input.first().json.body;
const content = body.content || body.text || body.research || '';

// Strip common NotebookLM / Google Docs artifacts
const normalized = content
  .replace(/\[?\d+\]?/g, '')           // footnote markers
  .replace(/Source:?\s*\d+/gi, '')      // source refs
  .replace(/\n{3,}/g, '\n\n')          // excessive newlines
  .replace(/^\s+|\s+$/gm, '')          // trim lines
  .trim();

return [{
  json: {
    normalized_content: normalized,
    char_count: normalized.length,
    intake_timestamp: new Date().toISOString(),
    source: body.source || 'notebooklm_manual'
  }
}];
```

### Node 9: Merge & Validate

```javascript
const scored = $('Parse Scoring').first().json.scored_signals || [];
const existing = $('Dedup Check').first().json || [];
const existingTickers = new Set(existing.map(e => e.ticker + '|' + e.thesis));

const validated = scored
  .filter(s => {
    // Required fields check
    if (!s.ticker || !s.direction || !s.thesis || !s.conviction) return false;
    if (s.conviction < 1 || s.conviction > 10) return false;
    return true;
  })
  .map(s => ({
    ...s,
    is_update: existingTickers.has(s.ticker + '|' + s.thesis),
    ticker: s.ticker.toUpperCase().trim()
  }));

return [{
  json: {
    signals: validated,
    total: validated.length,
    new_count: validated.filter(s => !s.is_update).length,
    update_count: validated.filter(s => s.is_update).length,
    high_conviction: validated.filter(s => s.conviction >= 7)
  }
}];
```

---

## Environment Variables

| Variable | Source | Required |
|----------|--------|----------|
| `CLAUDE_API_KEY` | console.anthropic.com | yes |
| `SUPABASE_URL` | Supabase project settings | yes |
| `SUPABASE_ANON_KEY` | Supabase project settings | yes |
| `SUPABASE_SERVICE_KEY` | Supabase project settings | yes |
| `WEBHOOK_SECRET` | Self-generated (openssl rand -hex 32) | yes |
| `SLACK_WEBHOOK_URL` | Slack app → Incoming Webhooks | optional |
| `GOOGLE_DOCS_FOLDER_ID` | Google Drive folder for NotebookLM exports | optional (Path B) |
| `SPLUNK_HEC_TOKEN` | Splunk HEC settings (port 8088) | optional |
| `SPLUNK_HEC_URL` | `https://localhost:8088/services/collector/event` | optional |

---

## Error Handling

```
[Nodes 4,6] Claude API errors
  └──▶ IF statusCode >= 400 or content[0].text undefined
       ├── yes → Set { error: "claude_api_failure", node: "extract|score" }
       │         → Supabase INSERT workflow_runs (status: 'error')
       │         → Slack alert: "⚠️ Trading research pipeline — Claude API failed"
       │         → Respond to Webhook: 500 + error message
       └── no  → Continue

[Node 10] Supabase write errors
  └──▶ IF statusCode >= 400
       ├── yes → Log error, Slack alert, respond 500
       └── no  → Continue to archive + audit log
```

---

## Build Order (Optimal Sequence)

| Step | Task | Time |
|------|------|------|
| 1 | Run Supabase schema migration (all 3 tables + views) | 30 min |
| 2 | Build Webhook trigger + Validate Payload + Normalize | 30 min |
| 3 | Build Signal Extractor Claude node + Parse | 45 min |
| 4 | Test extraction with 3 sample research briefs | 30 min |
| 5 | Build Conviction Scorer Claude node + Parse | 45 min |
| 6 | Build Dedup Check + Merge & Validate | 40 min |
| 7 | Build Supabase upsert + archive + audit log | 45 min |
| 8 | Build error handling branches | 30 min |
| 9 | Build high-conviction alert (Slack/SMS) | 20 min |
| 10 | End-to-end testing (5 research briefs, edge cases) | 60 min |
| 11 | Add Google Docs poll path (optional) | 45 min |
| **Total** | | **~5.5 hrs** |

---

## Quick-Start: Manual Intake via curl

Once deployed, paste your NotebookLM research like this:

```bash
curl -X POST https://your-n8n.com/webhook/trading/research-intake \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: YOUR_SECRET" \
  -d '{
    "content": "PASTE YOUR NOTEBOOKLM RESEARCH BRIEF HERE",
    "source": "notebooklm_sector_tech"
  }'
```

**Response:**
```json
{
  "status": "processed",
  "signals_extracted": 4,
  "signals_new": 3,
  "signals_updated": 1,
  "high_conviction": [
    { "ticker": "NVDA", "conviction": 8, "suggested_strategy": "CSP" }
  ]
}
```

---

## Future Enhancements

1. **Splunk dashboard** — Forward all signals to Splunk via HEC for historical pattern analysis alongside your other CMSG telemetry
2. **Pre-trade checklist auto-run** — When a signal scores ≥ 8 conviction, trigger a second workflow that runs the full Pre-Trade Checklist (fundamentals + technicals + options check) via web scraping FINVIZ + Alpha Vantage
3. **NotebookLM audio transcript intake** — If you record audio overviews, use Whisper API or Claude's audio capability to transcribe → feed into the same pipeline
4. **Feedback loop** — After you act on a signal, update `status` to `acted` and log the outcome. Build a weekly workflow that analyzes signal accuracy → feeds back into the conviction scoring prompt to self-improve
5. **Google Docs → n8n native** — When NotebookLM adds export-to-Docs, Path B becomes fully automated with zero manual copy-paste
