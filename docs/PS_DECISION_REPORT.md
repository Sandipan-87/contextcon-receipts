# ContextCon IIT Bombay — Problem-Statement Decision Report

Prepared 31 Oct 2026, roughly 10:55 AM. Coding opened at 10:30 AM and freezes at 3:30 PM.

**Update, around 11:30:** **PART N, the Infrastructure for Agents deep-dive**, has been added at the end. Probes run since the first draft corrected Parts C and E:
- Watcher is now confirmed accessible.
- Calls whose connection drops still get charged.
- Dot-path field narrowing works.

Sources:
- `docs/ContextCon PS - CrustData.pdf` (the handbook)
- docs.crustdata.com
- **Live probes against your Crustdata account through the connected MCP** (about 3 credits spent)

Tags used throughout:
- **[H]** stated in the handbook
- **[V]** verified by a live API call today
- **[D]** stated in the official Crustdata docs
- **[I]** inference or engineering judgment
- **[U]** unverified

---

## PART A — Executive Recommendation

**Primary PS: C1, "Claim-Verified Startup Diligence Agent" (Investing theme).**

The agent takes an unstructured founder pitch (an email, one-pager text, or deck notes), extracts every factual claim, and resolves the company and founders to Crustdata canonical IDs. It then verifies each claim against the identity graph, with web/news as corroboration, and produces a diligence memo. Every sentence in the memo is tied to a ledger entry marked **VERIFIED / CONTRADICTED / PARTIAL / UNVERIFIABLE**, with the endpoint, field path, entity ID, source URL, and data as-of date.

| | |
|---|---|
| Weighted score (base weights) | **85.0 / 100** |
| Sensitivity | #1 in all four weighting scenarios (83.0–86.5) |
| Confidence | **Medium-high.** Every core endpoint was exercised live. The REST response shapes and LLM-extraction quality still need to be validated in the first 30 minutes. |

**Why it is the strongest choice:**

1. **It maps directly onto the judging rubric.**
   - "Verifiable citations for every claim" [H] is the product itself.
   - "Unformatted inputs" [H] is the input.
   - "Messy data / unexpected tool responses" [H] shows up as contradictions and gaps the agent has to handle.
2. **The data is demonstrably there [V].**
   - A live `company/enrich` on Mercury returned funding milestones with date, amount, lead investor, and Crunchbase permalinks: Series D, $200M, TCV-led, 2026-05-20.
   - An independent `web/search` (news) returned "Mercury secures $200m Series D at $5.2bn valuation… led by TCV".
   - That is a working cross-source verification on the first try.
3. **The identity-graph problem is real and demo-able [V].** `company/identify` with `names:["Mercury"]` returned **25 different companies, all with `confidence_score: 1.0`**: fintech, construction, logistics, podcasts, and more. Naïve agents will silently pick the wrong one. Ours resolves the ambiguity with evidence, and judges can watch it happen.
4. **Most of the checking is deterministic.** Comparators are plain code (numbers, dates, set membership, ID joins). The LLM only extracts claims and writes prose constrained to the ledger. That makes it hard to dismiss as a "thin wrapper".
5. **The engine is shared with the backup and the alternative** (C3 hiring and C2 KYB). If C1 stalls, you can pivot by swapping the claim schema without rewriting the core.

**Main way it could fail:**
- Claim extraction quality, plus over-scoping the claim types.
- Operational risk from oversized `company/enrich` payloads. Funding plus headcount came back as **115 KB**, and two of four enrich calls through MCP dropped the connection [V]. Mitigate by requesting narrow fields, stripping timeseries, and retrying with backoff.

**Why the alternatives are weaker:**
- **C3 (hiring verification)** is nearly as strong but only uses the person side of the graph, and it carries an ethics/optics cost because it verifies real individuals.
- **C2 (KYB)** cannot produce real verdicts. Crustdata has no corporate-registry or sanctions data, so it would issue *risk signals* and could not prove a business is a shell.
- **Sourcing (C4) and market maps (C8)** are the most common hackathon builds and score low on novelty and verifiability.

---

## PART B — Competition Constraints

### B.1 Specification extracted from the handbook

| # | Item | Handbook content [H] |
|---|---|---|
| 1 | Objective | Build autonomous agents that turn professional-service workflows (hiring, investing, research, compliance) into software. The handbook says it rewards "root-cause understanding… agentic execution precision, and reliable verification… over simple prompt wrappers." |
| 1b | Challenge question | Execute a firm-level workflow "end-to-end with high precision, verifiable reasoning, and zero human intervention under strict time constraints." |
| 2 | Themes | Hiring, Investing, Research & markets, Insurance, Trust & compliance, Buying & paying, Agents that spend, Supply chain, Revenue, Infrastructure for agents. The themes link ("ContextCon 03: IIT Bombay · The Themes") **was not in the PDF** — this is a gap. |
| 3 | Mandatory data | "Must integrate and build on top of Crustdata's canonical identity graph for people and company data." Rule 3: "must utilize Crustdata's API keys and identity graph during the build." |
| 4 | APIs named | Person Search, Person Enrich, Company Search, Company Identify, Company Enrich, Job Search, Web Search and Fetch, Watcher. Base URL `https://api.crustdata.com`. |
| 5 | Headers | `authorization: Bearer YOUR_API_KEY`, `x-api-version: 2025-11-01`. Confirmed current by the docs [D] and by the MCP tool descriptions [V]. |
| 6 | Architectures | A single agent, a system of agents, an MCP server, or a CLI. |
| 7 | Judging | End-to-End Execution; Data Integrity & Verification; Robustness & Edge Cases; Demo Clarity. **No weights given.** |
| 8 | Eligibility / team | 3rd/4th-year BTech, dual-degree, and MTech students at IIT Bombay. Individual or up to 4 members. |
| 9 | Time | Code start 10:30 AM; last call 3:00 PM; **freeze and submission 3:30 PM** (5h). Video review 3:45 PM; finalists announced 5:00 PM; live finals 5:30 PM. |
| 10 | Deliverables | A functional code repository plus a **2-minute screen-recording demo video** showing "the product taking a request it has never seen all the way to finished work". |
| 11 | External interactions | Agents "strictly restricted from interacting with external real people; they must interact only with the team's local environment and authorized APIs." |
| 12 | Other | Register via the YC event platform. Pre-built ideas and sketches are allowed; coding is not allowed before 10:30. Judges' decisions are final. Finalists **demo live on stage**, so the system must run live as well as on video. |

### B.2 Compliance checklist

- [ ] Registered on the YC event platform [H]
- [ ] Repo created after 10:30 AM, with commit history showing that [H; the commit-history evidence is my inference]
- [ ] Crustdata API key used, with ≥2 graph endpoints in the critical path [H]
- [ ] Headers `authorization` and `x-api-version: 2025-11-01` set on every call [H][D]
- [ ] No email, SMS, DM, or other outreach to real people; nothing is sent anywhere, and outputs are local files [H]
- [ ] Interaction mode is a CLI, optionally plus an MCP server [H]
- [ ] The demo uses a request the agent has never seen [H]
- [ ] The 2-minute video is a **screen recording of live execution**, not slides [H]
- [ ] Repo and video submitted **before 3:30 PM**; aim for 3:15 [H]
- [ ] It can run live on stage at 5:30 PM, so there is a cached-replay fallback [H]
- [ ] Every team member meets the eligibility criteria [H]

### B.3 Requirement / interpretation / assumption separation

- **Explicit [H]:** everything in the B.1 table.
- **Reasonable interpretation [I]:** "Build on top of the identity graph" means `crustdata_company_id` and `crustdata_person_id` should be the join keys of the system, not decoration.
- **Reasonable interpretation [I]:** Calling Crustdata through MCP *or* REST both satisfy the handbook.
- **Reasonable interpretation [I]:** Using public figures' professional data is allowed. *Contacting* them is not.
- **Assumption to verify [U]:**
  - REST payloads match the MCP-wrapped payloads.
  - The team has an LLM API key.
  - Exactly what the themes link adds.
  - Whether judges supply the "never-seen request" live.

---

## PART C — Technical Research

### C.1 Account reality (live, `GET /account/endpoints` + `/account/credits`) [V]

- **Credits:** 15,200. About 3 credits were spent on these probes.

**Enabled endpoints:**

| Endpoint | Rate limit | Cost |
|---|---|---|
| `/company/identify` | 30 rpm | **free** |
| `/company/enrich` | **15 rpm** | 2 credits per company; technographics +2 |
| `/company/search` | 30 rpm | 0.03 per result + premium groups |
| `/company/search/autocomplete` | 300 rpm | free |
| `/person/search` | 30 rpm | 0.03 per result + premium groups, e.g. experience +0.1 |
| `/person/enrich` | **15 rpm** | 1 credit, cached |
| `/person/search/autocomplete` | 300 rpm | free |
| `/job/search` | 30 rpm | 0.03 per result |
| `/web/search/live` | **10 rpm** | 1 credit per page |
| `/web/enrich/live` (web fetch) | **10 rpm** | 1 credit per URL |
| `/social_post/search` | — | 0.5 per post |
| `/agent/query` | — | 2 credits; undocumented in llms.txt [U] |

**DISABLED** (each returns 403):
- `/person/contact/enrich` (no emails or phones)
- All `*/live` professional-network search and enrich (no real-time profile refresh, no live job search)
- **All `/batch/*`**
- `/employee_review/enrich`
- `/dev_platform/enrich`

**Watcher:** `/watch/*` paths do not appear in the endpoint list. However, a **`watch_create` with `preview:true` returned `can_create: true`, resolved 1/1 entity, and quoted 5 credits per notification [V]** (free, and no watch was created). Watcher is therefore accessible. It is still asynchronous: runs are hourly at best, and the first run is only a baseline. **It cannot carry a 2-minute live demo.**

**Transport reliability [V]:**
- About 6 of 19 MCP calls returned "Lost the connection while reading the reply". This happened even on free endpoints (identify, credits).
- **The balance shows dropped calls were still charged** (about 6 credits).
- REST behavior is untested [U]. Design for idempotent caching either way.

### C.2 Endpoint analysis

| Endpoint | Input | Returns (observed) | Role in C1 | When data is missing / ambiguous | Essential? |
|---|---|---|---|---|---|
| Company Identify [V] | arrays of domains / names / ids / LinkedIn URLs (one type per call, ≤25), `exact_match` | `crustdata_company_id`, basic_info (name, domains, LinkedIn URL, year_founded, employee_count_range, industries, type) | Entity resolution: the free first hop | **Name lookups are ambiguous: 25 "Mercury" matches, all confidence 1.0.** Confidence is non-discriminative, so domain or context is required. | **Essential** |
| Company Enrich [V] | same identifiers + `fields` groups | `funding.milestones[]` (round_type, date, amount_usd, lead_investors, investors, Crunchbase permalink), total_investment_usd, acquisitions; `headcount.total`, growth_percent (mom/qoq/yoy), by_role, 198-pt timeseries; plus people, news, locations, etc. [D] | Ground truth for funding, headcount, founded year, HQ, growth claims | Null groups are not billed. **Payloads are huge (115 KB for 2 groups); MCP connection dropped 2/4 times.** **Dot-path `fields` (e.g. `headcount.total`, `funding.last_fundraise_date`) return a small payload for 2 credits [V].** Always narrow. | **Essential** |
| Person Search [V] | filter tree on nested paths (e.g. `experience.employment_details.current.company_id`, `seniority_level`, `basic_profile.name`) | `crustdata_person_id`, name, headline, current[] and past[] employment, **each carrying `crustdata_company_id`**, start_date/end_date, `business_email_verified`, education, LinkedIn URL, **`metadata.updated_at`** | Founder/exec verification; founder prior-employer claims, using the person→company ID join | `remarks` explains zero-result filters. Past employers may have `crustdata_company_id: 0` (unlinked). | **Essential** |
| Person Enrich [D] | LinkedIn URLs ≤25 | full profile | Only needed if search payload is insufficient | `matches: []` when unmatched | Optional |
| Job Search [V] | filters on `company.basic_info.crustdata_company_id`, aggregations | listings with LinkedIn job URL, `date_added`, plus company snapshot (headcount, total_funding_usd, last_round_type); `count` and `group_by` aggregations | "We're hiring aggressively / building an eng team" claims; e.g. Mercury: 1,752 listings, 331 Engineering | 0 results are free | Optional (strong) |
| Web Search [V] | query, `sources:["news"]`, dates | title, snippet, url, position, timestamp | Corroboration for claims the graph lacks (valuation, revenue, customers) | **News URLs are `google.com/goto?url=…` redirect links** — store as-is and label them; do not claim they are the publisher URL. | Optional (strong) |
| Web Fetch [V-partial] | 1–10 URLs | `[{success,url,timestamp,title,content≤30k}]` | Read a cited page to confirm a snippet | **Connection dropped on first try** — treat as best-effort | Optional |
| Company Search [D] | filters | companies | Not needed in C1 MVP (needed for C8) | — | Optional |
| Watcher [D][V-preview] | entity/discovery watch; `preview:true` is free | async runs; preview returns `can_create`, resolved count, `per_notification` cost | Out of scope for C1 (relevant to I4/I8 in Part N) | — | Exclude |
| MCP [D][V] | `https://install.crustdata.com/mcp`, streamable HTTP, OAuth or bearer key | all tools above | Dev exploration (already used). For the product, **prefer direct REST** for control over timeouts and retries [I]. | — | Optional |

**Rate limits and errors [D]:**
- 429 returns `{"error":{"type":"rate_limit_error",…}}`.
- Recommended handling is exponential backoff with jitter.
- Enrich is limited to 15 rpm and web to 10 rpm. A single diligence run needs about 6–10 calls, which is comfortably within limits.

**Technical implications:**
1. Always resolve by **domain** when available; it is the cleanest key.
2. Name-only resolution needs a deterministic re-ranker plus a founder→company cross-join.
3. Keep payloads narrow.
4. The data is fresh: `metadata.updated_at` is 2026-10-24…27 and funding is dated 2026-05-20 [V]. Every ledger entry can carry an as-of date.

---

## PART D — Candidate Problem Statements

You supplied no candidates, so I generated fifteen.

| ID | Theme | Problem → deliverable | Target user | Crustdata dependency | Differentiator vs wrapper |
|---|---|---|---|---|---|
| **C1** | Investing | Unstructured pitch → claim-by-claim verified diligence memo + evidence ledger | VC analyst (screening 50 inbound decks/week) | Identify, Enrich (funding/headcount), Person Search (founders and prior employers, ID-joined), Job Search, Web Search | Deterministic comparators; entity disambiguation; contradiction detection; a prose validator that rejects uncited numbers |
| **C3** | Hiring | Unformatted résumé/claims → per-claim employment verification report (title, employer, dates) | Outcome-paid recruiter / staffing agency | Person Search/Enrich, Company Identify (employer resolution) | Date-overlap logic, employer alias resolution via IDs, a mismatch taxonomy |
| **C2** | Trust & compliance | Vendor/merchant onboarding form → KYB risk report with rule hits + credit-limit band | Fintech risk/onboarding ops | Identify (domain↔name consistency), Enrich (age, headcount, funding, people), Person Search (do the claimed directors work there?), Web Search (adverse news) | A rule engine over graph signals; consistency checks |
| C4 | Hiring | JD → ranked shortlist of verified candidates with fit rationale | Recruiter | Person Search heavy | Weak: the most common build |
| C5 | Buying & paying | Purchase request naming a vendor → policy-checked approve/reject + alternative vendors | Procurement ops | Identify, Enrich, Company Search (alternatives) | Policy rules plus vendor verification |
| C6 | Buying & paying | Invoice → vendor verification + BEC/fraud flags | AP team | Identify by domain | Needs PDF parsing; Crustdata is a minor part |
| C7 | Insurance | Company name → underwriting submission pre-fill + risk flags | Commercial underwriter | Enrich (industry, headcount, locations, growth), Web (incidents) | Moderate; overlaps C2 |
| C8 | Research | "Map X startups in region Y at stage Z" → cited market map | Analyst | Company Search, Enrich | Common; filter-tuning risk |
| C9 | Revenue | Inbound lead → ICP score + routing + CRM record | RevOps | Identify (from email domain), Person Search | Person-identify-by-email is **disabled** — degraded |
| C10 | Revenue | Account → outbound research brief (draft only, never sent) | SDR | Enrich, Person Search | Low novelty; outreach restrictions |
| C11 | Agents that spend | Research agent with a hard credit budget, cost-aware planning, and a spend ledger | Platform teams | Uses Crustdata credits as the spend | Interesting, but the output is thin; best as a *feature* of C1 |
| C12 | Infra | MCP middleware enforcing claim→evidence citation + hash-chained execution trail | Agent developers | Wraps the Crustdata MCP | No "finished work" by itself |
| C13 | Supply chain | Supplier list → supplier risk report | Sourcing manager | Company-level only; no shipment or BOM data | Data gap |
| C14 | Investing | Price a round from historical comps | Banker / VC | Funding milestones; valuation data is sparse [U] | Verifiability gap |
| C15 | Trust | Key-person / leadership-change monitor via Watcher | Portfolio ops | Watcher | Async, can't demo in 2 min |

### Full spec for the top three (abridged for the others)

#### C1 — Claim-Verified Startup Diligence

| Field | Detail |
|---|---|
| Existing workflow | An analyst manually cross-checks a deck against Crunchbase, LinkedIn, and news: 1–3 hours per company, inconsistently documented. |
| Request | "Here's an inbound pitch email from {founder}. Run first-pass diligence." (free text, optionally with a domain) |
| Deliverable | `memo.md` / `memo.html`: summary verdict, claims table (status + evidence), contradictions, unverifiable items, open questions for the founder call. Plus `ledger.json` and `trace.jsonl`. |
| Workflow | parse → resolve company → resolve founders → plan retrieval per claim type → fetch → compare → corroborate gaps via web → validate → write |
| Verification | Every claim maps to a typed comparator against a specific field path, carrying entity ID + as-of date |
| Failure modes | Ambiguous name; stealth or new company absent from the graph; LLM mis-extraction; payload or timeout issues; news-only claims |
| MVP | 6 claim types: founded year, HQ, headcount, total funding / last round (amount, lead, date), founders and their prior employers, hiring activity |
| Not a wrapper because | Retrieval is decided per claim; the IDs drive subsequent calls; conflicts are computed rather than generated |

#### C3 — Career-Claim Verification

| Field | Detail |
|---|---|
| Request | A pasted résumé text block |
| Deliverable | Per-role verification (employer resolved to an ID; title similarity; date overlap), a discrepancy list, and a confidence score |
| Failure modes | Common names; career gaps; the employer renaming itself; profile not in the dataset |
| Demo caveat | A real person's profile is needed. Use a teammate's own profile (with consent) or a well-known founder, with a *team-authored* altered résumé that is explicitly labeled as a test fixture. |

#### C2 — KYB Screen

| Field | Detail |
|---|---|
| Request | Onboarding JSON/text: legal name, website, claimed directors, claimed size, country |
| Deliverable | Risk report: rules fired (domain mismatch, company age < N, headcount ≪ claimed, directors not found at company, adverse news), a risk band, and a suggested credit limit |
| Limitation | No registry or sanctions data. The output is a *signal* report, and it must say so. |

---

## PART E — Feasibility Gate

| ID | Status | Reason / blocker | Mitigation |
|---|---|---|---|
| C1 | **PASS** | All critical endpoints are enabled and were exercised live | Narrow fields; retries |
| C3 | **PASS** | Person Search is enabled and the employment history includes IDs and dates [V] | Use a consented or public profile and a labeled fixture |
| C2 | **PASS** | Feasible, but verdicts are proxies | Frame the output as "risk signals" |
| C4 | PASS | Feasible | — |
| C5 | PASS | Feasible | — |
| C6 | CONDITIONAL | PDF/OCR parsing adds risk; Crustdata is not central | Use text invoices only |
| C7 | PASS | Feasible | — |
| C8 | PASS | Feasible | — |
| C9 | PASS (degraded) | Email→person identify is **disabled** (`/batch/person/identify`) [V] | Domain → company only |
| C10 | CONDITIONAL | Must never send; value is draft-only | — |
| C11 | PASS | Feasible | Ship as a feature of C1 |
| C12 | CONDITIONAL | Needs a host workflow to show "finished work" | Embed as a component of C1 |
| C13 | CONDITIONAL | No shipment, BOM, or customs data in Crustdata | — |
| C14 | CONDITIONAL | Valuation coverage is sparse and unverified | — |
| C15 | **FAIL** | Watcher is async (≥1h cadence; first run is a baseline). Access is confirmed via preview [V], but it still can't show request→finished work in 2 min | A smaller version could use `preview:true` only — but that is not a finished deliverable |

---

## PART F — Weighted Scoring Matrix (base weights)

Weights: Autonomy 20 · Crustdata 15 · Integrity 15 · Feasibility 15 · Robustness 10 · Demo 10 · TechDiff 5 · Novelty 5 · Scope risk 5.

| Rank | ID | Auto | Crust | Integ | Feas | Robust | Demo | Tech | Novel | Risk | **Score** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | C1 | 9 | 9 | 9 | 8 | 8 | 9 | 8 | 7 | 7 | **85.0** |
| 2 | C3 | 8 | 8 | 9 | 8 | 8 | 9 | 7 | 6 | 7 | **80.5** |
| 3 | C2 | 8 | 8 | 7 | 8 | 9 | 8 | 7 | 7 | 8 | **78.5** |
| 4 | C5 | 8 | 7 | 8 | 8 | 8 | 7 | 7 | 6 | 8 | 76.0 |
| 5 | C4 | 8 | 9 | 7 | 8 | 7 | 7 | 6 | 3 | 8 | 74.5 |
| 6 | C9 | 8 | 7 | 7 | 8 | 7 | 6 | 6 | 4 | 8 | 71.0 |
| 7 | C7 | 8 | 7 | 7 | 7 | 7 | 7 | 6 | 6 | 7 | 71.0 |
| 8 | C8 | 8 | 8 | 7 | 7 | 6 | 7 | 6 | 4 | 7 | 70.5 |
| 9 | C11 | 7 | 7 | 6 | 7 | 7 | 6 | 8 | 8 | 6 | 68.0 |
| 10 | C6 | 7 | 6 | 7 | 6 | 7 | 7 | 7 | 6 | 6 | 66.0 (COND) |
| 11 | C10 | 7 | 7 | 6 | 8 | 6 | 6 | 5 | 3 | 8 | 65.5 (COND) |
| 12 | C12 | 5 | 6 | 8 | 6 | 7 | 5 | 9 | 8 | 5 | 63.0 (COND) |
| 13 | C14 | 7 | 7 | 5 | 5 | 5 | 7 | 7 | 7 | 4 | 60.5 (COND) |
| 14 | C13 | 6 | 5 | 6 | 6 | 6 | 6 | 6 | 6 | 5 | 58.0 (COND) |
| — | C15 | 5 | 8 | 7 | 4 | 6 | 4 | 7 | 7 | 3 | 57.0 **FAIL** |

**Score justifications (top five):**

**C1 (85.0)**
- **Autonomy 9:** free text in, finished memo out, with no human step.
- **Crust 9:** the company and person graphs plus the ID join are the core of the product.
- **Integrity 9:** typed comparators and as-of dates. It is not 10 because news links are redirect URLs.
- **Feasibility 8:** six claim types and roughly 8 API calls per run. The extraction prompt is the main work.
- **Robustness 8:** ambiguity, nulls, and contradictions arise naturally.
- **Demo 9:** a red/green claim table is instantly legible.
- **Tech 8:** the resolver, comparators, and citation validator.
- **Novelty 7:** Harmonic, Affinity, and PitchBook exist, but claim-level *contradiction* reports with provenance are uncommon in hackathon builds.
- **Risk 7:** enrich payload size and LLM extraction.

**C3 (80.5)**
- Integrity 9: employment dates and IDs are exact.
- Crust 8: person side only.
- Novelty 6: background-check products such as Checkr exist.
- Risk 7: needs a real-person fixture.

**C2 (78.5)**
- Integrity 7: absence of evidence is not proof of a shell company, and there is no registry data.
- Robustness 9: the product's purpose is handling inconsistent inputs, so this criterion is its strongest.

**C5 (76.0)**
- A sound workflow, but it largely duplicates C2 with weaker data needs.

**C4 (74.5)**
- Novelty 3: the most common build.
- Integrity 7: "fit" is subjective.

---

## PART G — Detailed Analysis of the Top Five

### G.1 Agentic depth (which of the 12 stages are essential for the MVP)

| Stage | C1 | C3 | C2 | C5 | C4 |
|---|---|---|---|---|---|
| Request interpretation (LLM → typed schema) | ✔ | ✔ | ✔ | ✔ | ✔ |
| Task decomposition (claim → tool plan; deterministic map) | ✔ | ✔ | ✔ | ✔ | light |
| Entity resolution / disambiguation | ✔✔ | ✔✔ | ✔✔ | ✔ | light |
| Retrieval | ✔ | ✔ | ✔ | ✔ | ✔ |
| Evidence reconciliation (graph vs web) | ✔✔ | ✔ | ✔ | ✔ | — |
| Decision under uncertainty (status taxonomy) | ✔ | ✔ | ✔ (risk band) | ✔ (approve/reject) | ranking |
| Rule checking | ✔ (comparators) | ✔ | ✔✔ | ✔✔ | — |
| Tool execution | ✔ | ✔ | ✔ | ✔ | ✔ |
| Verification of output (citation validator) | ✔ | ✔ | ✔ | ✔ | weak |
| Failure recovery | ✔ | ✔ | ✔ | ✔ | ✔ |
| Finished artifact | memo | report | risk report | PO decision | shortlist |
| Audit trail | ✔ | ✔ | ✔ | ✔ | ✔ |

**Smallest credible architecture: one orchestrator, not multi-agent.** It is a deterministic pipeline with two LLM calls (extract, write) and one optional LLM call (disambiguation tie-break). Separate agents would add coordination cost and no measurable benefit within 5 hours [I].

**Checks for C1:**

| Check | C1 answer |
|---|---|
| Does it take actions? | Yes: 6–10 real API calls, chosen per claim. |
| Do results drive the next steps? | Yes: the resolved `crustdata_company_id` drives the people and job queries, and the founders' `past[]` employer IDs drive prior-employer verification. |
| Does it detect contradictions? | Yes. |
| Does it recover from failure? | Yes: retry and narrowing, plus an ambiguity halt. |
| Is it observable? | Yes: a live trace in the terminal. |

### G.2 Data integrity design (C1, applies to C3 and C2 too)

**Evidence ledger record** (mapped to observed fields):

```json
{
  "claim_id": "C4",
  "claim_text": "We raised a $200M Series D led by TCV",
  "claim_type": "last_round",
  "entity": {"crustdata_company_id": 631990, "name": "Mercury", "domain": "mercury.com"},
  "endpoint": "POST /company/enrich",
  "field_path": "funding.milestones[0]",
  "observed": {"round_type":"series_d","amount_usd":200000000,"lead_investors":"TCV","date":"2026-05-20"},
  "source_ref": "https://www.crunchbase.com/funding_round/mercury-technologies-series-d--cb331e91",
  "corroboration": [{"endpoint":"POST /web/search/live","title":"Mercury secures $200m Series D at $5.2bn valuation","url":"<google redirect url, labeled>","retrieved_at":"..."}],
  "retrieved_at": "2026-10-31T11:20:03Z",
  "data_as_of": "2026-05-20",
  "comparator": "amount_within_5pct AND lead_investor_in_set AND round_type_eq",
  "status": "VERIFIED",
  "kind": "observed"
}
```

Notes on this record:
- The `source_ref` link is built from the Crunchbase permalink the API returned, so it is a constructed URL. Store the raw `permalink` value and mark the URL as derived [I].
- `retrieved_at` is when **we** fetched it. `data_as_of` comes from the response: `metadata.updated_at` for people, the milestone `date`, or the last `headcount.timeseries` date.
- **Observed vs inferred:** `kind = observed | inferred`. Inferred items (e.g. "team is engineering-heavy, 22% eng") must reference the observed ledger rows they derive from.

**Anti-hallucination guards:**
1. The writer LLM receives *only* the ledger.
2. A post-validator extracts every number or proper noun in the memo and requires a matching ledger value. Otherwise that sentence is dropped and logged.
3. Any claim with no evidence is shown as **UNVERIFIABLE** and never silently omitted.

**Entity resolution:**
- domain → identify (exact).
- Name → identify (≤25 candidates) → deterministic re-rank on: domain token overlap, industry keyword match, |year_founded − claimed|, headcount-range compatibility, and whether claimed founder names appear in Person Search with `current.crustdata_company_id` equal to the candidate.
- If the margin between #1 and #2 is below a threshold, **halt with an AMBIGUOUS memo listing the candidates.** This is honest failure, and it is itself a robustness demo.

### G.3 Engineering feasibility (C1, team of 4)

| Block | Engineer-min |
|---|---|
| Setup, key, curl validation of 5 endpoints (REST shapes vs MCP) | 60 |
| HTTP client (headers, backoff, 429/timeout, field narrowing, disk cache) | 60 |
| Data models (Claim, Evidence, Ledger) + claim-type→plan map | 45 |
| Extraction prompt + schema validation | 60 |
| Entity resolver + re-ranker + ambiguity halt | 75 |
| Comparators for 6 claim types | 90 |
| Web corroboration | 30 |
| Memo writer + citation validator | 60 |
| CLI live trace (rich) + HTML render | 45 |
| Test on 6–8 companies, fix | 90 |
| Demo record + README + submit | 60 |
| **Total** | **≈ 675 engineer-min ≈ 11.3 h** |

With four people, about 4 h × 4 = 16 h is available. After roughly 30% integration and debug overhead, about 11 h is usable, so **the plan is tight but feasible.**

**Delivery risks:**
- **Hardest component:** claim extraction plus comparator coverage, especially the founders/prior-employers comparator.
- **First cut:** web corroboration, then HTML (keep markdown only), then the hiring claim type.
- **Minimum acceptable demo:** domain + 4 claim types (founded, HQ, headcount, last round), each with VERIFIED / CONTRADICTED status and ledger rows.
- **Most dangerous dependency:** `/company/enrich` payload and timeouts [V].
- **Fallback:** an on-disk JSON cache of every API response, replayable with `--replay`. It is used only for the stage, never presented as live.
- **Usable end-to-end by 1:00 PM:** walking skeleton by 12:00, working by 1:00.

### G.4 Risks and demo potential (all five)

| ID | Biggest risk | Demo potential |
|---|---|---|
| C1 | Extraction misses or misparses claims | Very high: red/green claim board plus the Mercury ambiguity |
| C3 | Fixture ethics; common-name ambiguity | High |
| C2 | Verdicts look arbitrary without registry data | High |
| C5 | Looks like C2 with extra steps | Medium |
| C4 | Indistinguishable from other teams | Medium |

### G.5 Competitive differentiation

This section is analyst knowledge and was **not re-verified today**.

| Area | Existing products |
|---|---|
| Startup data | Harmonic, Affinity, PitchBook, Crunchbase (data/CRMs) |
| Document Q&A | Hebbia, AlphaSense |
| KYB | Middesk, Persona |
| Background checks | Checkr, HireRight |
| AI sourcing | Juicebox/PeopleGPT |
| Enrichment workflows | Clay |

- **Routine and easy to copy:** "enrich a company and summarize it", "find people matching a JD".
- **Uncommon, and needs real execution:** claim-level contradiction detection with ID-anchored provenance, honest UNVERIFIABLE handling, and visible disambiguation.
- **What Crustdata uniquely enables here:** an ID-joined person↔company graph (founders' past employers already carry company IDs [V]) and dated funding milestones, all in one API.

### G.6 Adversarial review (top five)

#### C1

| # | Judge's question | Answer |
|---|---|---|
| 1 | Is it just a wrapper? | No. Comparators and resolution are code, and the LLM only extracts and phrases. Show the ledger. |
| 2 | Is Crustdata essential? | Yes. Funding milestones, headcount, and the founder↔company ID join come only from the graph. |
| 3 | What if data is incomplete? | The claim is marked UNVERIFIABLE with the reason "field null at as-of date". |
| 4 | What about similar names? | Show the Mercury 25-way ambiguity and the re-rank or halt. |
| 5 | How are claims verified? | Typed comparators with tolerances. |
| 6 | What about a wrong intermediate decision? | Resolution confidence is printed, and the founder cross-join acts as a second check. If they disagree, the agent halts. |
| 7 | Does it need a human? | No. |
| 8 | Which parts are execution vs generation? | Retrieval and comparison are execution. Only the summary prose is generated. |
| 9 | Weakest component? | Extraction. Mitigate with a schema, few-shot examples, and showing the extracted claims in the trace. |
| 10 | Live-demo failure? | API timeout → retries and cache. |
| 11 | Is the critical path feasible? | Yes, if the scope stays at 6 claim types. |
| 12 | Simplest competitor? | "Enrich + LLM summary". Ours beats it on contradictions and provenance. |

**C3**
- Same engine.
- Weak points: needs a real person's data (mitigate: consented teammate or public founder, labeled fixture). Title similarity is fuzzy (mitigate: use the `normalized_title` field [V] plus a date-overlap rule).
- Simplest competitor: "LinkedIn lookup". Ours computes date and title discrepancies.

**C2**
- Weak point: "how do you know it's a shell?" We don't; we report weighted signals with explicit rules and say registry checks are out of scope.
- Fatal-flaw check: not fatal, but integrity is capped.

**C5**
- Weak point: Crustdata provides only vendor existence and profile. The policy logic is generic.

**C4**
- Weak point: "why is this better than the Crustdata search UI?" The answer is thin. Fit scoring is unverifiable.

---

## PART H — Sensitivity Analysis (internal, not official)

| Scenario | Auto | Crust | Integ | Feas | Robust | Demo | Tech | Novel | Risk |
|---|---|---|---|---|---|---|---|---|---|
| Base | 20 | 15 | 15 | 15 | 10 | 10 | 5 | 5 | 5 |
| A Execution-first | 25 | 10 | 10 | 25 | 10 | 15 | 0 | 0 | 5 |
| B Verification-first | 15 | 20 | 30 | 10 | 15 | 5 | 0 | 0 | 5 |
| C Differentiation-first | 15 | 10 | 10 | 15 | 10 | 10 | 15 | 15 | 0 |

| Rank | Base | A Exec | B Verif | C Diff |
|---|---|---|---|---|
| 1 | C1 85.0 | C1 85.5 | C1 86.5 | C1 83.0 |
| 2 | C3 80.5 | C3 82.0 | C3 83.0 | C3 77.5 |
| 3 | C2 78.5 | C2 80.0 | C2 78.5 | C2 77.0 |
| 4 | C5 76.0 | C5/C4 77.5 | C5 77.5 | C5 73.5 |
| 5 | C4 74.5 | — | C4 77.0 | C11 71.0 |

**Stable top three across all scenarios: C1, C3, C2.** The C1 lead ranges from 4.5 to 5.5 points. The ranking is not an artifact of the weights.

---

## PART I — Final Three Recommendations

| | **Primary: C1 Claim-Verified Startup Diligence** | **Backup: C3 Career-Claim Verification** | **Alternative: C2 KYB Signal Screen** |
|---|---|---|---|
| User | VC analyst | Outcome-paid recruiter | Fintech onboarding/risk |
| Input | Pitch email/one-pager text (+ optional domain) | Résumé text | Onboarding form text/JSON |
| Output | Memo + claims table + ledger + trace | Per-role verification report + ledger | Risk report: rules fired, band, credit-limit suggestion + ledger |
| Why it matters | Inbound decks are full of inflated claims; first-pass diligence is hours of manual cross-checking | Résumé fraud; recruiters are paid on outcomes | Shell/fake merchants |
| Crustdata | Identify, Enrich, Person Search, Job Search, Web Search | Person Search/Enrich, Identify | Identify, Enrich, Person Search, Web Search |
| Architecture | Shared engine: parse → resolve → plan → fetch → compare → validate → write | same; swap the claim schema | same + rule engine |
| Excluded | Watcher, contact data, multi-agent, UI framework, valuation/revenue claims (web-only, flagged) | Education verification (optional), contact checks | Registry, sanctions, credit bureau |
| Score / confidence | 85.0 / med-high | 80.5 / medium | 78.5 / medium |
| Pivot cost from C1 | — | ~60 min (new extractor schema + 3 comparators) | ~75 min (rule table) |

---

## PART J — Implementation Blueprint (C1)

```
User request (free text pitch [+domain])
  │
  ▼  [LLM, structured output]  Request parsing → {company_name, domain?, founders[], claims[{id,type,value,raw}]}
  │  [code] schema validation; unknown claim types → "out_of_scope" list (shown, not dropped)
  ▼  [Crustdata] Entity resolution
  │     domain? → /company/identify {domains}  (free)
  │     else    → /company/identify {names} → [code] re-rank (industry, founded, size, domain token)
  │              → [Crustdata] /person/search founders × candidate ids → [code] pick / HALT(AMBIGUOUS)
  ▼  [code] Retrieval plan: claim.type → (endpoint, fields)
  ▼  [Crustdata] Retrieval (cached, retried, narrow fields)
  │     /company/enrich  fields: basic_info, funding (milestones, totals), headcount (total, growth_percent, by_role_percent) — drop timeseries
  │     /person/search   current.company_id = X AND seniority in [CXO, Owner / Partner]
  │     /job/search      company id = X, aggregations count + group_by category (limit 0–3)
  │     /web/search/live news  — only for claims the graph can't cover or CONTRADICTED ones
  ▼  [code] Evidence normalization → ledger rows (entity id, field path, observed, as-of, retrieved_at, source_ref)
  ▼  [code] Comparators → VERIFIED / PARTIAL / CONTRADICTED / UNVERIFIABLE
  ▼  [LLM] Memo writer (input = ledger only; must cite [C#])
  ▼  [code] Output validation: every number/proper noun ∈ ledger; else strip + log
  ▼  Deliverables: out/<run>/memo.md (+html), ledger.json, trace.jsonl, raw/ (API responses)
```

**Claim types and comparators (MVP):**

| Type | Source field [V] | Rule |
|---|---|---|
| founded_year | basic_info.year_founded | equal; ±1 → PARTIAL |
| hq | person/company HQ location fields (enrich `locations` [D]) | normalized city/country match |
| headcount | headcount.total (+ last timeseries date) | within ±15% VERIFIED; ±15–40% PARTIAL; else CONTRADICTED |
| growth | headcount.growth_percent.yoy | within ±10 pts |
| funding_total | funding.total_investment_usd | within ±10% |
| last_round | funding.milestones[] | round_type eq, amount ±5%, lead ∈ lead_investors |
| founder_identity | person/search current employer id = X | name fuzzy ≥0.9 + seniority CXO/Owner |
| founder_prior_employer | person.past[].name / crustdata_company_id | identify(prior company) id ∈ past ids |
| hiring | job/search count / group_by | ≥ claimed open roles; category share |

**Error handling:**

| Situation | Handling |
|---|---|
| 429 / timeout / connection drop | Retry ×3 with exponential backoff + jitter, then narrower fields, then mark the dependent claims UNVERIFIABLE (reason: tool_error) |
| `matches: []` | Not found in the graph → stealth or new company → memo says so and switches to web corroboration |
| Null field | UNVERIFIABLE (field_null) |
| `crustdata_company_id: 0` in past employment | Fall back to name match plus identify |
| Malformed or garbled input | The extractor returns the claims it could parse; zero claims → a "no verifiable claims" memo |
| Budget guard | Credit counter from the response; abort above N credits per run (a small C11 touch) |

**MVP boundaries:**
- **In scope:** CLI, 6 claim types, ledger, validator, cache/replay.
- **Out of scope:** web UI, Watcher, MCP-server packaging (stretch goal if time remains), multi-company batch, valuation/revenue verification beyond "news-corroborated" status.

**Stack [I]:**
- Python 3.11, `httpx`, `pydantic`, `rich`, `rapidfuzz`.
- One LLM SDK, using whichever key the team has (e.g. Claude Sonnet).
- Direct REST to `https://api.crustdata.com` with the required headers.

---

## PART K — Two-Minute Demo Script (C1)

**Scenario.** Use a fresh pitch email for a real company *not* used in development, chosen at recording time. The team writes the text and plants 2 false claims, and **the video says out loud that they were planted**, e.g. inflated headcount and a wrong lead investor. Give only the company name, no domain, and pick a name with collisions so the resolver is exercised.

**Before recording:** rehearse on 6–8 other companies. The verified behavior so far is the Mercury probes above. Everything else is *expected* behavior until tested.

| Time | Screen | Proof shown |
|---|---|---|
| 0:00–0:12 | Problem: "Analysts burn hours cross-checking pitch claims." Paste the pitch email into the CLI. | Raw unformatted input |
| 0:12–0:30 | Trace: 7 claims extracted (typed). Identify by name → **N candidates, all confidence 1.0** → re-rank → founder cross-check confirms id `X`. | Disambiguation visible |
| 0:30–1:00 | Live tool calls stream (enrich, person search, job search, web news), each with credits and latency | Real execution |
| 1:00–1:25 | Complication: enrich times out → retry with narrower fields succeeds; one claim has a null field → UNVERIFIABLE | Robustness |
| 1:25–1:50 | Memo opens: claims table with ✅ / ❌ / ⚠. Click a CONTRADICTED row → ledger entry with entity id, field path, observed value, as-of date, source link | Data integrity |
| 1:50–2:00 | "Every sentence cites a ledger row; uncited numbers are stripped by the validator." Show the validator log line. | Anti-hallucination |

**Success conditions:**
- Both planted claims show CONTRADICTED with correct evidence.
- At least 3 claims show VERIFIED.
- Zero uncited numbers in the memo.
- The run completes in under 90 seconds.

---

## PART L — Five-Hour Execution Plan

The plan starts at 11:00, because 30 minutes of the window have already passed. Default team of four:
- **A** — lead / integrator
- **B** — data / API
- **C** — LLM / extraction
- **D** — output / demo

| Time | A (integrator) | B (Crustdata client) | C (LLM) | D (output/demo) |
|---|---|---|---|---|
| 11:00–11:30 | Repo, models (`Claim`, `Evidence`, `Ledger`), pipeline skeleton with stubs | curl the 5 endpoints via REST; save sample JSON to `fixtures/`; confirm shapes match the MCP | Extraction schema + prompt; 3 test pitches | Pick 8 test companies (incl. ambiguous names); draft README |
| 11:30–12:30 | Resolver + re-ranker + halt | HTTP client: headers, retry/backoff, narrow fields, cache/replay | Extractor wired; validation; out_of_scope bucket | Rich CLI trace; memo markdown template |
| **12:30 checkpoint** | **Walking skeleton end-to-end on 1 company (domain input, 3 claim types)** | | | |
| 12:30–1:30 | Comparators: headcount, funding, last_round, founded | Person search founders + prior-employer join; job search aggregation | Memo writer constrained to ledger; citation validator | HTML render; ledger viewer |
| **1:30 checkpoint (mentor)** | **All 6 claim types; name-only input works; 3 companies pass** | | | |
| 1:30–2:30 | Integrate + fix; ambiguity path | Web news corroboration (cut first if late) | Harden extraction on messy inputs | Run the 8-company test matrix; log failures |
| **2:30 CODE FREEZE (features)** | | | | |
| 2:30–3:05 | Bug fixes only | Warm cache for the demo company + replay test | README: architecture, ledger schema, limitations | **Record the demo** (2 takes), trim to ≤2:00 |
| 3:05–3:20 | Final push; tag release | Verify the clean clone runs | Verify the video uploads and plays | Submit |
| 3:20–3:30 | Buffer | | | |

**Safeguards:**
- Push to the remote every 30 minutes.
- `.env.example` only; never commit the API key.
- Submit by 3:20.
- Keep a `--replay` cache for the stage finals at 5:30.

**Smaller teams:**
- **Solo:** cut web corroboration, HTML, and hiring. Use domain input plus a single re-rank rule. Freeze at 2:15.
- **Two people:** A+B merge (pipeline + client) and C+D merge (LLM + output).

---

## PART M — Final Decision

**Choose C1, the Claim-Verified Startup Diligence Agent.** It turns the judging rubric (end-to-end execution, verifiable citations for every claim, messy inputs, a clear demo) into the product itself.

The data it needs was confirmed live on your account today:
- dated, sourced funding milestones;
- headcount and growth figures;
- founder employment histories already joined to company IDs;
- a 25-way name collision that makes the identity graph's value visible on screen.

It is the top choice under every weighting tested, and its engine converts to the backup (C3) or the alternative (C2) in about an hour if needed.

**Smallest credible winning implementation:**
- A Python CLI that takes a messy pitch.
- The pitch is resolved to a `crustdata_company_id`, with a visible disambiguation step.
- Four calls: `company/enrich` (narrow fields), `person/search`, `job/search`, and one `web/search`.
- Six claim types checked by deterministic comparators.
- A ledger with entity ID, field path, observed value, as-of date, and source per claim.
- An LLM memo that is only allowed to cite ledger rows, enforced by a validator.
- Retry and replay for resilience.

**Do not build:** a web UI, Watcher, contact data, or multi-agent orchestration.

---

## PART N — Infrastructure for Agents: Ideas, Verification, Scoring

Handbook text [H]: *"Infrastructure for agents: Building missing developer blocks such as long-term memory, rule-checkers, CRM bindings, or cryptographic execution trails."*

### N.0 The constraint that shapes every infra idea

The judges score **End-to-End Execution**: "does the agent take a request all the way to finished work". The deliverable must show "a request it has never seen all the way to finished work" [H]. A developer block on its own produces no finished work.

**Rule applied below [I]:** every infra PS ships as **(block) + (thin reference agent that completes one real task through the block)**. The block must sit on the identity graph, using `crustdata_company_id` / `crustdata_person_id` as keys, to satisfy the mandatory-integration rule [H].

### N.1 Live capability probes for the infra ideas (31 Oct, roughly 11:15–11:30) [V]

| # | Probe | Result | Implication |
|---|---|---|---|
| P1 | `company/identify` domains `mercury.com`, `stripe.com`, `www.stripe.com`, `https://stripe.com/in` | All Stripe variants → **631394**; mercury.com → **631990** | Domain normalization is done server-side, so domain is the safest canonical key. Powers I1, I2. |
| P2 | `company/identify` LinkedIn URLs `https://www.linkedin.com/company/mercuryhq`, `linkedin.com/company/stripe/` | → 631990, 631394 (with or without scheme, trailing slash) | URL variants collapse too |
| P3 | `company/identify` names `["Mercury"]` | **25 different companies, all `confidence_score: 1.0`** | The confidence score cannot disambiguate. An agent picking `matches[0]` is wrong most of the time. |
| P4 | `company/identify` names `["Mercury Technologies"]` (the fintech's legal name) | Top hits are unrelated IT/security firms at 1.0. **The real Mercury (631990) appears only at 0.6, tied with Mercury Insurance, Mercury Systems, Dell Technologies, Honeywell Technologies** | Legal-name and alias resolution is unreliable. A resolver layer with context signals is genuinely missing infrastructure. |
| P5 | `person/search` `basic_profile.name = "Jason Zhang"` | **1,725 matches**; one result has current `crustdata_company_id: 0` (unlinked employer) | Person resolution needs a company anchor. Unlinked employers exist. |
| P6 | `company/enrich` with dot-path fields (`headcount.total`, `funding.total_investment_usd`, `funding.last_round_type`, `funding.last_fundraise_date`) | Tiny payload, **2 credits**: Stripe headcount 16,641; total funding $10.44B; last round `secondary_market` on 2026-03-09 | Cheap targeted refresh, so a memory/freshness layer is affordable (I4) |
| P7 | `watch_create` entity watch on 631990 tracking `headcount.total` changed or `news` added, `preview:true` | `can_create: true`, `resolved: 1`, `per_notification: 5` credits; no watch created, 0 credits | Watcher is usable for invalidation, but events are async (≥hourly cadence, baseline first run) |
| P8 | Every MCP response | Carries `credits.spent_this_call`, `request_ids[]`, `balance_estimated` | Per-call cost and request ID are available for a signed trail and budget governor (I3, I6). REST equivalents (headers?) are **[U]** — check with curl. |
| P9 | Transport | About 6 of 19 calls dropped the connection, including free endpoints; **dropped calls were still charged** (balance fell by about 6 credits with no data returned) | An idempotent cache plus spend reconciliation is a real need (I6). Every infra idea must include retries. |

Probe spend so far is about 12 credits; the balance is about 15,188.

### N.2 Candidate infra problem statements

| ID | Block | Reference agent (finished work) | Crustdata capability used (status) | Why it's "missing infrastructure" |
|---|---|---|---|---|
| **I1** | **Resolve-before-Act entity gateway**, an MCP server exposing `resolve_company(mention, context)` / `resolve_person(name, company_hint)`. It returns `RESOLVED(id, evidence) / AMBIGUOUS(candidates, why) / NOT_FOUND`, re-ranking identify candidates on domain, LinkedIn, industry, founding year, size, and the person↔company join. | An account-list reconciliation agent: "Here are 40 company mentions from meeting notes, give me the canonical list" | identify domain/URL/name (P1–P4 [V]); person search with company-id join (P5 [V]) | P3/P4 show the raw API returns undifferentiated 1.0 scores. Every agent that acts on entities needs this. |
| **I2** | **Canonical CRM binding**: a local CRM (SQLite) whose primary keys are Crustdata IDs. Every write passes through resolve → dedupe → field-level provenance (source endpoint, as-of) → conflict log. | A messy lead CSV/notes (duplicates, typos, `www.`/`https://` variants, aliases) becomes a clean CRM plus a merge/conflict report | identify (25 per call, 30 rpm) [V]; dot-path enrich [V]; person search [V] | The handbook names "CRM bindings". Naïve CRM sync duplicates "Stripe", "stripe.com" and "Stripe Inc". |
| **I3** | **Claim firewall + cryptographic execution trail**: an MCP proxy in front of Crustdata. It logs every call (request, response SHA-256, request_id, credits, timestamps) into a hash-chained, Ed25519-signed log, and exposes `check_answer(text)`, which deterministically matches each number/entity in an agent's answer to logged evidence. It blocks or annotates unsupported claims. | A research Q&A agent: "Who founded Mercury, what have they raised, are they hiring engineers?" → answer + per-claim citations + signed trail + a `verify_trail` CLI anyone can run | all read endpoints; `request_ids` and `spent_this_call` (P8 [V]) | The handbook names "cryptographic execution trails". The judging asks for "verifiable citations for every claim" [H]. This block makes that property enforceable for any agent. |
| I4 | **Entity-keyed long-term memory with freshness**: facts stored per canonical ID with as-of and source; aliases resolve to the same memory; recall checks TTL, and stale facts are refreshed by a 2-credit dot-path enrich plus a diff; optional Watcher invalidation | A multi-session account assistant (session 2 uses a different alias and gets a memory hit plus a stale-fact refresh) | P1/P2 aliasing [V], P6 refresh [V], P7 Watcher [V-preview] | The handbook names "long-term memory". Hard to show in 2 min across sessions; the Watcher part can't fire live. |
| I5 | **Policy rule-checker for agent actions**: YAML policies (e.g. "targets must have 50–1000 employees, funded within 24 months, not on the customer list, not a competitor, no duplicate company") evaluated against Crustdata facts → ALLOW / DENY / NEEDS_DATA with evidence | A prospecting agent proposes 15 accounts → the guard filters them and explains (nothing is sent; compliant with [H] rule 4) | enrich `headcount.total`, `funding.last_fundraise_date` [V]; company search filters [D, not probed] | The handbook names "rule-checkers". A solid build, but its policy logic is generic. |
| I6 | **Agent-safe Crustdata client**: idempotent cache keyed on the request hash, retry/backoff, auto field-narrowing, null normalization, budget governor, charged-on-drop reconciliation | Same research agent, run under a budget | P6, P8, P9 [V] | Real pain (P9), but not "finished work" and it looks like plumbing |
| I7 | **Graph-grounded agent eval harness**: auto-generates questions with known answers from Crustdata ("CTO of X?", "founded year of Y?") and scores any agent on accuracy, citation validity and entity-confusion rate | Eval report for 2 agent configs | identify/enrich/person search [V] | Novel, but "request it has never seen → finished work" fits awkwardly |
| I8 | **Watcher→agent trigger bus**: Watcher events become queued agent tasks | Alert-driven research | P7 [V-preview] | Async; can't be demoed live |

### N.3 Feasibility gate

| ID | Status | Reason |
|---|---|---|
| I1 | **PASS** | Identify (free, 30 rpm) and person search are verified. Must ship with a reference agent to show finished work. |
| I2 | **PASS** | All calls verified. SQLite is local (allowed: "team's local environment" [H]). |
| I3 | **PASS** | All read calls verified. Hashing and signing are local, stdlib or `cryptography` [I]. The proxy pattern (Python MCP server calling REST) is standard but adds about 45 min. |
| I4 | **CONDITIONAL** | The live Watcher invalidation can't be demonstrated (async). Fallback: on-demand TTL refresh only. |
| I5 | **PASS** | Company-search filters are documented but not yet probed. Validate with a 0.03-credit call. |
| I6 | **CONDITIONAL** | Feasible, but by itself shows no finished work. Fold it into whichever PS you pick. |
| I7 | **CONDITIONAL** | The demo framing conflicts with the "request it has never seen" deliverable. |
| I8 | **FAIL** | Async events; no live end-to-end in 2 min. Simulating events would amount to fabricating output [H rule-spirit]. |

### N.4 Scoring matrix

Same criteria and weights as Part F. C1 is included for reference.

| Rank | ID | Auto 20 | Crust 15 | Integ 15 | Feas 15 | Robust 10 | Demo 10 | Tech 5 | Novel 5 | Risk 5 | **Score** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ref | C1 Claim-verified diligence | 9 | 9 | 9 | 8 | 8 | 9 | 8 | 7 | 7 | **85.0** |
| 1 | **I3** Claim firewall + signed trail | 8 | 8 | 10 | 7 | 8 | 9 | 9 | 8 | 6 | **82.0** |
| 2 | **I2** Canonical CRM binding | 8 | 9 | 8 | 8 | 9 | 8 | 7 | 6 | 8 | **81.0** |
| 3 | **I1** Resolve-before-Act gateway | 6 | 10 | 9 | 8 | 9 | 7 | 8 | 7 | 8 | **80.0** |
| 4 | I5 Policy rule-checker | 8 | 8 | 8 | 8 | 8 | 8 | 7 | 7 | 8 | 79.0 |
| 5 | I7 Eval harness | 7 | 8 | 8 | 7 | 6 | 6 | 8 | 8 | 7 | 72.0 (COND) |
| 6 | I4 Entity memory | 7 | 8 | 8 | 7 | 7 | 6 | 8 | 7 | 6 | 72.0 (COND) |
| 7 | I6 Safe client | 5 | 7 | 7 | 9 | 10 | 5 | 6 | 5 | 9 | 69.5 (COND) |
| — | I8 Trigger bus | 6 | 8 | 7 | 4 | 6 | 4 | 7 | 7 | 3 | 59.0 **FAIL** |

**Justifications:**

**I3 (82.0)**
- Integrity 10: every claim is mechanically bound to a hashed, signed API response, so a judge can re-verify offline.
- Demo 9: a "tamper with one byte → `verify_trail` fails" moment is instantly legible.
- Tech 9: an MCP proxy plus hash chain plus deterministic claim matcher.
- Feasibility 7: the proxy layer, signing and matcher are more surface area than C1.
- Risk 6: claim matching on free text is the hard part.
- Auto 8: finished work comes from the reference agent, not the block.

**I2 (81.0)**
- Robust 9: messy CSVs exercise exactly the "unformatted inputs" criterion.
- Crust 9: the IDs are the primary keys.
- Novel 6: dedupe/enrichment tools exist (e.g. Clay, CRM dedupe apps — analyst knowledge, not verified today).

**I1 (80.0)**
- Crust 10: the purest use of the canonical graph.
- Integrity 9: P3/P4 prove the need.
- Auto 6: a resolver alone is not finished work; the score depends on the reference agent.

**I5 (79.0)**
- Balanced, but the policy DSL is generic. Crustdata only supplies the facts.

**Lower-ranked ideas**
- I4, I6, I7 lose on demo and end-to-end.
- I8 fails the gate.

### N.5 Sensitivity analysis (same scenario weights as Part H)

| Rank | Base | A Execution-first | B Verification-first | C Differentiation-first |
|---|---|---|---|---|
| 1 | C1 85.0 | C1 85.5 | C1 86.5 | I3 83.0 = C1 83.0 |
| 2 | I3 82.0 | I2 82.0 | I1 85.0 | I1 78.5 |
| 3 | I2 81.0 | I5 80.0 = I3 80.0 | I3 84.5 | I2 77.5 |
| 4 | I1 80.0 | I1 77.5 | I2 83.5 | I5 77.0 |
| 5 | I5 79.0 | I6 71.0 | I5 80.0 | I7 73.0 |

**Stable infra top three:** I3, I2 and I1 are in the infra top four under every scenario. I3 is the most consistent, ranking #1 or #2 among infra ideas in three of four scenarios and tied #2/#3 in Execution-first. I2 wins on execution, I1 on verification, and I3 on differentiation.

### N.6 Recommended infra PS: hybrid **H1 = I3 (+ I1 inside) with C1 as the reference agent**

**H1 problem statement.** *"Verifiable Context Layer"*: an MCP server that any agent connects to instead of raw Crustdata. It provides:
1. `resolve_*`: Resolve-before-Act with AMBIGUOUS/NOT_FOUND states (I1).
2. Read tools that return narrowed, cached, retried data with a ledger ID per response.
3. `check_answer`: rejects any claim or number not backed by a ledger entry.
4. A hash-chained, Ed25519-signed execution trail, plus a `verify_trail` CLI.

The demo client is a thin diligence agent (C1) that takes a never-seen pitch to a memo **through** the layer.

| Weights | Base | A Exec | B Verif | C Diff |
|---|---|---|---|---|
| H1 (scores 9,9,10,7,8,9,9,8,6) | **85.5** | 83.5 | **88.0** | **85.5** |
| C1 alone | 85.0 | **85.5** | 86.5 | 83.0 |

**Honest read.** H1 and C1 are **tied within scoring noise** (±2.5). H1 wins if judges weight verification and originality. C1 wins if they weight raw execution. They share about 80% of their code: the ledger, resolver and validator are already C1 components. H1 adds:

| H1 addition | Estimated time |
|---|---|
| MCP server packaging (Python MCP SDK, stdio) | about 45 min |
| Hash chain + Ed25519 signing + `verify_trail` | about 30 min |
| `check_answer` as a standalone tool | already in C1 as the validator; about 15 min to expose |

**Decision rule.** Pick H1 if you have **3 or more people**, one of whom has built an MCP server or is comfortable with the Python MCP SDK. Otherwise build C1 and keep the ledger/trail as internal modules. You can still say "built as a reusable layer" in the demo.

**H1 architecture (deltas vs Part J):**

```
Reference agent (C1 diligence, LLM: extract + write)
   │  MCP (stdio)
   ▼
Verifiable Context Layer (MCP server)
   ├─ resolve_company / resolve_person   [Crustdata identify + person/search + code re-rank → RESOLVED|AMBIGUOUS|NOT_FOUND]
   ├─ get_company_facts / get_people / get_jobs / search_news   [REST, dot-path fields, cache, retry]
   │        └─ every response → ledger entry {ledger_id, endpoint, request, sha256(response), request_id?, credits, retrieved_at, data_as_of}
   ├─ check_answer(text)  [code: extract numbers/entities → match ledger values → SUPPORTED|UNSUPPORTED per span]
   └─ trail: append-only JSONL, entry_hash = sha256(prev_hash || canonical_json(entry)), Ed25519 signature over head
CLI: verify_trail run.jsonl → OK | BROKEN at entry N
```

**H1 two-minute demo (deltas vs Part K):**

| Time | Screen |
|---|---|
| 0:00–0:15 | "Agents act on the wrong entity and invent citations. We built the missing layer." |
| 0:15–0:35 | Agent asks for "Mercury Technologies" → layer returns **AMBIGUOUS** (the real fintech at 0.6, tied with Dell/Honeywell — P4) → agent supplies the founder's name → layer returns RESOLVED 631990 via the person↔company join |
| 0:35–1:10 | Agent completes the memo through the layer, with live tool calls and ledger IDs streaming |
| 1:10–1:30 | Agent's draft contains one unsupported number → `check_answer` blocks it → agent revises |
| 1:30–1:50 | Final memo with per-claim ledger citations |
| 1:50–2:00 | `verify_trail` → OK; flip one byte → **BROKEN at entry 7** |

**Infra-specific risks:**
- MCP SDK setup time. Fallback: expose the same functions as a Python library plus CLI. The handbook allows a CLI [H].
- `check_answer` false positives on paraphrased numbers ("$200M" vs 200000000). Normalize units in code.
- REST may not expose `request_id`. Fall back to the response hash only [U].

### N.7 Infra-only shortlist (if you commit to this theme)

| | Primary | Backup | Alternative |
|---|---|---|---|
| PS | **H1 / I3** Verifiable Context Layer (claim firewall + signed trail + resolver) | **I2** Canonical CRM binding | **I1** Resolve-before-Act gateway (+ reconciliation agent) |
| Base score | 85.5 (H1) / 82.0 (I3 standalone) | 81.0 | 80.0 |
| Confidence | Medium | Medium-high (simplest, most robust) | Medium |
| Smallest credible build | Python MCP server with 4 tools + signed JSONL trail + thin diligence client + `verify_trail` | SQLite CRM + resolver + dot-path enrich + merge/conflict report from a messy 30-row CSV | Resolver MCP tool + a 40-mention reconciliation run with AMBIGUOUS handling |
| First cut if late | MCP packaging (ship as CLI/library) | Person-level dedupe | Person resolution |

The team plan in Part L still applies. For H1, reassign **B** to own the MCP server and trail from 12:30, and move web corroboration to **C**.
