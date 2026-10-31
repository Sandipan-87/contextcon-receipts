# Receipts: high-level architecture

## 1. The whole system (draw this one)

```
                          ┌────────────────────────┐
                          │   RULEBOOK             │
                          │   STRATEGY.md          │
                          │   thesis · ± margins · │
                          │   guardrails · allowed │
                          │   actions · autonomy   │
                          └───────────┬────────────┘
                                      │ bounds every step
                                      ▼
┌──────────────┐   request   ┌────────────────────────────────────────────┐
│    USER      │────────────▶│                 AGENT                      │
│ (fund        │             │                                            │
│  analyst)    │             │ 1 UNDERSTAND   LLM reads thesis / pitch    │
│              │             │ 2 IDENTIFY     right company & people      │
│ • thesis     │             │                (refuses to guess)          │
│ • pitch      │             │ 3 INVESTIGATE  call Crustdata  ──────────┐ │
│ • 1 company  │             │ 4 JUDGE        code checks claims, scores│ │
│ • picks      │             │ 5 DECIDE       by rulebook               │ │
└──────▲───────┘             │ 6 ACT          board · email draft       │ │
       │                     └──────┬───────────────────────┬───────────┘ │
       │                            │ every call/decision   │             │
       │ results + proof            ▼                       ▼             ▼
       │                   ┌─────────────────┐    ┌───────────────┐  ┌────────────────────┐
       │                   │ SIGNED LEDGER   │    │ DEAL BOARD    │  │ CRUSTDATA API      │
       │                   │ (receipts)      │    │ OUTBOX        │  │ company · people · │
       │                   │ hash chain +    │    │ (never sent)  │  │ jobs · search      │
       │                   │ Ed25519 sig     │    └───────────────┘  └─────────┬──────────┘
       │                   └────────┬────────┘                                │ usage log
       │                            ▼                                         ▼
       │                   ┌─────────────────────────────────────────────────────────┐
       └───────────────────│ VERIFY (no LLM): recompute everything + Crustdata witness │
                           └─────────────────────────────────────────────────────────┘
```

## 2. The learning loop (draw this second)

```
   ┌──────────────┐   10 companies     ┌───────────────────┐
   │ AGENT scouts │──────────────────▶ │ AGENT SEALS its   │
   │ & scores     │                    │ prediction FIRST  │
   └──────▲───────┘                    └─────────┬─────────┘
          │                                      │
          │ better next round                    ▼
   ┌──────┴───────┐                    ┌───────────────────┐
   │ LEARN        │◀───────────────────│ YOU PICK          │
   │ re-weight    │  score: 7/10 → 9/10│ (blind)           │
   │ your taste   │                    └───────────────────┘
   └──────────────┘
```

## 3. One-line story for the judges
**Request → Identify → Investigate (Crustdata) → Judge (code) → Decide (rulebook) → Act → Seal → Verify**, plus a loop where **your picks teach it your taste.**

## Key words to write next to the boxes
- **LLM only reads language.** Facts, verdicts and maths are plain code.
- **Receipts:** every number links to a real API response.
- **Never guesses:** ambiguous company or person → human.
- **Bounded autonomy:** acts alone only above 80% confidence, after 10 decisions.
- **Tamper-proof:** change one byte → verify fails.
