"""The quote desk: one entry point that resolves actors, enforces rules, and audits every attempt.

Callers pass only an actor id. The desk looks up the role in the user directory, so nobody can
claim to be a MANAGER just by saying so. State transitions are delegated to ApprovalWorkflow,
which already audits its own successes and failures; the desk audits everything else (creating,
editing, viewing) so the log has exactly one entry per attempt.
"""

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

from quote_sim.access import Action, PermissionDenied, check_permission
from quote_sim.approval import ApprovalPolicy, ApprovalWorkflow, InvalidTransition
from quote_sim.audit import AuditEntry, AuditLog
from quote_sim.costs import CostSheet
from quote_sim.evidence import (
    MissingEvidence,
    PriceListCatalog,
    attach_evidence,
    product_catalog,
)
from quote_sim.models import LineItem, PricingPolicy, Quote, QuoteState
from quote_sim.pricing import ValidationError, create_line_item
from quote_sim.users import User, UserDirectory
from quote_sim.views import QuoteView, build_quote_view

UNASSIGNED_QUOTE_ID = "-"
UNKNOWN_ROLE = "unknown"

# Errors that represent a refused or invalid attempt. Anything else is a programming bug and
# should crash loudly rather than be written to the audit log as a business failure.
EXPECTED_ERRORS = (InvalidTransition, MissingEvidence, PermissionDenied, ValidationError)


class QuoteDesk:
    """Hold quotes in memory and route every action through permission, state, and audit checks."""

    def __init__(
        self,
        *,
        users: UserDirectory,
        price_lists: PriceListCatalog,
        pricing_policy: PricingPolicy,
        approval_policy: ApprovalPolicy,
        audit_log: AuditLog,
        cost_sheet: CostSheet | None = None,
        quote_id_prefix: str = "Q",
    ) -> None:
        self._users = users
        self._price_lists = price_lists
        self._pricing_policy = pricing_policy
        self._audit_log = audit_log
        self._cost_sheet = cost_sheet
        self._quote_id_prefix = quote_id_prefix
        self._workflow = ApprovalWorkflow(
            approval_policy, audit_log, price_lists, pricing_policy
        )
        self._quotes: dict[str, Quote] = {}
        self._next_quote_number = 1

    # ----- read-only properties -------------------------------------------------------------

    @property
    def quote_ids(self) -> tuple[str, ...]:
        """Expose ids only; quote contents are read through view() so reads are audited."""
        return tuple(self._quotes)

    @property
    def audit_entries(self) -> tuple[AuditEntry, ...]:
        return self._audit_log.entries

    @property
    def price_lists(self) -> PriceListCatalog:
        return self._price_lists

    @property
    def pricing_policy(self) -> PricingPolicy:
        """Let callers such as the agent check limits before attempting an audited action."""
        return self._pricing_policy

    # ----- creating and editing drafts ------------------------------------------------------

    def create_quote(self, actor_id: str) -> Quote:
        try:
            user = self._authorize(actor_id, Action.CREATE_QUOTE)
        except EXPECTED_ERRORS as error:
            self._record_failure(actor_id, Action.CREATE_QUOTE, UNASSIGNED_QUOTE_ID, None, error)
            raise

        quote = Quote(quote_id=self._allocate_quote_id(), creator_id=user.user_id)
        self._quotes[quote.quote_id] = quote
        self._record(user, Action.CREATE_QUOTE.value, quote.quote_id, None, quote.state, {})
        return quote

    def add_line(
        self,
        actor_id: str,
        quote_id: str,
        *,
        product_id: str,
        quantity: int,
        discount: Decimal,
        discount_rule_id: str,
        price_list_version: str | None = None,
    ) -> Quote:
        """Add a priced, evidenced line; with no version given, the newest price list is used."""

        def build_lines(quote: Quote) -> tuple[LineItem, ...]:
            version = price_list_version or self._price_lists.latest_version
            line = self._priced_line(product_id, quantity, discount, version, discount_rule_id)
            return quote.line_items + (line,)

        return self._edit(
            actor_id,
            quote_id,
            build_lines,
            {"change": "add_line", "product_id": product_id, "quantity": quantity},
        )

    def update_line(
        self,
        actor_id: str,
        quote_id: str,
        line_index: int,
        *,
        quantity: int,
        discount: Decimal,
        discount_rule_id: str,
    ) -> Quote:
        """Change quantity or discount but keep the line's original price-list version."""

        def build_lines(quote: Quote) -> tuple[LineItem, ...]:
            old_line = _line_at(quote, line_index)
            # Re-pricing from the line's own version keeps "new price list must not change
            # existing quotes" true even while a draft is being edited.
            version = (
                old_line.evidence.price_list_version
                if old_line.evidence is not None
                else self._price_lists.latest_version
            )
            new_line = self._priced_line(
                old_line.product_id, quantity, discount, version, discount_rule_id
            )
            lines = list(quote.line_items)
            lines[line_index] = new_line
            return tuple(lines)

        return self._edit(
            actor_id,
            quote_id,
            build_lines,
            {"change": "update_line", "line_index": line_index, "quantity": quantity},
        )

    def remove_line(self, actor_id: str, quote_id: str, line_index: int) -> Quote:
        def build_lines(quote: Quote) -> tuple[LineItem, ...]:
            _line_at(quote, line_index)
            return quote.line_items[:line_index] + quote.line_items[line_index + 1 :]

        return self._edit(
            actor_id,
            quote_id,
            build_lines,
            {"change": "remove_line", "line_index": line_index},
        )

    # ----- workflow transitions (audited by ApprovalWorkflow) -------------------------------

    def submit(self, actor_id: str, quote_id: str) -> Quote:
        return self._transition(actor_id, quote_id, Action.SUBMIT_QUOTE, self._workflow.submit)

    def approve(self, actor_id: str, quote_id: str) -> Quote:
        return self._transition(actor_id, quote_id, Action.APPROVE_QUOTE, self._workflow.approve)

    def reject(self, actor_id: str, quote_id: str) -> Quote:
        return self._transition(actor_id, quote_id, Action.REJECT_QUOTE, self._workflow.reject)

    def revise(self, actor_id: str, quote_id: str) -> Quote:
        return self._transition(actor_id, quote_id, Action.REVISE_QUOTE, self._workflow.revise)

    def send(self, actor_id: str, quote_id: str) -> Quote:
        return self._transition(actor_id, quote_id, Action.SEND_QUOTE, self._workflow.send)

    # ----- reading --------------------------------------------------------------------------

    def view(self, actor_id: str, quote_id: str) -> QuoteView:
        """Return a role-shaped view and audit the read, including whether cost was visible."""
        quote: Quote | None = None
        try:
            user = self._authorize(actor_id, Action.VIEW_QUOTE)
            quote = self._find(quote_id)
        except EXPECTED_ERRORS as error:
            from_state = quote.state if quote is not None else None
            self._record_failure(actor_id, Action.VIEW_QUOTE, quote_id, from_state, error)
            raise

        quote_view = build_quote_view(quote, user.role, self._pricing_policy, self._cost_sheet)
        self._record(
            user,
            Action.VIEW_QUOTE.value,
            quote.quote_id,
            quote.state,
            quote.state,
            {"cost_margin_visible": quote_view.cost_visible},
        )
        return quote_view

    # ----- internals ------------------------------------------------------------------------

    def _edit(
        self,
        actor_id: str,
        quote_id: str,
        build_lines: Callable[[Quote], tuple[LineItem, ...]],
        details: dict[str, object],
    ) -> Quote:
        action = Action.EDIT_DRAFT
        quote: Quote | None = None
        try:
            user = self._authorize(actor_id, action)
            quote = self._find(quote_id)
            if quote.state not in {QuoteState.DRAFT, QuoteState.APPROVED}:
                raise InvalidTransition(f"cannot edit a quote in {quote.state.value}")
            new_lines = build_lines(quote)
        except EXPECTED_ERRORS as error:
            from_state = quote.state if quote is not None else None
            self._record_failure(actor_id, action, quote_id, from_state, error)
            raise

        if quote.state is QuoteState.APPROVED:
            # The spec says an approved quote returns to DRAFT when edited. Who may do that is
            # still undecided, so the workflow owns (and currently denies and audits) this path.
            updated = self._workflow.edit_approved(quote, user.user_id, user.role, new_lines)
        else:
            updated = replace(quote, line_items=new_lines)
            self._record(
                user, action.value, quote.quote_id, quote.state, updated.state, details
            )
        self._quotes[quote_id] = updated
        return updated

    def _transition(
        self,
        actor_id: str,
        quote_id: str,
        action: Action,
        step: Callable[..., Quote],
    ) -> Quote:
        quote: Quote | None = None
        try:
            user = self._users.get(actor_id)
            quote = self._find(quote_id)
        except EXPECTED_ERRORS as error:
            from_state = quote.state if quote is not None else None
            self._record_failure(actor_id, action, quote_id, from_state, error)
            raise
        # The workflow checks the role, the transition table, and evidence, and audits the
        # result itself, so the desk must not write a second entry here.
        updated = step(quote, user.user_id, user.role)
        self._quotes[quote_id] = updated
        return updated

    def _priced_line(
        self,
        product_id: str,
        quantity: int,
        discount: Decimal,
        price_list_version: str,
        discount_rule_id: str,
    ) -> LineItem:
        price_list = self._price_lists.get(price_list_version)
        line = create_line_item(
            product_id,
            quantity,
            discount,
            product_catalog(price_list),
            self._pricing_policy,
        )
        return attach_evidence(line, price_list, discount_rule_id)

    def _authorize(self, actor_id: str, action: Action) -> User:
        user = self._users.get(actor_id)
        check_permission(user.role, action)
        return user

    def _find(self, quote_id: str) -> Quote:
        try:
            return self._quotes[quote_id]
        except (KeyError, TypeError) as error:
            raise ValidationError(f"unknown quote: {quote_id}") from error

    def _allocate_quote_id(self) -> str:
        quote_id = f"{self._quote_id_prefix}-{self._next_quote_number:04d}"
        self._next_quote_number += 1
        return quote_id

    def _record(
        self,
        user: User,
        action: str,
        quote_id: str,
        from_state: QuoteState | None,
        to_state: QuoteState | None,
        details: dict[str, object],
    ) -> None:
        self._audit_log.record(
            actor_id=user.user_id,
            role=user.role.value,
            action=action,
            quote_id=quote_id,
            from_state=from_state,
            to_state=to_state,
            details=details,
        )

    def _record_failure(
        self,
        actor_id: str,
        action: Action,
        quote_id: str,
        from_state: QuoteState | None,
        error: Exception,
    ) -> None:
        try:
            role = self._users.get(actor_id).role.value
        except PermissionDenied:
            role = UNKNOWN_ROLE
        self._audit_log.record(
            actor_id=str(actor_id),
            role=role,
            action=action.value,
            quote_id=str(quote_id),
            from_state=from_state,
            to_state=None,
            details={
                "result": "denied" if isinstance(error, PermissionDenied) else "failed",
                "reason": str(error),
            },
        )


def _line_at(quote: Quote, line_index: int) -> LineItem:
    if type(line_index) is not int or not 0 <= line_index < len(quote.line_items):
        raise ValidationError(f"no line at index {line_index}")
    return quote.line_items[line_index]
