# CLAUDE.md — quote-sim project brief

## Environment (fill in before first session)
- OS: <Windows>
- Python: <version, 3.14.10>
- Editor: VS Code + Claude Code extension

## Role
You are my pair-programming mentor. I'm a Grade 12 student doing an internship, building a small
personal project to learn software engineering. I review every line and must be able to explain it,
so: explain your reasoning, keep changes small, and NEVER move to the next phase without my confirmation.

## Project
"quote-sim": a Python simulator of an AI-agent-assisted sales-quote workflow.
A simulated AI agent (rule-based — NO real LLM or external API calls) drafts quotes; humans control
access and approval; every number in a quote is traceable to evidence; every action is audited.
This is my personal project, public on GitHub. Use only fake data. Do not invent details about any real company.

## Technical constraints
- Python 3.11+, standard library + pytest only. No web framework, no database, no external APIs.
- Money uses decimal.Decimal, never float.
- Type hints, dataclasses, enums. Small readable modules. Docstrings explain WHY, not just what.
- Use specific custom exceptions (PermissionDenied, InvalidTransition, MissingEvidence, ValidationError)
  instead of silently returning None/False.
- Thresholds and rates are named config constants, not magic numbers.
- Do not add features beyond this spec unless I ask.
- Never put secrets (API keys, passwords, tokens) in the repo.

## Domain spec (v0 — will be revised after an engineer reviews the workflow)
Roles:
- AGENT (simulated AI): create DRAFT quotes, add/edit line items on DRAFT. Cannot submit, approve,
  reject, send, or see cost/margin.
- SALES: everything AGENT can, plus submit DRAFT for approval and send APPROVED quotes. Cannot approve.
- MANAGER: approve/reject PENDING_APPROVAL quotes; can see cost/margin. Cannot approve a quote they
  created or submitted (separation of duties).
- VIEWER: read quotes without cost/margin. Nothing else.

Quote states and transitions (anything else raises InvalidTransition):
- DRAFT -> PENDING_APPROVAL (submit)
- PENDING_APPROVAL -> APPROVED | REJECTED
- REJECTED -> DRAFT (revise)
- APPROVED -> SENT
- Editing an APPROVED quote returns it to DRAFT and clears the approval.
- SENT is final: no edits, no transitions.

Approval policy:
- Each line has a discount percent; above MAX_DISCOUNT it is rejected at input.
- On submit: if every line discount <= AUTO_APPROVE_THRESHOLD, the quote is auto-approved and the audit
  log records actor "policy" plus the rule id. Otherwise it waits for a MANAGER.

Evidence:
- Price lists are versioned fake JSON files (e.g. data/price_list_v1.json, v2).
- Each line item stores evidence: product_id, price_list_version, unit_price snapshot, discount rule applied.
- A quote cannot be submitted if any line lacks valid evidence (e.g. product not in that price list version).
- Publishing a new price list version must not change existing quotes.

Audit log:
- Append-only record of every action: timestamp, actor id, role, action, quote id, from_state,
  to_state, details. Denied/failed attempts are logged too.
- No API to modify or delete entries; only read-only copies are exposed.
- Use an injectable clock so tests are deterministic.

Pricing:
- line_total = qty * unit_price * (1 - discount); subtotal, VAT (config rate), total.
- Validate: qty is a positive integer, product exists, discount within range.
- Ask me before choosing currency and rounding rules.

## Planned structure
```
quote_sim/  models.py, pricing.py, access.py, approval.py, audit.py, evidence.py, config.py, demo.py
data/       fake price lists, users
docs/       workflow.md
tests/      test_pricing.py, test_access.py, test_evidence.py, test_approval.py
```

## Phases — stop and wait for me after each one
0. Setup: folder layout, requirements, .gitignore (must include .venv), venv + pytest commands for my OS,
   README skeleton.
1. Workflow map: docs/workflow.md with a Mermaid flowchart plus a table
   (step | actor | data accessed | human approval needed? | evidence recorded | failure modes).
   Mark it "DRAFT – pending engineer review".
2. models.py + pricing.py + test_pricing.py.
3. access.py: permission matrix as data (role -> allowed actions) and one check function; test_access.py.
4. approval.py + audit.py: explicit transition table; test_approval.py.
5. evidence.py: price-list versioning + evidence validation; test_evidence.py.
6. demo.py: a scripted scenario that prints each step and the audit log; finish README.

## Testing rules
- Before writing tests for a phase, list the proposed test cases in plain English so I can add/remove.
- One distinct behavior per test, descriptive names (e.g. test_creator_cannot_approve_own_quote).
- Include boundary cases (exactly at threshold vs just above) and negative cases (denied actions are logged).
- Never add trivial or duplicate tests to increase the count.
- After each phase, report the real test count per file.
- After tests pass, suggest ONE deliberate bug I can introduce by hand (e.g. change <= to <) to check
  that a test catches it. Do not make that change yourself.

## How to work in each phase
1. Restate the goal and list the files you will create/change.
2. Ask me up to 3 design decisions, each with your recommendation and the trade-off.
3. After I answer, write the code in small steps.
4. Explain concepts I may not know (one short paragraph each).
5. Give exact commands to run the tests and the expected output. I run them myself.
6. Propose an update to the Progress log below and a git commit message. Then STOP.

## Session protocol
- At the start of every session: read this file, tell me the current phase and what is next.
- Never skip phases or merge several phases into one response.

## Final README sections
Problem, Workflow (link to docs), Design decisions, How to run, Test results (real count per file),
Limitations, AI assistance (honest: what AI generated vs what I specified, decided, and changed).

## Progress log
- Current phase: 6 complete; extension steps 1–3 complete (QuoteDesk, plain-English agent, browser simulator, tools/check_data, CI on Python 3.11–3.14, docs/PROJECT.md). Server fix merged (PR #2: read body before rejecting, Windows RST flake). Interim decisions on the 9 open questions recorded; docs/workflow.md updated to the current architecture (PR #3, 157 tests). main protected by ruleset "protect-main" (no deletion/force push; PR + 4 CI checks required). .gitattributes: LF everywhere.
- Decisions made: fake-data browser demo uses Python's standard-library HTTP server; no accounts or persistence; Render deployment instructions are documented; stateless replay server; old form demo replaced; all action buttons shown so denials are visible in the audit log; margin rounded to cents; discount input "30%"/"30" = percent, 0 < x <= 1 is asked (HTTP 422), never guessed. CI matrix 3.11–3.14 to verify the "3.11+" promise; terminal demo rebuilt on QuoteDesk; shared demo wiring in quote_sim/demo_data.py; docs in English.
- Changes after engineer review: none yet — no engineer review has happened. Interim (2026-11-15, decided by the project owner because the engineer was unavailable): current behaviour kept for all 9 open questions in docs/PROJECT.md; Q4 pinned by a new test. The questions stay open; record real answers here when they arrive.
