# Receipts

**An autonomous deal-screening agent for venture funds. It acts only inside your written rules, learns your taste from your decisions, and proves every claim and action with signed API receipts.**

Built for ContextCon IIT Bombay (Crustdata × Y Combinator). Themes: Investing, and Infrastructure for agents (cryptographic execution trails, rule-checkers).

## The manual work it replaces
An analyst at a fund spends 1–2 hours per company:
1. Find companies that fit the thesis, or read an inbound pitch.
2. Work out which company it really is.
3. Check headcount, funding, team and hiring across LinkedIn, Crunchbase and Google.
4. Decide.
5. Email the founders.
6. Update the CRM.

None of it is auditable afterwards.

## What the user does vs what the agent does
| Step | You | Agent | Output |
|---|---|---|---|
| Set strategy | Edit `strategy/STRATEGY.md` once: thesis, ± tolerances, guardrails, autonomy limits, allowed actions | Seals the full rulebook text into every run | Rules in force, provable later |
| Source | Run `scout`, or drop an inbound pitch | Searches Crustdata for thesis-fit companies (skipping ones already on the board), or extracts every claim from a pitch with an LLM | Candidates / claims |
| Identify | — | Resolves companies and people to Crustdata IDs. **Refuses to guess** when ambiguous ("Mercury" = 25 companies; "our CTO Max" = 6 Maxes) | Logged decisions |
| Investigate | — | Calls Crustdata enrich / person search / job search; every response stored and hashed as a receipt | Receipt-backed facts |
| Judge | — | Code compares claims to facts within the strategy's ± margins; scores companies with your learned preferences; detects bad source data | Verdicts, p(you pick) |
| Commit | — | **Seals its predictions into the signed ledger before you decide** | Tamper-proof forecast |
| Act | — | Within its autonomy limits: updates the deal board, drafts founder emails to `outbox/` (never sent, per handbook rule 4), archives the signed trail. Below its confidence threshold, or before it has learned enough, it queues the deal for you. | Executed actions, each citing the rule that allowed it |
| Decide | Pick the companies you want (`decide --pick 2,5,7`) | Scores itself against its sealed predictions, executes your decisions, re-fits its model of your preferences, and explains what it learned | Agreement score, updated preferences |
| Audit | `verify` any run, any time | Recomputes everything; no LLM involved | ✔ / ✘ |

## Web app (recommended for users and the demo)
```bash
python -m receipts.webapp        # then open http://127.0.0.1:8000
```

| Page | What you do there |
|---|---|
| **Deal board** | See every company by stage (Needs analyst / Partner meeting / Awaiting founder info / Passed). |
| **Scout & decide** | Scout a round, tick the companies you'd pick (the agent's sealed prediction stays blurred so you can pick blind), submit, and see the agent's agreement score, the actions it executed, and what it learned. |
| **Check a pitch** | Paste a pitch (or load an example) and watch the agent work live. Then see the verdicts, click any fact for its receipt, and see the decision, the actions taken, and the drafted email. |
| **What it learned** | Agreement per round, your preferences in plain words, and the stated-vs-learned weights. |
| **Outbox** | Drafted emails (never sent). |
| **Audit trail** | Verify any run (optionally with Crustdata's usage-log witness), or run a tamper test on a copy. |
| **Rulebook** | The rules the agent acts within. |

## Quick start (CLI)
```bash
pip install -r requirements.txt pyyaml numpy
cp .env.example .env              # CRUSTDATA_API_KEY; OLLAMA_API_KEY optional (beam, falls back to gemma4:31b)

python -m receipts scout                      # round of 10 thesis-fit companies, predictions sealed
python -m receipts scout --thesis "Series A devtools in India"   # a never-seen thesis, typed in plain English
python -m receipts decide --round 1 --pick 1,4,5   # your real choices; agent scores itself and learns
python -m receipts scout                      # next round uses what it learned
python -m receipts analyze razorpay.com      # analyse one company against your thesis + learned taste
python -m receipts board                      # deal board
python -m receipts learned                    # what it learned + agreement per round
python -m receipts run --pitch fixtures/pitches/01_mercury_planted_lies.txt   # verify an inbound pitch
python -m receipts verify last --witness      # re-prove a run, incl. Crustdata's own usage log
python -m receipts view last                  # clickable HTML: any fact -> its receipt -> raw API JSON
python -m receipts tamper last && python -m receipts verify last              # watch it fail
```

## Bounded autonomy (`strategy/STRATEGY.md`)
| Section | What it controls |
|---|---|
| `thesis` | Hard filters: sector, HQ countries, headcount, stage, raised since. |
| `tolerances` | ± margins for claims (e.g. headcount ±15% = verified, ±40% = partial). |
| `guardrails` | Hard rules learning can't override: contradicted claims block ADVANCE; 3 contradictions mean PASS; ambiguous entities go to a human; unstable data is never held against a company. |
| `autonomy` | Act alone only if confidence ≥ 0.80 **and** ≥ 10 of your decisions have been learned. Otherwise the agent queues for you. |
| `actions` | Allowed: `update_deal_board`, `draft_email_to_outbox`, `archive_signed_trail`. Forbidden: `send_external_email`, `contact_any_person`. Forbidden actions are blocked and logged. |
| `learning` | Your stated prior preferences, how strongly they anchor learning, and weight bounds. |

## Free-text thesis (a request it has never seen)
Type a thesis in plain English, on the Scout page or with `scout --thesis`. The LLM *proposes* filters; code validates every value:
- **Industries** are checked against Crustdata's autocomplete, and each lookup is a receipt.
- **Round types** must be in the allowed set, and **countries** are normalized.
- **Criteria it can't search on** (e.g. "technical founders") are shown to you, not invented.

If too few new companies match, the agent relaxes the least essential filter first: split keywords, then drop keywords, then drop recency, then widen to neighbouring stages. Each relaxation is a ledger decision shown in the round. Industry, country and the rulebook's guardrails are never relaxed.

## Preference learning
- **Model.** Bayesian logistic regression over receipt-backed features: headcount growth, engineering hiring share, open roles, time since last round, team size, funding, stage, and age. It starts from the stated thesis, and each pick or reject moves it. A Laplace approximation gives its confidence, so it defers to you while uncertain.
- **Honest scoring.** Predictions are sealed before you choose, and agreement ("matched 8/10", "you picked 2 of my top 3") plus a **calibration (Brier) score** are computed afterwards. A Brier score of 0.25 is what always guessing 50% would get, so lower is better. Nobody, including us, can edit the forecast after seeing your picks.
- **Re-checkable.** The model is a deterministic function of your recorded decisions; `verify` re-fits it and gets the same weights.
- **Honest limit.** With 10–20 decisions the model is still weak. Agreement is noisy round to round (synthetic test: 0.7–0.9), and it improves as decisions accumulate. We report it; we don't promise it.

## What `verify` checks
- **Every run:**
  - The hash chain and Ed25519 signature are intact.
  - Every stored API response re-hashes correctly.
  - Every fact re-resolves from the raw bytes.
  - Every action was permitted by the *sealed* rulebook.
  - Every LLM-drafted email uses only numbers present in its grounding facts.
- **Pitch runs:**
  - Each verdict re-runs with the sealed tolerances.
  - The memo re-renders byte-for-byte, so it contains no text without a source.
- **Scout runs:**
  - The features are recomputed from facts.
  - The scores are recomputed with the sealed model.
  - The predictions are sealed before any decision.
- **Decide runs:**
  - The referenced predictions are intact and pre-date the decision.
  - The agreement score is recomputed.
  - The model is re-fitted from the training set.
- **`--witness`:** each call matches Crustdata's `/account/usage/events/{X-Request-ID}` (endpoint, request body, status, credits).

**Limitation:** the usage log proves each call happened with those parameters, but it doesn't store response bodies. Publish or commit the head hash when sharing results.

## LLM use (Ollama)
The LLM handles claim extraction from pitches and the wording of drafted emails. Models are tried in order: `OLLAMA_MODELS` (default `beam,gemma4:31b`, both on the free Ollama plan; `minimax-m3` needs Ollama credits). A model the account can't use (e.g. HTTP 402) is skipped, and the model that actually ran is recorded in the ledger. If no LLM is available, a rule-based extractor and email templates take over. Verification never uses an LLM.

## As an MCP server
Any MCP client (Claude Code, Claude Desktop, …) can use the same rulebook, receipts and signed trail:
`claude mcp add receipts -- python -m receipts.mcp_server` (or use the bundled `.mcp.json`).

| Tool | What it does |
|---|---|
| `get_strategy` | Returns the rulebook. |
| `check_pitch` | Verifies a pitch, decides, acts, and seals the run. |
| `scout_round` | Scouts, scores, and seals predictions. |
| `record_decisions` | Records the human's picks only, then scores and learns. |
| `verify_run` | Deterministic re-verification, optionally with the witness check. |
| `deal_board` | Returns the current board. |

## Layout
```
strategy/   STRATEGY.md (the rulebook), LEARNED.md (generated)
receipts/   proxy ledger facts resolve extract claims features learn scout decide actions board compose llm render verify
fixtures/   test pitches (team-written; planted lies labelled)
tests/      offline tests (learner test uses synthetic decisions only)
runs/       one signed folder per run · data/ deal board + model · outbox/ drafted emails
```
