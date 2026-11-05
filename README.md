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
python -m quote_sim.web
```

Open `http://localhost:8000`. The form simulates a quote for fake data without saving it. See
[docs/deployment.md](docs/deployment.md) for public hosting instructions.

## Test results

Verified with `python -m pytest -q`: 71 tests passed.

- `tests/test_pricing.py` — 14 tests.
- `tests/test_access.py` — 19 tests.
- `tests/test_approval.py` — 17 tests.
- `tests/test_evidence.py` — 14 tests.
- `tests/test_web.py` — 7 tests.

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
