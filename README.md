# Receipts

**A diligence agent whose every claim carries a verifiable receipt.**

Paste a founder's pitch. The agent extracts every checkable claim, resolves the company and people to Crustdata's canonical identity graph, checks each claim with deterministic comparators, and writes a diligence memo. Every sentence in the memo points to a **receipt**: a hashed, chained, Ed25519-signed record of the raw Crustdata API response. Anyone can re-check the memo later with `verify`. No LLM is involved in verification, and Crustdata's own usage log serves as an independent witness.

Built for ContextCon IIT Bombay (Crustdata × Y Combinator). Themes: Infrastructure for agents (cryptographic execution trails) and Investing (diligence).

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env        # add CRUSTDATA_API_KEY (ANTHROPIC_API_KEY optional)

python -m receipts run --pitch fixtures/pitches/01_mercury_planted_lies.txt
python -m receipts verify last --witness
python -m receipts tamper last && python -m receipts verify last    # watch it fail
```

## What it catches (live run on a team-written pitch with planted lies)

| Claim in pitch | Verdict | Evidence |
|---|---|---|
| "Mercury Technologies" (no domain) | resolved, not guessed | identify returns 25 candidates; the real fintech ranks only 0.6. Resolved to ID 631990 because founder Immad Akhund currently works there (person search). |
| "a team of 3,000 people" | ❌ CONTRADICTED | headcount 1,782 [receipt] |
| "$200M Series D led by Accel" | ❌ CONTRADICTED | Series D on 2026-05-20, lead investor TCV [receipt] |
| "Our CTO Max previously worked at Google" | ⚠️ UNSUPPORTED | Mercury has 6 people named Max; the one holding the CTO role is Maximilian Tagher, whose history shows Heyzap, no Google [receipt] |
| "hiring heavily in engineering" | ✅ VERIFIED | 331 of 1,752 open roles are Engineering [receipt] |

## How it works

```
pitch ─► extract claims (Claude structured output, or rule-based fallback)
      ─► resolve company: domain → identify; name → candidates → re-rank → founder cross-check → RESOLVED | AMBIGUOUS | NOT_FOUND
      ─► gather: /company/enrich (narrow fields), /person/search (role-aware person resolution), /job/search
      ─► every response: raw bytes → blobs/sha256/<hash>; ledger entry {request, response_hash, X-Request-ID, X-Credits-Used, prev_hash, entry_hash}
      ─► facts F1..Fn = JSON-pointer lookups into those raw responses
      ─► deterministic comparators → VERIFIED / PARTIAL / CONTRADICTED / UNSUPPORTED / UNVERIFIABLE
      ─► memo rendered purely from claims + facts → sealed with an Ed25519 signature over the chain head
```

| Step | Done by |
|---|---|
| Claim extraction | LLM (optional) or rules |
| Entity and person resolution, comparisons, arithmetic, memo text | Code |
| Facts | Crustdata REST API (`x-api-version: 2025-11-01`) |
| Verification | Code only |

## `verify` checks

1. **Chain:** every `entry_hash` recomputes; `prev_hash` links and sequence are intact.
2. **Signature:** Ed25519 over the chain head.
3. **Blobs:** every stored API response re-hashes to its ledger `response_hash`.
4. **Facts:** every fact re-resolves from the raw response to the same value.
5. **Claims:** every verdict reproduces by re-running the comparator.
6. **Report:** the memo re-renders byte-for-byte, so it contains no text or number without a source.
7. **Witness** (`--witness`): every call matches Crustdata's `/account/usage/events/{X-Request-ID}`: endpoint, request body, status, credits.

**Honest limitation:** the usage log proves each call happened with those parameters at that time, but it does not store response bodies. Whoever holds the signing key could rebuild and re-sign a fully rewritten chain. Mitigation: publish or commit the head hash when the memo is shared.

## Robustness built in

- **Ambiguous company names:** a decision entry lists the candidates, and the agent never guesses.
- **Ambiguous people:** "Max" is matched to the person who holds the claimed role, and the choice is logged.
- **Noisy data:** an unstable headcount series is reported as UNVERIFIABLE (data unstable) with an anomaly entry, never as CONTRADICTED.
- **Failed calls** are logged as receipts and retried with backoff.
- **Responses are cached by request hash,** because dropped connections are still billed.
- **Missing data** becomes UNVERIFIABLE with the reason.

## Layout

```
receipts/   proxy.py ledger.py facts.py resolve.py extract.py claims.py agent.py render.py verify.py __main__.py
fixtures/   test pitches (team-written; planted lies labeled)
runs/       one folder per run: ledger.jsonl, blobs/, facts.json, claims.json, meta.json, report.md, head.sig
docs/       hackathon handbook; planning documents
```
