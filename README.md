# quote-sim

A small Python simulator for learning how an AI-agent-assisted sales-quote workflow can keep human
approval, access control, evidence, and audit history explicit. It uses fake data and makes no real
LLM or external API calls.

**Live demo:** https://quote-sim.onrender.com (fake data only; the free server sleeps when idle, so
the first visit can take about a minute).

## Problem

Sales quotes can be difficult to review when pricing evidence, permissions, and approval history
are kept in separate places. This learning project models a small quote workflow where line prices
retain their source evidence, roles have different permissions, and approval decisions are audited.
All data is fake; the simulated agent is rule-based and does not call an LLM or an external service.

## Workflow

The current draft workflow map is in [docs/workflow.md](docs/workflow.md) and is pending engineer
review; until then, open points use interim decisions listed at the end of that file. The repository layout, architecture, module map, and open questions are in
[docs/PROJECT.md](docs/PROJECT.md).

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
- The `main` branch is protected by a GitHub ruleset: it cannot be deleted or force-pushed, and
  every change arrives through a pull request whose CI checks pass on Python 3.11–3.14.
- `.gitattributes` stores and checks out every text file with LF line endings, so Windows and
  Linux (CI) see identical files whatever each machine's `core.autocrlf` setting is.
- The browser demo is hosted on Render from `render.yaml`, so its settings are reviewed in pull
  requests. It deploys only after CI passes on `main`, runs Python 3.14.10 (a version CI tests),
  and its build runs the fake-data check instead of installing anything.

## How to run

In PowerShell, from the project root:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m tools.check_data
python -m pytest
```

`tools.check_data` checks the fake files in `data/` (every price list is listed in
`quote_sim/config.py` and named after its version, every role has a user, every product sold in
the newest price list has a cost). GitHub Actions runs the same two commands on Python 3.11, 3.12,
3.13, and 3.14 for every push and pull request.

The virtual environment is local and excluded from Git. Use a Python 3.11+ launcher version in
place of `3.14` if needed.

Run the scripted demo from the project root:

```powershell
python -m quote_sim.demo
```

The agent drafts a quote from a plain-English request; sales submits it; a sales attempt to approve
it is denied; a manager approves it; the same quote is shown to a manager (with margin) and a
viewer (without); sales sends it. The audit log printed at the end is the one the desk wrote.

Run the browser demo locally:

```powershell
python -m server
```

Open `http://localhost:8000`. Pick who you are acting as, ask the rule-based agent to draft a
quote, then submit, approve, reject, or send it as different users. Quotes are shown from the
acting user's point of view (only managers see cost and margin), and the audit log lists every
attempt, including denied ones. Nothing is saved: the browser keeps the list of steps and the
server replays them on a fresh in-memory desk for every click. The same demo runs publicly at
https://quote-sim.onrender.com; see [docs/deployment.md](docs/deployment.md) for how it is hosted.

## Test results

Verified with `python -m pytest -q`: 157 tests passed.

- `tests/test_access.py` — 20 tests.
- `tests/test_agent.py` — 23 tests.
- `tests/test_approval.py` — 17 tests.
- `tests/test_check_data.py` — 7 tests.
- `tests/test_demo.py` — 4 tests.
- `tests/test_evidence.py` — 16 tests.
- `tests/test_interpret.py` — 9 tests.
- `tests/test_pricing.py` — 14 tests.
- `tests/test_server.py` — 17 tests.
- `tests/test_service.py` — 17 tests.
- `tests/test_users.py` — 5 tests.
- `tests/test_views.py` — 8 tests.

Counts include parametrized cases (one test function run with several inputs counts once per
input).

## Limitations

This is a small rule-based simulator using fake data, without persistent storage or real quote
delivery. The standard-library web server is an educational demo, not a production-hardened service;
it has no accounts and must not receive real customer or pricing data. The public demo runs on
Render's free plan, so it sleeps after 15 idle minutes and may be restarted at any time. The workflow is a draft and
is subject to engineer review. Authorization for revising a rejected quote and editing an approved
quote remains deliberately unresolved and denied; the demo does not exercise those paths. When
every discount is within the auto-approval threshold, one SALES user can submit and send a quote
with no second person involved. These are interim decisions by the project owner while the
engineer review is pending; see the open questions in [docs/PROJECT.md](docs/PROJECT.md).

## AI assistance

AI assistance helped draft and explain code, tests, and documentation. The project owner supplied
the domain brief, technical constraints, and phase plan, and reviews the changes and makes the
project decisions. The demo uses explicitly named sample values; it does not claim that they are
real business rules or defaults.
