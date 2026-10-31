# Fund strategy: the agent's rulebook

The agent acts on its own, but **only inside the rules in the YAML block below**. Every action it takes
records which rule allowed it, and the full text of this file is sealed into each run's ledger, so you can
always prove which rules were in force when a decision was made.

- **Thesis** (hard filters): the agent never scouts or recommends outside these.
- **Tolerances**: the ± margins used to judge a founder's claims against Crustdata data.
- **Guardrails** (hard): learning can never override these.
- **Autonomy**: when the agent may act without asking you.
- **Learning**: what it may learn from your decisions, and how far it may drift from the stated thesis.

Edit the values, not the keys. The defaults are a starting point for a fintech/payments seed–Series B fund.

```yaml
thesis:
  sectors: ["Financial Services"]          # Crustdata professional-network industry names
  hq_countries: ["India", "United States"]
  headcount: [20, 2000]
  last_round: ["seed", "series_a", "series_b"]
  raised_since: "2025-01-01"               # only companies that raised recently (active fundraising)

tolerances:                                # pitch-claim margins (percent)
  headcount: {verified: 15, partial: 40}
  total_funding: {verified: 10, partial: 30}
  round_amount: 5
  open_roles: {verified: 25, partial: 50}
  unstable_series_swing: 40                # week-on-week swing that marks headcount data unstable
  total_vs_series: 15

guardrails:
  pass_if_contradictions: 3                # this many contradicted claims -> PASS
  block_advance_if_contradicted: ["headcount", "total_funding", "round", "person_role"]
  ambiguous_entity: NEEDS_HUMAN            # never guess a company or person
  unstable_data: exclude_feature           # bad source data is never held against a company
  identity_collision: NEEDS_HUMAN          # a record that looks merged with another company goes to a human

decision_thresholds:
  advance_at_or_above: 0.60                # model probability you would pick it
  pass_at_or_below: 0.40                   # in between -> NEEDS_HUMAN

autonomy:
  auto_act_if_confidence: 0.80             # below this, queue for a human instead of acting
  min_decisions_before_auto_act: 10        # the agent defers to you until it has learned enough

actions:
  allowed: ["update_deal_board", "draft_email_to_outbox", "archive_signed_trail"]
  forbidden: ["send_external_email", "contact_any_person"]   # handbook rule 4

learning:
  expected_pick_rate: 0.5                  # before any decisions, assume you pick about half of each round
  prior_strength: 2.0                      # how strongly the stated thesis anchors learning
  weight_bounds: [-3.0, 3.0]
  prior_weights:                           # your stated preferences before any decisions
    growth_yoy: 0.8
    eng_hiring_share: 0.4
    open_roles: 0.2
    months_since_round: -0.3
    headcount: -0.2
    total_funding: 0.0
    stage: 0.0
    company_age: -0.1
```
