from decimal import Decimal

import pytest

from quote_sim.agent import (
    MAX_REQUEST_CHARS,
    AgentPolicy,
    QuoteAgent,
    RequestedItem,
    VolumeRule,
    parse_request,
    resolve_product,
)
from quote_sim.audit import AuditLog
from quote_sim.interpret import NeedsClarification
from quote_sim.models import QuoteState
from quote_sim.pricing import ValidationError
from quote_sim.service import QuoteDesk

TEST_AGENT_POLICY = AgentPolicy(
    list_price_rule_id="test-list-price",
    requested_discount_rule_id="test-requested",
    volume_rules=(
        VolumeRule("test-volume-10", 10, Decimal("0.05")),
        VolumeRule("test-volume-50", 50, Decimal("0.15")),
    ),
)


def make_agent(desk: QuoteDesk) -> QuoteAgent:
    return QuoteAgent(desk, "agent-1", TEST_AGENT_POLICY)


def test_parse_accepts_quantity_first_and_product_first_entries() -> None:
    parsed = parse_request("3 x widget; cable 2\n4 sample-gadget")

    assert parsed.items == (
        RequestedItem(3, "widget"),
        RequestedItem(2, "cable"),
        RequestedItem(4, "sample-gadget"),
    )


def test_draft_merges_repeated_products(desk: QuoteDesk) -> None:
    draft = make_agent(desk).draft("5 x widget, widgets 7", price_list_version="test-v1")

    assert [(note.product_id, note.quantity) for note in draft.notes] == [("widget", 12)]


def test_parse_rejects_unreadable_entry() -> None:
    with pytest.raises(NeedsClarification, match="do not understand '#'"):
        parse_request("12 widgets #")


def test_parse_rejects_empty_request() -> None:
    with pytest.raises(NeedsClarification, match="could not find any products"):
        parse_request(" ,\n ; ")


def test_parse_rejects_zero_quantity() -> None:
    with pytest.raises(NeedsClarification, match="at least 1"):
        parse_request("0 x widget")


def test_request_exactly_at_char_limit_is_accepted_and_one_over_is_rejected() -> None:
    entry = "1 x widget"
    at_limit = entry + " " * (MAX_REQUEST_CHARS - len(entry))

    assert parse_request(at_limit).items == (RequestedItem(1, "widget"),)
    with pytest.raises(NeedsClarification, match="at most"):
        parse_request(at_limit + " ")


def test_quantity_at_threshold_gets_rule_and_one_below_gets_list_price() -> None:
    assert TEST_AGENT_POLICY.rule_for(10) == ("test-volume-10", Decimal("0.05"))
    assert TEST_AGENT_POLICY.rule_for(9) == ("test-list-price", Decimal("0"))


def test_highest_reached_threshold_wins() -> None:
    assert TEST_AGENT_POLICY.rule_for(60) == ("test-volume-50", Decimal("0.15"))


def test_duplicate_min_quantity_rules_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate min_quantity"):
        AgentPolicy(
            list_price_rule_id="test-list-price",
            requested_discount_rule_id="test-requested",
            volume_rules=(
                VolumeRule("rule-a", 10, Decimal("0.05")),
                VolumeRule("rule-b", 10, Decimal("0.10")),
            ),
        )


def test_draft_creates_agent_owned_quote_with_evidence_on_every_line(desk: QuoteDesk) -> None:
    draft = make_agent(desk).draft("12 x widget, cable 3", price_list_version="test-v1")

    view = desk.view("sales-1", draft.quote_id)
    assert view.state is QuoteState.DRAFT
    assert view.creator_id == "agent-1"
    assert [
        (line.product_id, line.price_list_version, line.discount_rule_id)
        for line in view.lines
    ] == [
        ("widget", "test-v1", "test-volume-10"),
        ("cable", "test-v1", "test-list-price"),
    ]


def test_unknown_product_fails_before_any_quote_is_created(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    with pytest.raises(NeedsClarification, match="unknown product 'gizmo'"):
        make_agent(desk).draft("2 x widget, 1 x gizmo", price_list_version="test-v1")

    assert desk.quote_ids == ()
    assert audit_log.entries == ()


PRODUCT_IDS = ("sample-widget", "sample-cable", "sample-support-plan")


def test_parse_understands_number_words_and_dozens() -> None:
    parsed = parse_request("a dozen widgets and twenty five cables and two dozen gadgets")

    assert parsed.items == (
        RequestedItem(12, "widgets"),
        RequestedItem(25, "cables"),
        RequestedItem(24, "gadgets"),
    )


def test_parse_extracts_discount_and_price_list_version() -> None:
    parsed = parse_request("20 widgets with a 10% discount using v2 prices")

    assert parsed.items == (RequestedItem(20, "widgets"),)
    assert parsed.discount_text == "10%"
    assert parsed.price_list_version == "v2"


def test_parse_ignores_polite_filler_and_punctuation() -> None:
    parsed = parse_request("Hello, can you quote 5 gadgets please?")

    assert parsed.items == (RequestedItem(5, "gadgets"),)


def test_vague_quantity_is_asked_about() -> None:
    with pytest.raises(NeedsClarification, match="'some' is not a number"):
        parse_request("some widgets")


@pytest.mark.parametrize("phrase", ["widget", "widgets", "sample-widget"])
def test_resolve_accepts_short_names_and_plurals(phrase: str) -> None:
    assert resolve_product(phrase, PRODUCT_IDS) == "sample-widget"


def test_typo_gets_close_match_suggestion() -> None:
    with pytest.raises(NeedsClarification, match="did you mean sample-widget"):
        resolve_product("widgts", PRODUCT_IDS)


def test_alias_shared_by_two_products_is_ambiguous() -> None:
    with pytest.raises(NeedsClarification, match="basic-plan or support-plan"):
        resolve_product("plan", ("basic-plan", "support-plan"))


def test_requested_discount_overrides_volume_rule_and_is_explained(desk: QuoteDesk) -> None:
    draft = make_agent(desk).draft(
        "12 widgets with a 20% discount", price_list_version="test-v1"
    )

    note = draft.notes[0]
    assert (note.discount, note.discount_rule_id) == (Decimal("0.2"), "test-requested")
    assert "customer asked for 20% off" in note.reason
    assert "would give 5% (test-volume-10)" in note.reason


def test_requested_discount_above_maximum_is_asked_before_creating_quote(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    with pytest.raises(NeedsClarification, match="above the 30% maximum"):
        make_agent(desk).draft("2 widgets with a 40% discount", price_list_version="test-v1")

    assert desk.quote_ids == ()
    assert audit_log.entries == ()


def test_conflicting_price_list_choice_is_asked_about(desk: QuoteDesk) -> None:
    with pytest.raises(NeedsClarification, match="mentions v2 but test-v1 is selected"):
        make_agent(desk).draft("3 widgets using v2 prices", price_list_version="test-v1")
