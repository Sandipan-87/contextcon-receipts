# FINAL PLAN — "Receipts": a diligence agent whose every claim carries a verifiable receipt

**Theme:** Infrastructure for agents (verifiable execution trail), shown through Investing (startup diligence).

**Locked:** 31 Oct 2026, confirmed around 12:20 PM IST. Code freeze is at 3:30 PM. Watcher and portfolio monitoring are **out of scope**.

## 1. One-liner
An agent reads a founder's pitch, checks every claim against Crustdata's people and company graph, and writes a diligence memo. Every sentence in the memo points to a receipt: a hashed, chained, signed record of the real API response. Anyone can verify the memo afterwards with a deterministic `verify` command. No LLM is involved in verification, and Crustdata's own usage log acts as an independent witness.

## 2. The problem
AI agents fail in two ways.
- **Wrong entity.** `identify("Mercury")` returns 25 companies, all at confidence 1.0. `"Mercury Technologies"` ranks the real fintech at 0.6, tied with Dell. Both results were seen live.
- **Unsupported facts.** LLMs invent plausible numbers and citations.
- **The data itself can be noisy** (seen live). Ramp's headcount history swings 11,703 → 5,935 → 3,060 → 2,900 in 6 weeks (Sep–Oct 2026), and `headcount.total` = 3,757 disagrees with the latest point. Ramp still has 1,790 open roles, and the top 10 news results contain no layoff story. A naive checker would mark a true headcount claim CONTRADICTED. Ours must say "data unstable".

Diligence analysts spend 1–2 hours per inbound pitch cross-checking claims by hand, with no audit trail.

## 3. Input → output
**Input:** free-text pitch email or one-pager notes. The domain is optional.

**Output:** a run folder `runs/<run_id>/` containing:

| File | Contents |
|---|---|
| `report.md` / `report.html` | Verdict, claims table (✅ VERIFIED / 🟡 PARTIAL / ❌ CONTRADICTED / ⚠ UNSUPPORTED / ❔ UNVERIFIABLE), questions for the founder |
| `claims.json` | Structured claims, each citing fact IDs |
| `ledger.jsonl` | Hash-chained entries: tool_call, decision, anomaly, exception, claim_set, report |
| `blobs/sha256/<hash>` | Raw API response bytes |
| `head.sig` | Ed25519 signature over the chain head; the head hash is also committed to git |

## 4. Architecture
```
pitch text ─► agent.py (Claude: 1) extract claims  2) write report with {slots})
                 │ tools only via ▼
            proxy.py  ── REST ──► api.crustdata.com (identify, enrich, person/search, job/search, web/search)
              │ raw bytes → blobs/   │ flatten → facts F1..Fn {pointer, value, receipt_seq}
              ▼
            ledger.py  (canonical JSON, sha256 chain, Ed25519 sign)
              ▼
            claims.py  (typed comparators + derivation registry) ─► statuses
              ▼
            render.py  (fills {slots} from claims; scans for unbacked numbers/names)
              ▼
            verify.py  (no LLM): chain ▸ blobs ▸ claims ▸ report ▸ witness
              ▼
            viewer/index.html  (click sentence → claim → receipt → raw JSON with pointer highlighted)
```

| Step | Done by |
|---|---|
| Claim extraction, report wording | **LLM** |
| Entity resolution, comparisons, arithmetic, rendering, verification | **Code** |
| Facts | **Crustdata REST** (headers: `authorization: Bearer`, `x-api-version: 2025-11-01`) |

## 5. Key mechanisms

**Entity resolution** (logged as a `decision` entry):
- Domain or LinkedIn URL → identify. Exact; variants normalize, verified.
- Name only → identify candidates → code re-ranks on industry, founding year, size, domain → if it's still close, run person search on the founder and use their `current.crustdata_company_id`.
- Outcome is RESOLVED, AMBIGUOUS (logged with candidates) or NOT_FOUND.

**Facts, not pointers.** The proxy flattens each response into `F14 = {pointer:"/0/matches/0/company_data/headcount/total", value:1782, receipt:14}`. The LLM cites `F14`, and code owns the pointers.

**Claim kinds:**

| Kind | Example | Verified by |
|---|---|---|
| direct | headcount 1,782 | JSON-pointer value equals the claimed value |
| derived | eng share of roles 18.9% | Re-running a registered pure function (`ratio`, `per_employee`, `tenure_years`) |
| absence | no Google role in CTO's history | Search/enrich receipt and the exact query shown |

**Comparators** (pitch claim vs fact):

| Claim | Rule |
|---|---|
| headcount | **First a stability check** on `headcount.timeseries`. If week-on-week swings exceed 40% in the last 3 months, or `headcount.total` differs from the latest point by more than 15%, the claim is **UNVERIFIABLE (data unstable)**, logged as an `anomaly` entry. Corroborate with job count and news, and never mark it CONTRADICTED. Otherwise: within ±15% → VERIFIED; within ±40% → PARTIAL; else CONTRADICTED. |
| founded year | exact match; ±1 year → PARTIAL |
| round amount / lead | amount ±5%; lead investor ∈ `lead_investors` |
| prior employer | company ID ∈ the founder's `past[]`, with tenure computed from that entry's own start/end dates (request JSON; markdown flattens `past[]` and loses the pairing) |
| "X is still our CTO" / team claims | person search on current CXOs at the company. Departures are verified with the `experience.employment_details.past.company_id` filter (live: returned 16 former Ramp CXO/VPs with end dates) |
| hiring | job count and category share |

**Hallucination block.** The LLM writes `"Headcount is {c3}"`, and the renderer fills in the value. A regex scan flags any number or name that doesn't come from a claim.

**Ledger entry** (all fields confirmed from live REST headers):
`seq, type, ts, endpoint, request, request_hash, http_status, response_hash, upstream_request_id (X-Request-ID), credits_used (X-Credits-Used), rate_limit_remaining, prev_hash, entry_hash`

**The `verify` command:**
1. **Chain:** recompute hashes, check links and seq gaps, check the signature.
2. **Blobs:** sha256 matches.
3. **Claims:** pointers, derivations and absences re-checked.
4. **Report:** every sentence has ≥1 claim; no unbacked numbers.
5. **Witness:** `GET /account/usage/events/{X-Request-ID}`. Endpoint, request body, status, credits and timestamp must match. Confirmed working live: HTTP 200, event visible within 15 seconds.

**Limitation to state on stage:** the witness proves the call happened with those parameters, but not the response content (`response: null` for successful calls). The key holder could re-sign a rewritten chain. Mitigations: the witness check, plus the head hash committed to git.

**Robustness:**
- Retries with backoff. Each retry is its own entry, and errors are logged as receipts.
- The proxy caches by request hash, because dropped connections were still charged.
- The proxy reads `X-RateLimit-Remaining` to pace calls.
- Null field → UNVERIFIABLE.
- `crustdata_company_id: 0` → fall back to name match.
- Anomaly rule: monthly growth beyond ±40%. Do **not** sum regions; they overlap.

## 6. Two-minute demo script
| Time | Shows |
|---|---|
| 0:00–0:12 | Problem in one line. Paste a pitch with **3 planted lies, said aloud** (e.g. "3,000 people", "led by Accel", "CTO ex-Google") |
| 0:12–0:30 | "Mercury Technologies" → AMBIGUOUS decision entry → resolved to 631990 via the founder |
| 0:30–1:00 | Live calls stream, showing receipt numbers, credits and request IDs |
| 1:00–1:25 | Report: 3 red claims with evidence; a ❔ for unverifiable ARR; the founder questions. *(Optional 5-second cut: a Ramp pitch's headcount claim → "UNVERIFIABLE: Crustdata series unstable", showing the agent doesn't trust bad data blindly.)* |
| 1:25–1:45 | Click a sentence → receipt → raw JSON with pointer highlighted. `verify` → all ✔, witness 100% confirmed |
| 1:45–2:00 | Edit one byte in a blob → `verify` ✘ "blob hash mismatch at receipt #14". Git shows the committed head hash |

Live values available for the demo (verified today on Mercury): founded 2017; headcount 1,782; Series D $200M led by TCV on 2026-05-20; total funding $657M; CTO Maximilian Tagher's past employer is Heyzap (2011–2017); 1,752 jobs, 331 of them Engineering.

## 7. Repo
```
receipts/
  proxy.py  ledger.py  facts.py  resolve.py  claims.py  agent.py  render.py  verify.py
  mcp_server.py        (stretch)
  viewer/index.html
  fixtures/pitches/    (team-written test pitches, planted lies labeled)
  runs/                (gitignored except the demo run)
  .env.example  .gitignore(.env)  README.md
```
Stack: Python 3.11, httpx, pynacl, jsonpointer, anthropic (Claude Sonnet for speed), rich.

## 8. Team plan (4 people)
| Who | Owns | Done by |
|---|---|---|
| A | `ledger.py` + `verify.py` (chain, blobs, signature, witness) | 1:45 |
| B | `proxy.py` + `facts.py` + `resolve.py` (REST, cache, retries, flattening, AMBIGUOUS) | 1:15 |
| C | `agent.py` + `claims.py` + `render.py` (extraction, comparators incl. the stability check, slots, unbacked-number scan) | 2:15 |
| D | 6 test pitches (Mercury with planted lies; one ambiguous name; one Ramp pitch with a *true* headcount claim to show "data unstable"; one company not in Crustdata; one with typos/no domain; one fresh company for the "never seen" run), viewer, README, demo recording | 3:15 |

**Checkpoints:**
- **1:15:** one pitch → resolve → 2 facts → 1 claim → ledger → verify ✔, end to end.
- **2:00:** all claim types, report, tamper test.
- **2:30:** feature freeze; run all 6 pitches.
- **2:45–3:10:** record the demo.
- **3:20:** submit.

**Cut order if late:**
1. `mcp_server.py`
2. Witness check
3. Derived claims
4. HTML viewer, falling back to a terminal report

**Never cut:** chain, facts, claim check, unbacked-number scan.

## 9. Before writing code (first 10 minutes)
- [ ] Rotate the API key that was exposed in chat; put the new one in `.env` only.
- [ ] Check this key's credit balance (`GET /account/credits`). The MCP account may be a different team.
- [ ] Confirm the team has an Anthropic API key.
- [ ] Create the repo and push the skeleton (shows coding started after 10:30).
