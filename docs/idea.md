My new recommendation: AgentGrid
The operating system for data-consuming agents
Agents share a live context graph, coordinate expensive API calls, and recover from failures—without repeatedly researching the same people and companies.

Think of it as Redis + a job scheduler + shared context for AI agents, specifically designed around Crustdata’s people and company graph.

The real problem
Suppose a company runs three autonomous agents:

A market research agent researches companies.
A recruiting agent looks for engineering leaders.
A partnership agent investigates potential partners.
All three investigate the same company.

Without coordination:

text

Research agent     → calls Crustdata for company profile
Recruiting agent   → calls Crustdata for company profile again
Partnership agent  → calls Crustdata for company profile again
They independently resolve the same company, repeat searches, consume credits, and maintain separate copies of context. If one agent crashes halfway through a long task, it may start again and repeat calls.

Now imagine hundreds of agents. The problem is no longer “can an LLM understand JSON?” It is:

How do we coordinate autonomous agents around shared real-world entities, limited API budgets, and long-running work?

That is a genuine infrastructure problem.

What AgentGrid does
Agents don’t call Crustdata directly. They ask AgentGrid for the context they need.

text

                 ┌───────────────────┐
                 │  Research agent   │
                 └─────────┬─────────┘
                           │
                 ┌─────────▼─────────┐
                 │     AgentGrid     │
                 │                   │
                 │ • Identity graph  │
                 │ • Shared context  │
                 │ • API scheduler   │
                 │ • Budget control  │
                 │ • Job recovery    │
                 └─────────┬─────────┘
                           │
                      Crustdata
                           │
                 ┌─────────▼─────────┐
                 │ Companies, people │
                 │ and job records   │
                 └───────────────────┘
The core capabilities
1. Shared entity context
All agents reference the same resolved company or person.

For example, if one agent researches a company using its domain, another agent can reuse the resolved company record instead of independently identifying it.

The graph is based on the actual records and identifiers Crustdata returns, not a made-up graph.

2. Duplicate-call prevention
If three agents request the same company enrichment at the same time:

text

3 agent requests → 1 Crustdata call → result shared with all 3
AgentGrid coalesces identical in-flight requests and can reuse a cached result when its freshness policy allows it.

3. Budget-aware execution
The user sets a budget for the whole job. AgentGrid decides whether it can safely make the next call.

For example:

text

Task: Analyze 10 companies
Budget: 100 credits

Search broadly → select matching companies → enrich selected companies
The system prioritizes calls that help complete the task, rather than blindly enriching every possible record.

Crustdata publishes endpoint-specific pricing and notes that some endpoints are priced by returned record, so budget enforcement must use the actual event plan and conservative limits—not guesses. 1

4. Crash recovery
AgentGrid checkpoints work. If a worker stops after completing part of the task, another worker resumes from the last recorded step.

Important engineering nuance: you cannot guarantee exactly-once billing for a remote API call if the worker crashes after the API processes a request but before its response is recorded. The demo should show recovery after a recorded checkpoint and explicitly handle uncertain calls.

The hackathon demo
Instead of demonstrating abstract infrastructure, give it a real job:

“Analyze these five companies for potential partnerships. For each, produce a company profile, relevant engineering leadership where available, and current job listings. Stay within the configured API budget.”

Three agents work on the same task:

Company agent: resolves and profiles each company.
People agent: finds relevant people associated with those companies.
Hiring agent: finds job listings.
They share one AgentGrid context rather than doing everything separately.

What judges see
text

TASK: Partnership intelligence for five companies

Agent 1: researching companies
Agent 2: researching people
Agent 3: researching jobs

Crustdata calls completed:  [actual count]
Duplicate calls avoided:    [actual count]
Budget consumed/estimated:  [actual amount]
Worker status:              running / recovered
Then:

Stop one worker during the demo.
Restart it.
Show the completed, already-recorded work was not repeated.
Produce the finished partnership brief locally.
No outreach to real people. The agents only use authorized APIs and produce a local artifact, as required by the challenge.

The “wow” moment
Run the same task twice:

Without AgentGrid: agents request data independently.
With AgentGrid: agents share resolved entities and identical API requests.
Show actual measured call counts and completion times. Don’t promise a percentage beforehand; let the demo show the difference