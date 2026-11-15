"""Terminal demo: one scripted quote, from the agent's draft to a sent quote, with the audit log.

Every step goes through the QuoteDesk, so the audit log printed at the end is the real one the
desk wrote, including the attempt that was denied. Run with: python -m quote_sim.demo
"""

from collections.abc import Callable

from quote_sim.access import PermissionDenied
from quote_sim.audit import AuditEntry
from quote_sim.demo_data import load_fake_data, new_agent, new_desk
from quote_sim.views import QuoteView

AGENT_ID = "agent-01"
SALES_ID = "sales-01"
MANAGER_ID = "manager-01"
VIEWER_ID = "viewer-01"
DEMO_REQUEST = "Hi, we need sixty widgets and 2 support plans please"

Printer = Callable[[str], None]


def run(out: Printer = print) -> None:
    """Print each step; `out` is injectable so tests can capture the story without a terminal."""
    data = load_fake_data()
    desk = new_desk(data)
    agent = new_agent(desk, AGENT_ID)

    out("quote-sim terminal demo (fake data, rule-based agent, nothing is saved)")
    out("")
    out(f"1. Customer request: {DEMO_REQUEST!r}")
    draft = agent.draft(DEMO_REQUEST)
    quote_id = draft.quote_id
    out(f"   AGENT {AGENT_ID} drafted {quote_id}. Understood: {draft.understood}")
    for note in draft.notes:
        out(f"   - {note.reason}")

    quote = desk.submit(SALES_ID, quote_id)
    out(f"2. SALES {SALES_ID} submitted it -> {quote.state.value}")
    out("   (a line discount is above the auto-approval threshold, so a manager must decide)")

    try:
        desk.approve(SALES_ID, quote_id)
    except PermissionDenied as error:
        out(f"3. SALES {SALES_ID} tried to approve it -> denied: {error}")

    quote = desk.approve(MANAGER_ID, quote_id)
    out(f"4. MANAGER {MANAGER_ID} approved it -> {quote.state.value}")

    out("5. The same quote seen by two roles:")
    _print_view(out, "MANAGER", desk.view(MANAGER_ID, quote_id))
    _print_view(out, "VIEWER", desk.view(VIEWER_ID, quote_id))

    quote = desk.send(SALES_ID, quote_id)
    out(f"6. SALES {SALES_ID} sent it -> {quote.state.value} (final)")

    out("")
    out("Audit log (append-only; simulated time):")
    for entry in desk.audit_entries:
        out(f"  {_format_entry(entry)}")


def _print_view(out: Printer, label: str, view: QuoteView) -> None:
    margin = f"{view.total_margin} USD" if view.cost_visible else "hidden"
    out(
        f"   {label:<8} subtotal {view.subtotal} + VAT {view.vat} = total {view.total} USD; "
        f"margin: {margin}"
    )


def _format_entry(entry: AuditEntry) -> str:
    from_state = entry.from_state.value if entry.from_state else "-"
    to_state = entry.to_state.value if entry.to_state else "x"
    details = ", ".join(f"{key}={value}" for key, value in entry.details.items())
    return (
        f"{entry.timestamp:%H:%M} | {entry.actor_id} ({entry.role}) | {entry.action} | "
        f"{entry.quote_id} | {from_state} -> {to_state}" + (f" | {details}" if details else "")
    )


if __name__ == "__main__":
    run()
