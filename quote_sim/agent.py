"""A rule-based stand-in for an AI drafting agent.

There is no language model here. The "agent" reads a short request written in plain English,
works out what was asked for, looks prices up in a published price list, picks discounts from a
visible rule table, and explains every choice. It acts through the QuoteDesk with its own AGENT
identity, so it gets the same permission checks and audit entries as any other actor.

The guiding rule: never guess. Anything the agent cannot map to a product, quantity, discount,
or price list makes it stop and ask (NeedsClarification) before any quote is created.

Understanding happens in two stages:
1. parse_request() splits the text into (quantity, product phrase) items plus an optional
   discount and price-list mention. It needs no product list.
2. resolve_product() maps a phrase such as "widgets" onto a real product id in the chosen price
   list, accepting short names and plurals, and suggesting close matches for typos.
"""

import difflib
import re
from dataclasses import dataclass
from decimal import Decimal

from quote_sim.evidence import MissingEvidence
from quote_sim.interpret import DiscountUnit, NeedsClarification, interpret_discount
from quote_sim.pricing import ValidationError
from quote_sim.service import QuoteDesk

MAX_REQUEST_CHARS = 1000
MAX_REQUEST_ITEMS = 20
MAX_QUANTITY_DIGITS = 6  # Keeps fake quantities readable and the arithmetic small.
NO_DISCOUNT = Decimal("0")
PERCENT = Decimal("100")

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
MULTIPLIER_WORDS = {"dozen": 12, "hundred": 100}
ARTICLES = {"a", "an"}
VAGUE_QUANTITIES = {"some", "few", "several", "many", "lots", "bunch", "couple"}
# Words that carry no order information. Anything NOT listed here and not understood makes the
# agent ask, so this list only needs the common polite and structural words.
FILLER_WORDS = {
    "i", "we", "need", "needs", "want", "wants", "would", "like", "to", "please", "pls", "order",
    "quote", "quotation", "for", "hi", "hello", "hey", "thanks", "thank", "you", "can", "could",
    "get", "me", "us", "give", "send", "buy", "also", "of", "the", "units", "unit", "pieces",
    "piece", "pcs", "x", "our", "my", "company", "customer", "is", "are", "be", "will", "just",
    "with", "new", "total", "in",
}

DISCOUNT_VALUE = r"(?P<value>\d+(?:\.\d+)?)\s*(?P<suffix>%|percent\b)?"
DISCOUNT_PATTERNS = (
    # "with a 10% discount", "at 10% off", "0.1 discount"
    re.compile(rf"(?:\b(?:with|at)\s+)?(?:\ban?\s+)?{DISCOUNT_VALUE}\s*(?:discount|off)\b"),
    # "discount of 10%", "discount: 0.1", "at a discount of 12.5 percent"
    re.compile(rf"(?:\bwith\s+|\bat\s+)?(?:\ban?\s+)?\bdiscount\s*(?:of|:|=|at)?\s*{DISCOUNT_VALUE}"),
)
VERSION_PATTERN = re.compile(
    r"(?:\b(?:using|use|from|with|on|at)\s+)?(?:\bthe\s+)?(?:\bprice[\s-]*list\s+)?"
    r"\b(?P<version>v\d+)\b(?:\s+(?:prices?|price[\s-]*list|pricing))?"
)
ITEM_SEPARATORS = re.compile(r"[,;\n]+|\band\b|&|\bplus\b")
TOKEN_PATTERN = re.compile(r"\d+(?:\.\d+)?|[a-z][a-z0-9-]*|\S")
PUNCTUATION = set(".!?:()\"'-")


# ----- policy --------------------------------------------------------------------------------


@dataclass(frozen=True)
class VolumeRule:
    """One row of the agent's discount table: at least min_quantity units earns this discount."""

    rule_id: str
    min_quantity: int
    discount: Decimal


@dataclass(frozen=True)
class AgentPolicy:
    """Keep the agent's choices data-driven so a reviewer can read every rule it can apply."""

    list_price_rule_id: str
    requested_discount_rule_id: str
    volume_rules: tuple[VolumeRule, ...]

    def __post_init__(self) -> None:
        for name in ("list_price_rule_id", "requested_discount_rule_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{name} must be a non-empty string")
        seen_quantities: set[int] = set()
        for rule in self.volume_rules:
            if not isinstance(rule, VolumeRule):
                raise ValidationError("volume_rules must contain VolumeRule records")
            if not isinstance(rule.rule_id, str) or not rule.rule_id.strip():
                raise ValidationError("volume rule ids must be non-empty strings")
            if type(rule.min_quantity) is not int or rule.min_quantity <= 0:
                raise ValidationError("min_quantity must be a positive integer")
            if rule.min_quantity in seen_quantities:
                # Two rules for the same quantity would make the agent's choice ambiguous.
                raise ValidationError(f"duplicate min_quantity: {rule.min_quantity}")
            seen_quantities.add(rule.min_quantity)
            if (
                not isinstance(rule.discount, Decimal)
                or not rule.discount.is_finite()
                or not NO_DISCOUNT <= rule.discount <= Decimal(1)
            ):
                raise ValidationError("volume discounts must be Decimals between 0 and 1")

    def rule_for(self, quantity: int) -> tuple[str, Decimal]:
        """Pick the rule with the highest threshold the quantity reaches, else list price."""
        reached = [rule for rule in self.volume_rules if quantity >= rule.min_quantity]
        if not reached:
            return self.list_price_rule_id, NO_DISCOUNT
        best = max(reached, key=lambda rule: rule.min_quantity)
        return best.rule_id, best.discount


# ----- stage 1: parse ------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestedItem:
    """A quantity and the words used for the product, before matching a real product id."""

    quantity: int
    phrase: str


@dataclass(frozen=True)
class ParsedRequest:
    items: tuple[RequestedItem, ...]
    discount_text: str | None = None
    price_list_version: str | None = None


@dataclass(frozen=True)
class _Quantity:
    value: int


@dataclass(frozen=True)
class _Multiplier:
    value: int


def parse_request(text: str) -> ParsedRequest:
    """Split a plain-English request into items, an optional discount, and an optional version.

    Accepted examples: "12 x sample-widget, cable 3", "a dozen widgets and two support plans",
    "20 widgets with a 10% discount using v2 prices".
    """
    if not isinstance(text, str):
        raise ValidationError("request must be text")
    if len(text) > MAX_REQUEST_CHARS:
        raise NeedsClarification(f"request must be at most {MAX_REQUEST_CHARS} characters")

    # Same-length replacements only, so the text stays recognisable in error messages.
    normalized = text.lower().replace("×", "x").replace("*", "x")
    normalized = re.sub(r"\bx(?=\d)", "x ", normalized)

    normalized, discount_text = _extract_discount(normalized)
    normalized, version = _extract_version(normalized)
    if re.search(r"\b(?:discount|off)\b", normalized):
        raise NeedsClarification("how much discount? write it like '10% discount'")

    items: list[RequestedItem] = []
    for chunk in ITEM_SEPARATORS.split(normalized):
        items.extend(_parse_chunk(chunk))
    if not items:
        raise NeedsClarification(
            "I could not find any products; try something like '12 x sample-widget'"
        )
    if len(items) > MAX_REQUEST_ITEMS:
        raise NeedsClarification(f"a request may list at most {MAX_REQUEST_ITEMS} items")
    return ParsedRequest(tuple(items), discount_text, version)


def _extract_discount(text: str) -> tuple[str, str | None]:
    found: list[str] = []

    def take(match: re.Match[str]) -> str:
        found.append(match.group("value") + ("%" if match.group("suffix") else ""))
        return " "

    for pattern in DISCOUNT_PATTERNS:
        text = pattern.sub(take, text)
    if len(found) > 1:
        raise NeedsClarification(
            f"I found {len(found)} discounts ({', '.join(found)}); give one for the whole request"
        )
    return text, found[0] if found else None


def _extract_version(text: str) -> tuple[str, str | None]:
    versions: list[str] = []

    def take(match: re.Match[str]) -> str:
        versions.append(match.group("version"))
        return " "

    text = VERSION_PATTERN.sub(take, text)
    if len(set(versions)) > 1:
        raise NeedsClarification(
            f"the request names several price lists ({', '.join(versions)}); pick one"
        )
    return text, versions[0] if versions else None


def _parse_chunk(chunk: str) -> list[RequestedItem]:
    tokens = _tokens(chunk)
    if not tokens:
        return []
    shown = chunk.strip()

    items: list[RequestedItem] = []
    if isinstance(tokens[0], _Quantity):
        # Quantity-first: "12 widgets", "3 x cable 4 gadgets"
        index = 0
        while index < len(tokens):
            quantity = tokens[index]
            words = _take_words(tokens, index + 1)
            if not isinstance(quantity, _Quantity) or not words:
                raise NeedsClarification(f"in {shown!r}, which product is each quantity for?")
            items.append(RequestedItem(quantity.value, "-".join(words)))
            index += 1 + len(words)
    else:
        # Product-first: "widgets 12", "support plan x 2"
        index = 0
        while index < len(tokens):
            words = _take_words(tokens, index)
            after = index + len(words)
            if after >= len(tokens):
                raise NeedsClarification(f"how many {' '.join(words)}?")
            quantity = tokens[after]
            assert isinstance(quantity, _Quantity)
            items.append(RequestedItem(quantity.value, "-".join(words)))
            index = after + 1
    return items


def _take_words(tokens: list[object], start: int) -> list[str]:
    words: list[str] = []
    for token in tokens[start:]:
        if not isinstance(token, str):
            break
        words.append(token)
    return words


def _tokens(chunk: str) -> list[object]:
    """Turn words into quantities where possible; drop filler; reject what cannot be read."""
    raw = [
        token
        for token in TOKEN_PATTERN.findall(chunk)
        if token not in FILLER_WORDS and token not in PUNCTUATION
    ]
    tokens: list[object] = []
    for position, token in enumerate(raw):
        following = raw[position + 1] if position + 1 < len(raw) else None
        if token in VAGUE_QUANTITIES:
            raise NeedsClarification(f"{token!r} is not a number; how many exactly?")
        if token in ARTICLES:
            # "a widget" means one; "a dozen" lets the multiplier speak for itself.
            if following is not None and (following in MULTIPLIER_WORDS or following in NUMBER_WORDS):
                continue
            tokens.append(_Quantity(1))
        elif token[0].isdigit():
            if not token.isdigit():
                raise NeedsClarification(f"quantity must be a whole number, not {token}")
            if len(token) > MAX_QUANTITY_DIGITS:
                raise NeedsClarification(f"quantity {token} is too large")
            if int(token) == 0:
                raise NeedsClarification("quantity must be at least 1")
            tokens.append(_Quantity(int(token)))
        elif token in NUMBER_WORDS:
            tokens.append(_Quantity(NUMBER_WORDS[token]))
        elif token in MULTIPLIER_WORDS:
            tokens.append(_Multiplier(MULTIPLIER_WORDS[token]))
        elif re.fullmatch(r"[a-z][a-z0-9-]*", token):
            tokens.append(token)
        else:
            raise NeedsClarification(f"I do not understand {token!r} in {chunk.strip()!r}")
    return _combine_numbers(tokens)


def _combine_numbers(tokens: list[object]) -> list[object]:
    """Merge "twenty five" -> 25, "two dozen" -> 24, and a lone "dozen" -> 12."""
    combined: list[object] = []
    for token in tokens:
        previous = combined[-1] if combined else None
        if isinstance(token, _Multiplier):
            if isinstance(previous, _Quantity):
                combined[-1] = _Quantity(previous.value * token.value)
            else:
                combined.append(_Quantity(token.value))
        elif (
            isinstance(token, _Quantity)
            and isinstance(previous, _Quantity)
            and previous.value >= 20
            and previous.value % 10 == 0
            and token.value < 10
        ):
            combined[-1] = _Quantity(previous.value + token.value)
        else:
            combined.append(token)
    return combined


# ----- stage 2: match products ---------------------------------------------------------------


def resolve_product(phrase: str, product_ids: tuple[str, ...]) -> str:
    """Match "widgets", "widget" or "sample-widget" to the product id "sample-widget".

    Every hyphen-suffix of an id is an alias ("sample-support-plan" -> "support-plan" -> "plan"),
    and a trailing plural "s"/"es" is ignored. An alias shared by two products is ambiguous.
    """
    aliases: dict[str, set[str]] = {}
    for product_id in product_ids:
        parts = product_id.split("-")
        for start in range(len(parts)):
            aliases.setdefault("-".join(parts[start:]), set()).add(product_id)

    for candidate in _singular_forms(phrase):
        matches = aliases.get(candidate)
        if matches and len(matches) == 1:
            return next(iter(matches))
        if matches:
            raise NeedsClarification(
                f"{phrase!r} could be {' or '.join(sorted(matches))}; which one?"
            )

    suggestions = sorted(
        {product_id for alias in difflib.get_close_matches(phrase, aliases, n=3, cutoff=0.6)
         for product_id in aliases[alias]}
    )
    hint = (
        f"did you mean {' or '.join(suggestions)}?"
        if suggestions
        else f"available: {', '.join(product_ids)}"
    )
    raise NeedsClarification(f"unknown product {phrase!r}; {hint}")


def _singular_forms(phrase: str) -> list[str]:
    forms = [phrase]
    if phrase.endswith("es"):
        forms.append(phrase[:-2])
    if phrase.endswith("s"):
        forms.append(phrase[:-1])
    return forms


# ----- the agent -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftNote:
    """The agent's explanation for one line, so a human reviewer can check each decision."""

    product_id: str
    quantity: int
    price_list_version: str
    unit_price: Decimal
    discount: Decimal
    discount_rule_id: str
    reason: str


@dataclass(frozen=True)
class AgentDraft:
    quote_id: str
    understood: str
    notes: tuple[DraftNote, ...]


class QuoteAgent:
    """Draft quotes on behalf of one AGENT user; everything it does goes through the desk."""

    def __init__(self, desk: QuoteDesk, agent_id: str, policy: AgentPolicy) -> None:
        if not isinstance(policy, AgentPolicy):
            raise TypeError("policy must be an AgentPolicy")
        self._desk = desk
        self._agent_id = agent_id
        self._policy = policy

    def draft(
        self,
        request_text: str,
        price_list_version: str | None = None,
        discount_unit: DiscountUnit | None = None,
    ) -> AgentDraft:
        """Create one DRAFT quote for the request, or ask (NeedsClarification) before creating.

        All understanding and checking happens first, so a misunderstood request never leaves a
        half-built quote behind; nothing has been attempted on a quote, so nothing is audited.
        """
        parsed = parse_request(request_text)
        version = self._choose_version(parsed, price_list_version)
        price_list = self._desk.price_lists.get(version)

        quantities: dict[str, int] = {}
        for item in parsed.items:
            product_id = resolve_product(item.phrase, tuple(price_list.products))
            # Merge repeats so a volume rule sees the real total ("5 widgets, 7 widgets" = 12).
            quantities[product_id] = quantities.get(product_id, 0) + item.quantity

        requested_discount = self._requested_discount(parsed, discount_unit)

        quote = self._desk.create_quote(self._agent_id)
        notes: list[DraftNote] = []
        for product_id, quantity in quantities.items():
            rule_id, discount, reason = self._choose_discount(quantity, requested_discount, version)
            self._desk.add_line(
                self._agent_id,
                quote.quote_id,
                product_id=product_id,
                quantity=quantity,
                discount=discount,
                discount_rule_id=rule_id,
                price_list_version=version,
            )
            notes.append(
                DraftNote(
                    product_id=product_id,
                    quantity=quantity,
                    price_list_version=version,
                    unit_price=price_list.products[product_id],
                    discount=discount,
                    discount_rule_id=rule_id,
                    reason=reason,
                )
            )

        understood = "; ".join(
            [", ".join(f"{quantity} x {product_id}" for product_id, quantity in quantities.items())]
            + ([f"requested discount {_percent(requested_discount)}%"]
               if requested_discount is not None else [])
            + [f"price list {version}"]
        )
        return AgentDraft(quote_id=quote.quote_id, understood=understood, notes=tuple(notes))

    def _choose_version(self, parsed: ParsedRequest, selected: str | None) -> str:
        price_lists = self._desk.price_lists
        if selected and parsed.price_list_version and selected != parsed.price_list_version:
            raise NeedsClarification(
                f"the request mentions {parsed.price_list_version} but {selected} is selected; "
                "which price list should I use?"
            )
        version = selected or parsed.price_list_version or price_lists.latest_version
        try:
            price_lists.get(version)
        except MissingEvidence as error:
            raise NeedsClarification(
                f"price list {version} is not published; available: {', '.join(price_lists.versions)}"
            ) from error
        return version

    def _requested_discount(
        self, parsed: ParsedRequest, unit: DiscountUnit | None
    ) -> Decimal | None:
        if parsed.discount_text is None:
            if unit is not None:
                raise NeedsClarification("a discount unit was given but the request has no discount")
            return None
        discount = interpret_discount(parsed.discount_text, unit)
        maximum = self._desk.pricing_policy.max_discount
        if discount > maximum:
            raise NeedsClarification(
                f"the requested {_percent(discount)}% discount is above the "
                f"{_percent(maximum)}% maximum; please ask for {_percent(maximum)}% or less"
            )
        return discount

    def _choose_discount(
        self, quantity: int, requested: Decimal | None, version: str
    ) -> tuple[str, Decimal, str]:
        volume_rule_id, volume_discount = self._policy.rule_for(quantity)
        if requested is not None:
            # The customer's own ask is used as stated; a human approver sees both numbers.
            return (
                self._policy.requested_discount_rule_id,
                requested,
                f"customer asked for {_percent(requested)}% off; the volume table alone would "
                f"give {_percent(volume_discount)}% ({volume_rule_id})",
            )
        if volume_rule_id == self._policy.list_price_rule_id:
            return (
                volume_rule_id,
                volume_discount,
                f"quantity {quantity} is below every volume threshold, so list price from "
                f"{version} applies ({volume_rule_id})",
            )
        threshold = next(
            rule.min_quantity for rule in self._policy.volume_rules if rule.rule_id == volume_rule_id
        )
        return (
            volume_rule_id,
            volume_discount,
            f"quantity {quantity} reaches the {threshold}-unit threshold, so {volume_rule_id} "
            f"gives {_percent(volume_discount)}% off the {version} price",
        )


def _percent(fraction: Decimal) -> str:
    return format((fraction * PERCENT).normalize(), "f")
