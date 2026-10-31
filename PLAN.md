# PartnerMesh — a VC firm's partners as a market of agents

> ContextCon IIT Bombay · Crustdata track · code freeze 3:30 PM IST

## One-liner
A VC firm types a thesis it has never run before. Each partner's AI twin (defined by its own `agents.md`)
scouts and researches startups on Crustdata's graph, places sealed bids in an internal prediction market,
and the firm gets a ranked shortlist, a cited IC memo, and draft founder outreach. Humans only handle exceptions.
Every fact and bid is hash-chained, so the decision is auditable and agents can't rewrite reasoning after outcomes.

## Rubric mapping
| Criterion | How we hit it |
|---|---|
| End-to-end (25) | thesis → sourcing → research → bids → market → memo + outreach drafts + CRM, one command |
| Verification (20) | every number in a memo cites a receipt (Crustdata request id + response hash); `verify` command |
| Robustness (20) | messy thesis text, ambiguous company names, failed API calls logged, data anomalies flagged → exception queue |
| Value (20) | outbound deal sourcing + IC prep is analyst/associate work VCs pay for today; market weights partners by track record |
| Domain (15) | partner twins, conviction budgets, bull/bear dissent, warm-intro-first outreach |

## Architecture
```
thesis (free text)
  └─► planner (LLM) ──► Crustdata company_search filters  (fallback: deterministic keyword filters)
        └─► candidates (≤8) ──► company_enrich (+ founders/people) ──► feature sheet (deterministic, no LLM math)
              └─► each partner agent (LLM + its agents.md + weight) ──► sealed bid {prob, stake, reasons→feature keys}
                    └─► market clears: price = Σ w·stake·prob / Σ w·stake
                          └─► outputs: ranked list · IC memo (bull/bear) · outreach drafts (outbox/) · crm.json · exceptions.md · report.html
feedback(company, outcome) ──► Brier score per agent ──► weight update + "lessons" appended to that agent's agents.md
ledger.jsonl: every API call / decision / bid hash-chained (sha256, prev_hash) ──► `verify`
```

## Stack (decided)
- Python 3, `httpx`, stdlib `hashlib`/`json`; no heavy frameworks.
- LLM: **open-source model via an OpenAI-compatible endpoint**. Default **Groq → `llama-3.3-70b-versatile`** (fast, free tier);
  fallback **Ollama local `qwen2.5:3b`** (CPU-only box, slower). Switchable by env var.
- Crustdata REST: `https://api.crustdata.com`, headers `authorization: Bearer $CRUSTDATA_API_KEY`, `x-api-version: 2025-11-01`.
  Enabled on our plan: company identify/search/enrich, person search/enrich, job search, web search/fetch.
- Outbound actions are sandboxed (local outbox/CRM files) — competition rule: no contacting real people.

## Repo layout
```
partnermesh/
  crust.py       # Crustdata client; every call → ledger receipt (incl. failures)
  ledger.py      # hash chain + verify
  llm.py         # OpenAI-compatible client (Groq/Ollama), JSON output + retry
  features.py    # deterministic signals: headcount growth, hiring, funding recency, runway proxy, founder pedigree, anomalies
  agents.py      # load agents.md, prompt, parse sealed bid
  market.py      # clearing + weights + feedback (Brier)
  outputs.py     # memo, outreach drafts, crm.json, exceptions, report.html
  cli.py         # run / verify / feedback
partners/
  priya_founder_hawk/agents.md     # founders & team above all
  arjun_momentum_quant/agents.md   # growth & capital efficiency, skeptical of hype
runs/<run_id>/   # ledger.jsonl, blobs/, outputs
```

## Build order (≈2h) — cut from the bottom if late
1. **13:30–13:45** Keys + repo: Crustdata API key, Groq key, `gh` install + auth, private repo `saketvispute/partnermesh`.
2. **13:45–14:20** `crust.py` + `ledger.py` + `features.py` — verified against 2 real companies.
3. **14:20–14:50** `llm.py` + two `agents.md` + `agents.py` + `market.py` — bids parse reliably.
4. **14:50–15:10** `outputs.py` (memo, outbox, crm, exceptions, report.html) + `cli.py run` end-to-end on a fresh thesis.
5. **15:10–15:20** `verify` + `feedback` (weights + lessons) — **cut first if late**.
6. **15:20–15:30** Record 2-min video, push, submit.

Stretch (only if ahead): warm-intro path via founder co-employment overlap; Crustdata watchers on "watch" list.

## Demo script (2 min)
1. (15s) Problem: partners + associates spend days sourcing & prepping IC; firm decision is one vote.
2. (60s) `run "Series A devtools in India, technical founders"` → live log: search, enrich, Priya bids, Arjun bids, market price.
3. (30s) report.html: ranked list, memo with bull/bear + citations, outbox drafts, exception queue (anomaly / split vote).
4. (15s) `verify` ✔, tamper one number → ✘; `feedback` → weights shift, lesson added to agents.md.

## Needed from the team now
- `CRUSTDATA_API_KEY` (REST key from Crustdata dashboard — the MCP login isn't usable from our code)
- `GROQ_API_KEY` (console.groq.com, free) — or say "local" to use Ollama
- GitHub: run `! gh auth login` once `gh` is installed
