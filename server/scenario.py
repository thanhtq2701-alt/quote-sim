"""Stateless replay: rebuild a fresh desk and re-run the browser's step list on every request.

The server never stores quotes. The browser keeps the list of steps it has taken and sends the
whole list each time; the server replays it from scratch. That keeps every visitor isolated, needs
no database, and makes the outcome deterministic: the same steps always give the same audit log.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from quote_sim import config
from quote_sim.demo_data import FakeData, load_fake_data, new_agent, new_desk
from quote_sim.interpret import (
    AmbiguousDiscount,
    DiscountUnit,
    NeedsClarification,
    interpret_discount,
)
from quote_sim.service import EXPECTED_ERRORS, QuoteDesk

MAX_STEPS = 200
PERCENT = Decimal("100")


class StepFormatError(ValueError):
    """A step the browser built incorrectly; this is a client bug, not a business refusal."""


class ClarificationNeeded(Exception):
    """A step cannot run until the person answers a question; the step is not kept or audited."""

    def __init__(self, step_index: int, error: NeedsClarification) -> None:
        super().__init__(str(error))
        self.step_index = step_index
        self.error = error

    def options(self) -> list[dict[str, str]]:
        """For an ambiguous discount, offer both readings as ready-to-send discount units."""
        if not isinstance(self.error, AmbiguousDiscount):
            return []
        typed = format(self.error.value.normalize(), "f")
        hundred_times = format((self.error.value * PERCENT).normalize(), "f")
        return [
            {"label": f"{hundred_times}% (fraction {typed})", "discount_unit": "fraction"},
            {"label": f"{typed}%", "discount_unit": "percent"},
        ]


@dataclass(frozen=True)
class StepResult:
    ok: bool
    message: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplayResult:
    desk: QuoteDesk
    steps: tuple[StepResult, ...]


def replay(steps: object, data: FakeData | None = None) -> ReplayResult:
    """Run each step in order; a refused step is recorded and the replay carries on."""
    if not isinstance(steps, list):
        raise StepFormatError("steps must be a list")
    if len(steps) > MAX_STEPS:
        raise StepFormatError(f"at most {MAX_STEPS} steps are allowed")

    desk = new_desk(data or load_fake_data())
    results: list[StepResult] = []
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            raise StepFormatError(f"step {index} must be an object")
        action = step.get("action")
        handler = STEP_HANDLERS.get(action) if isinstance(action, str) else None
        if handler is None:
            raise StepFormatError(f"step {index} has an unknown action")
        try:
            results.append(handler(desk, step))
        except StepFormatError as error:
            raise StepFormatError(f"step {index}: {error}") from error
        except NeedsClarification as error:
            # Must come before EXPECTED_ERRORS: NeedsClarification is a ValidationError subclass.
            raise ClarificationNeeded(index, error) from error
        except EXPECTED_ERRORS as error:
            # The desk has already written the audit entry; the browser just needs the reason.
            results.append(StepResult(ok=False, message=str(error)))
        except ArithmeticError:
            results.append(StepResult(ok=False, message="number is outside the supported range"))
    return ReplayResult(desk=desk, steps=tuple(results))


# ----- step handlers -----------------------------------------------------------------------


def _agent_draft(desk: QuoteDesk, step: Mapping[str, Any]) -> StepResult:
    agent = new_agent(desk, _text(step, "actor"))
    draft = agent.draft(
        _text(step, "request"),
        price_list_version=_optional_text(step, "price_list_version"),
        discount_unit=_discount_unit(step),
    )
    return StepResult(
        ok=True,
        message=f"{draft.quote_id} drafted with {len(draft.notes)} line(s)",
        notes=(f"Understood: {draft.understood}",)
        + tuple(f"{note.product_id}: {note.reason}" for note in draft.notes),
    )


def _add_line(desk: QuoteDesk, step: Mapping[str, Any]) -> StepResult:
    quote = desk.add_line(
        _text(step, "actor"),
        _text(step, "quote_id"),
        product_id=_text(step, "product_id"),
        quantity=_integer(step, "quantity"),
        discount=interpret_discount(_text(step, "discount"), _discount_unit(step)),
        discount_rule_id=config.DEMO_MANUAL_DISCOUNT_RULE_ID,
        price_list_version=_optional_text(step, "price_list_version"),
    )
    return StepResult(ok=True, message=f"line added to {quote.quote_id}")


def _remove_line(desk: QuoteDesk, step: Mapping[str, Any]) -> StepResult:
    quote = desk.remove_line(
        _text(step, "actor"), _text(step, "quote_id"), _integer(step, "line_index")
    )
    return StepResult(ok=True, message=f"line removed from {quote.quote_id}")


def _transition_handler(
    method_name: str,
) -> Callable[[QuoteDesk, Mapping[str, Any]], StepResult]:
    def handle(desk: QuoteDesk, step: Mapping[str, Any]) -> StepResult:
        method = getattr(desk, method_name)
        quote = method(_text(step, "actor"), _text(step, "quote_id"))
        return StepResult(ok=True, message=f"{quote.quote_id} is now {quote.state.value}")

    return handle


STEP_HANDLERS: Mapping[str, Callable[[QuoteDesk, Mapping[str, Any]], StepResult]] = {
    "agent_draft": _agent_draft,
    "add_line": _add_line,
    "remove_line": _remove_line,
    "submit": _transition_handler("submit"),
    "approve": _transition_handler("approve"),
    "reject": _transition_handler("reject"),
    "revise": _transition_handler("revise"),
    "send": _transition_handler("send"),
}


# ----- field readers: wrong shapes are client bugs, so they raise StepFormatError ----------


def _text(step: Mapping[str, Any], name: str) -> str:
    value = step.get(name)
    if not isinstance(value, str):
        raise StepFormatError(f"{name} must be a string")
    return value


def _optional_text(step: Mapping[str, Any], name: str) -> str | None:
    value = step.get(name)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise StepFormatError(f"{name} must be a string")
    return value


def _integer(step: Mapping[str, Any], name: str) -> int:
    value = step.get(name)
    # bool is a subclass of int in Python, so True would otherwise count as quantity 1.
    if type(value) is not int:
        raise StepFormatError(f"{name} must be an integer")
    return value


def _discount_unit(step: Mapping[str, Any]) -> DiscountUnit | None:
    value = _optional_text(step, "discount_unit")
    if value is None:
        return None
    try:
        return DiscountUnit(value)
    except ValueError as error:
        raise StepFormatError("discount_unit must be 'percent' or 'fraction'") from error
