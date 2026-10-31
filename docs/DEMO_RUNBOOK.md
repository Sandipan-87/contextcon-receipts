# Demo runbook (for the team)

## State left for you
- **Round 1 is scouted and sealed:** 10 real fintech/payments companies that raised since 2025 (`runs/scout_*`, `python -m receipts board`).
- **No human decisions have been made.** Your team must make the picks. Do not let anyone else, including the agent, make them; the agreement score is only meaningful if the picks are yours.
- The Mercury pitch has been verified (`runs/run_*`); its follow-up email is drafted in `outbox/`.

## Before recording (about 15 min)
1. Open `runs/scout_*/report.md` (round 1). As a team, pick the companies you would genuinely take to a partner meeting, about half.
2. `python -m receipts decide --round 1 --pick <numbers>` records your picks, scores the agent, and runs learning.
3. `python -m receipts scout` runs round 2, which uses what the agent learned. Its predictions are sealed.
4. Look at round 2, pick **without reading the agent's column** (cover it), then `python -m receipts decide --round 2 --pick <numbers>`.
5. `python -m receipts learned` shows the agreement in round 1 vs round 2, and what it learned.

## 2-minute recording
| Time | Show | Say |
|---|---|---|
| 0:00–0:12 | `strategy/STRATEGY.md` | "Our fund's rulebook. The agent acts on its own, but only inside these limits." |
| 0:12–0:30 | `python -m receipts run --pitch fixtures/pitches/01_mercury_planted_lies.txt` | "An inbound pitch with three lies we planted. It resolves 'Mercury Technologies' out of 25 Mercurys, and finds the right 'Max' out of six." |
| 0:30–0:45 | Red claims → **REQUEST_INFO** → drafted email in `outbox/` | "It decided by rule, moved the deal on our board, and drafted the founder email. Not sent: rule 4." |
| 0:45–1:10 | Round 2 `scout` output, predictions sealed | "Scouting: 333 thesis-fit companies, 10 new ones, scored with what it learned from our round 1 picks. Predictions are sealed before we choose." |
| 1:10–1:30 | `decide` output: agreement, then `learned` | "We picked; it scored itself against its sealed forecast and updated what it knows about our taste." |
| 1:30–1:50 | `verify last --witness` | "Every fact, verdict, action and model weight recomputes. Crustdata's own usage log confirms every call." |
| 1:50–2:00 | `tamper last` then `verify last` → ✘ | "Change one byte and it fails, at the exact receipt." |

## If something breaks live
- **API slow:** responses are cached by request hash, so re-running the same command replays from cache with no extra credits.
- **LLM down:** the agent falls back to the rule-based extractor and email templates, and says so in the trace.
- **LLM:** `beam` (free) is used first, then `gemma4:31b`. `minimax-m3` returns HTTP 402 on the free plan; add Ollama credits and set `OLLAMA_MODELS=minimax-m3,beam` to use it.
