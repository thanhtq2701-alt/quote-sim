# quote-sim

A small Python simulator for learning how an AI-agent-assisted sales-quote workflow can keep human
approval, access control, evidence, and audit history explicit. It uses fake data and makes no real
LLM or external API calls.

## Problem

Sales quotes can be difficult to review when pricing evidence, permissions, and approval history
are kept in separate places. This learning project models a small quote workflow where line prices
retain their source evidence, roles have different permissions, and approval decisions are audited.
All data is fake; the simulated agent is rule-based and does not call an LLM or an external service.

## Workflow

The current draft workflow map is in [docs/workflow.md](docs/workflow.md) and is pending engineer
review.

## Design decisions

- Python 3.11 or newer; the current development machine has Python 3.14.10.
- The standard library is used for application code; pytest is the only project dependency.
- Currency is USD with two decimal places. Each line and the VAT amount use `ROUND_HALF_UP`; VAT
  is calculated from the sum of rounded line totals.
- Discounts are decimal fractions (for example, `0.10` means 10%); each line keeps its catalog
  unit-price snapshot.
- Discount limit and VAT rate are required `PricingPolicy` values. No application values have been
  chosen; tests use named values only to verify calculations.
- Permissions are a role-to-action matrix. Quote-specific separation of duties is checked with
  quote context in the approval phase.
- Auto-approval threshold and rule id are required `ApprovalPolicy` values. No application values
  have been chosen; tests use named values only to verify the boundary behavior.
- Audit entries use an injectable timezone-aware UTC clock. Rejected-quote revision and approved-
  quote editing remain unauthorized until the workflow authority is decided.
- Price lists are versioned fake JSON files with Decimal prices; each quote line keeps its source
  version, unit-price snapshot, and explicit discount-rule id. Submission requires valid evidence.
- The demo's named pricing and approval values are illustrative scenario inputs, not application
  defaults.
- Every action goes through `QuoteDesk`, which looks the actor's role up in the fake user
  directory (callers cannot claim a role) and audits creates, edits, and reads as well as
  workflow transitions. Margin is visible only to MANAGER and is rounded to cents like other
  money values.
- The simulated agent is rule-based. It understands plain-English requests (quantities as digits
  or words, short product names, plurals, one discount, a price-list version) and asks instead of
  guessing whenever something is unclear; a misunderstood request creates nothing.
- Discount input: `10%` or `10 percent` is a percentage; a number above 1 can only be a
  percentage; `0` is zero; a number from 0 to 1 (such as `0.3`) is ambiguous, so the person is
  asked whether they meant 0.3% or 30%.

## How to run

In PowerShell, from the project root:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
```

The virtual environment is local and excluded from Git. Use a Python 3.11+ launcher version in
place of `3.14` if needed.

Run the scripted demo from the project root:

```powershell
python -m quote_sim.demo
```

It loads the fake v1 price list, creates and evidences a draft quote, submits it for manager
approval, sends the approved quote, then prints its totals and audit entries.

Run the browser demo locally:

```powershell
python -m server
```

Open `http://localhost:8000`. Pick who you are acting as, ask the rule-based agent to draft a
quote, then submit, approve, reject, or send it as different users. Quotes are shown from the
acting user's point of view (only managers see cost and margin), and the audit log lists every
attempt, including denied ones. Nothing is saved: the browser keeps the list of steps and the
server replays them on a fresh in-memory desk for every click. See
[docs/deployment.md](docs/deployment.md) for public hosting instructions.

## Test results

Verified with `python -m pytest -q`: 145 tests passed.

- `tests/test_access.py` — 20 tests.
- `tests/test_agent.py` — 23 tests.
- `tests/test_approval.py` — 17 tests.
- `tests/test_evidence.py` — 16 tests.
- `tests/test_interpret.py` — 9 tests.
- `tests/test_pricing.py` — 14 tests.
- `tests/test_server.py` — 17 tests.
- `tests/test_service.py` — 16 tests.
- `tests/test_users.py` — 5 tests.
- `tests/test_views.py` — 8 tests.

Counts include parametrized cases (one test function run with several inputs counts once per
input).

## Limitations

This is a small rule-based simulator using fake data, without persistent storage or real quote
delivery. The standard-library web server is an educational demo, not a production-hardened service;
it has no accounts and must not receive real customer or pricing data. The workflow is a draft and
is subject to engineer review. Authorization for revising a rejected quote and editing an approved
quote remains deliberately unresolved and denied; the demo does not exercise those paths.

## AI assistance

AI assistance helped draft and explain code, tests, and documentation. The project owner supplied
the domain brief, technical constraints, and phase plan, and reviews the changes and makes the
project decisions. The demo uses explicitly named sample values; it does not claim that they are
real business rules or defaults.
