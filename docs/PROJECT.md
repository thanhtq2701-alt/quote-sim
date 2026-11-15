# quote-sim — project overview

A learning project that simulates an AI-agent-assisted sales-quote workflow. A rule-based
"agent" drafts quotes from plain-English requests; humans control access and approval; every
price on a quote points at the versioned price list it came from; every attempt, including
denied ones, is written to an append-only audit log. All data is fake, and no LLM or external
API is called.

## Repository layout

```
.github/workflows/  CI: data check + pytest on Python 3.11–3.14
data/               fake price lists (v1–v3), users, internal cost sheet
docs/               this overview, the workflow map, deployment notes
quote_sim/          the domain library (no web code)
server/             standard-library HTTP server: JSON API + static files
tests/              pytest suite, one file per module
tools/              maintenance scripts (python -m tools.check_data)
web/                the browser page: index.html, app.js, styles.css (no build step)
CLAUDE.md           the project brief and phase plan used with the AI assistant
README.md           problem, decisions, how to run, test results
```

## Architecture

Dependencies only point downwards: `web` knows nothing about Python, `server` translates HTTP
to library calls, and `quote_sim` knows nothing about HTTP.

```mermaid
flowchart TD
    Web["web/ (browser)<br/>keeps the list of steps, draws results"] -->|"POST /api/replay"| Server
    Server["server/<br/>validates JSON, replays steps on a fresh desk"] --> Desk
    Server --> Agent
    Agent["agent.py<br/>plain English → items, discount, version"] --> Desk
    Desk["service.py — QuoteDesk<br/>resolves actor → role, audits every attempt"] --> Workflow
    Desk --> Views["views.py<br/>role-shaped read models (cost for MANAGER only)"]
    Workflow["approval.py<br/>transition table, auto-approval, separation of duties"] --> Access["access.py<br/>role → action matrix"]
    Workflow --> Evidence["evidence.py<br/>versioned price lists, line evidence"]
    Desk --> Pricing["pricing.py<br/>Decimal money, rounding, VAT"]
    Desk --> Audit["audit.py<br/>append-only log, injectable clock"]
```

### What happens on one click

1. The browser appends a step, for example `{"action": "approve", "actor": "manager-01",
   "quote_id": "Q-0001"}`, to its list and sends the whole list.
2. The server builds a new, empty `QuoteDesk` and replays every step in order. A refused step
   (wrong role, wrong state) is recorded in the audit log and the replay continues.
3. Quotes are read back through `QuoteDesk.view()` as the chosen user, so a VIEWER never receives
   cost or margin, and those reads are audited too.
4. If a step cannot be understood (an unknown product, or a discount such as `0.3` that could
   mean 0.3% or 30%), the server answers HTTP 422 with a question. Nothing is kept or audited
   until the person answers.

Because nothing is stored on the server, visitors cannot see each other's quotes, and the same
steps always produce the same audit log.

## Module map

| Module | Responsibility |
|---|---|
| `quote_sim/models.py` | Frozen dataclasses: `Quote`, `LineItem`, `LineEvidence`, policies, `QuoteState` |
| `quote_sim/pricing.py` | Line totals, subtotal, VAT; USD cents with `ROUND_HALF_UP`; input validation |
| `quote_sim/access.py` | Permission matrix as data; `check_permission`, `is_allowed` |
| `quote_sim/approval.py` | Explicit transition table; auto-approval policy; manager decisions |
| `quote_sim/evidence.py` | Loading and publishing price-list versions; attaching and validating evidence |
| `quote_sim/audit.py` | Append-only audit log with frozen entries and an injectable clock |
| `quote_sim/users.py` | Fake user directory; unknown actors are denied |
| `quote_sim/costs.py` | Internal cost sheet, kept apart from price lists |
| `quote_sim/views.py` | Read models shaped per role; the one place cost/margin visibility is decided |
| `quote_sim/service.py` | `QuoteDesk`: the single entry point for every action |
| `quote_sim/interpret.py` | Reading typed discounts; asking when a value is ambiguous |
| `quote_sim/agent.py` | Rule-based drafting agent: parse, match products, choose and explain discounts |
| `quote_sim/config.py` | Illustrative demo values and data paths (not business rules) |
| `quote_sim/demo_data.py` | Builds the demo desk and agent from `config.py` for both demos |
| `quote_sim/demo.py` | Terminal demo: `python -m quote_sim.demo` |
| `server/scenario.py` | Step validation and stateless replay |
| `server/serialize.py` | JSON shapes; money leaves the server as strings |
| `server/app.py` | Routes, request limits, security headers |
| `tools/check_data.py` | Checks `data/` files: versions, users per role, costs for sold products |

## Status

- Phases 0–6 of the original plan are complete.
- Extension steps after the plan:
  1. Users, cost sheet, role-shaped views, `QuoteDesk`, rule-based agent.
  2. Browser simulator (`server/` + `web/`), plain-English agent requests, discount
     clarification.
  3. Repository tidy-up: `tools/check_data.py`, CI, this overview, terminal demo rebuilt on
     `QuoteDesk`.
- Server fix: the request body is read before a request is rejected, so Windows clients get the
  400 answer instead of a connection reset.
- Interim decisions on the open questions recorded (2026-11-15); engineer review still pending.
- Test counts per file are listed in the [README](../README.md#test-results).

## Open questions (pending engineer review)

These are deliberately undecided. The code denies or flags them rather than guessing.

**Interim decision (2026-11-15):** the engineer was not available, so the project owner kept the
current behaviour described after each question. These are interim decisions, not engineer
answers: the questions stay open, and an answer will be recorded in CLAUDE.md under "Changes
after engineer review". Where a test pins the current behaviour, it is named, so changing the
behaviour later makes that test fail on purpose.

**Authority and workflow**

1. **Who may revise a rejected quote (REJECTED → DRAFT)?** Every role is currently denied, and
   each attempt is audited. Pinned by `test_rejected_quote_cannot_be_revised_while_authority_is_tbd`.
2. **Who may edit an approved quote (it returns to DRAFT and loses its approval), and which price
   list do edited lines use: the line's original version or the newest one?** Every role is
   currently denied, and each attempt is audited. Pinned by
   `test_approved_quote_cannot_be_edited_while_authority_is_tbd` and
   `test_editing_approved_quote_is_denied_until_authority_is_decided`.
3. **Who may publish a new price-list version?** Today it is a file added to `data/` and listed in
   `config.py`; there is no publishing role.
4. **May the person who submitted a quote also send it, or should sending be separated like
   approval?** Currently any SALES user may send an approved quote, including its submitter. With
   auto-approval this means one person can submit and send with no second person involved. Pinned
   by `test_submitter_may_send_auto_approved_quote_while_separation_is_undecided`.
   *If sending is separated later:* a trial change (2026-11-15) made 7 tests fail — the pinning
   test, `test_agent_draft_to_sent_flow_records_every_step`, `test_editing_sent_quote_is_rejected`,
   and the 4 tests in `test_demo.py`, because the demo's SALES user submits and sends. The rule
   belongs in `approval.py` `send` and needs its own error message; the existing
   creator/submitter check says "cannot approve or reject" and should not be reused as is.

**Policy**

5. **Should a customer-requested discount replace the volume rule?** The agent currently uses the
   customer's figure as stated (within the maximum) and writes the volume-rule figure in its note
   for the approver. Pinned by `test_requested_discount_overrides_volume_rule_and_is_explained`.
6. **What are the real values for the maximum line discount, the auto-approval threshold, and the
   VAT rate?** The demos use illustrative values from `config.py` (30%, 10%, 10%); the library
   requires them as parameters and has no defaults.

**Audit**

7. **Should reading a quote be audited?** It is, including whether cost and margin were visible.
   Pinned by `test_viewing_quote_is_audited_with_cost_visibility`.
8. **Should a request the agent could not understand be audited?** It is not: nothing was
   attempted on a quote. The browser shows the question instead. Pinned by
   `test_unknown_product_fails_before_any_quote_is_created` and
   `test_requested_discount_above_maximum_is_asked_before_creating_quote`.
9. **Which roles may read the audit log?** The library exposes read-only copies to its caller; in
   the browser demo every role sees the whole log, including the reasons for denials.

## Limitations

- In-memory only; no accounts; no real quote delivery. The web server is a learning demo, not a
  production service, and must never receive real customer or pricing data.
- The agent understands a small, fixed vocabulary of English phrasing. It asks rather than guesses,
  so unusual wording leads to a question, not a wrong quote.
- Published price-list files are not protected against being edited in place; the rule "a
  published version never changes" is enforced in memory and by review, not by the file system.
- A rejected quote cannot be reworked and an approved quote cannot be edited: both paths exist in
  the transition table but no role may use them until questions 1 and 2 are answered.
- When every discount is within the auto-approval threshold, one SALES user can submit and send a
  quote with no second person involved (question 4).

## Workflow and deployment

- Workflow map and table: [workflow.md](workflow.md) (DRAFT – pending engineer review).
- Hosting the browser demo: [deployment.md](deployment.md).
