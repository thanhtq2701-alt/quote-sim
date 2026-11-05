import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from quote_sim.evidence import (
    MissingEvidence,
    PriceList,
    PriceListCatalog,
    attach_evidence,
    load_price_list,
    validate_line_evidence,
)
from quote_sim.models import LineEvidence, LineItem
from quote_sim.pricing import ValidationError

DATA_DIRECTORY = Path(__file__).resolve().parents[1] / "data"
TEST_DISCOUNT_RULE = "test-max-discount"


def make_line_item(
    *,
    product_id: str = "sample-widget",
    unit_price: str = "10.00",
) -> LineItem:
    return LineItem(
        product_id=product_id,
        quantity=1,
        unit_price=Decimal(unit_price),
        discount=Decimal("0.05"),
    )


def make_price_list_catalog() -> PriceListCatalog:
    return PriceListCatalog(
        [
            PriceList("v1", {"sample-widget": Decimal("10.00")}),
            PriceList("v2", {"sample-widget": Decimal("12.00")}),
        ]
    )


def test_load_price_list_reads_version_and_decimal_prices() -> None:
    price_list = load_price_list(DATA_DIRECTORY / "price_list_v1.json")

    assert price_list.version == "v1"
    assert price_list.products["sample-widget"] == Decimal("10.00")


def test_publish_files_loads_distinct_fake_versions() -> None:
    catalog = PriceListCatalog()

    catalog.publish_file(DATA_DIRECTORY / "price_list_v1.json")
    catalog.publish_file(DATA_DIRECTORY / "price_list_v2.json")

    assert catalog.versions == ("v1", "v2")
    assert catalog.get("v1").products["sample-widget"] == Decimal("10.00")
    assert catalog.get("v2").products["sample-widget"] == Decimal("12.00")


def test_load_price_list_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid price-list JSON"):
        load_price_list(path)


def test_load_price_list_rejects_non_decimal_string_price(tmp_path: Path) -> None:
    path = tmp_path / "invalid-price.json"
    path.write_text(
        json.dumps({"version": "bad", "products": {"widget": "not-a-price"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="invalid price"):
        load_price_list(path)


def test_publishing_duplicate_version_does_not_replace_original() -> None:
    catalog = PriceListCatalog(
        [PriceList("v1", {"sample-widget": Decimal("10.00")})]
    )

    with pytest.raises(ValidationError, match="already published"):
        catalog.publish(PriceList("v1", {"sample-widget": Decimal("99.00")}))

    assert catalog.get("v1").products["sample-widget"] == Decimal("10.00")


def test_publishing_new_version_preserves_old_price() -> None:
    catalog = PriceListCatalog(
        [PriceList("v1", {"sample-widget": Decimal("10.00")})]
    )
    catalog.publish(PriceList("v2", {"sample-widget": Decimal("12.00")}))

    assert catalog.get("v1").products["sample-widget"] == Decimal("10.00")
    assert catalog.get("v2").products["sample-widget"] == Decimal("12.00")


def test_attach_evidence_records_version_price_and_discount_rule() -> None:
    price_list = PriceList("v1", {"sample-widget": Decimal("10.00")})

    evidenced_line = attach_evidence(
        make_line_item(),
        price_list,
        TEST_DISCOUNT_RULE,
    )

    assert evidenced_line.evidence is not None
    assert evidenced_line.evidence.product_id == "sample-widget"
    assert evidenced_line.evidence.price_list_version == "v1"
    assert evidenced_line.evidence.unit_price_snapshot == Decimal("10.00")
    assert evidenced_line.evidence.discount_rule_id == TEST_DISCOUNT_RULE


def test_attach_evidence_rejects_product_missing_from_selected_version() -> None:
    price_list = PriceList("v1", {"different-product": Decimal("10.00")})

    with pytest.raises(MissingEvidence, match="absent"):
        attach_evidence(make_line_item(), price_list, TEST_DISCOUNT_RULE)


def test_validate_line_evidence_accepts_matching_version_and_snapshot() -> None:
    catalog = make_price_list_catalog()
    line_item = attach_evidence(
        make_line_item(),
        catalog.get("v1"),
        TEST_DISCOUNT_RULE,
    )

    validate_line_evidence(line_item, catalog)


def test_validate_line_evidence_rejects_missing_evidence() -> None:
    with pytest.raises(MissingEvidence, match="no evidence"):
        validate_line_evidence(make_line_item(), make_price_list_catalog())


def test_validate_line_evidence_rejects_unknown_price_list_version() -> None:
    catalog = make_price_list_catalog()
    line_item = replace(
        attach_evidence(make_line_item(), catalog.get("v1"), TEST_DISCOUNT_RULE),
        evidence=LineEvidence(
            product_id="sample-widget",
            price_list_version="unknown",
            unit_price_snapshot=Decimal("10.00"),
            discount_rule_id=TEST_DISCOUNT_RULE,
        ),
    )

    with pytest.raises(MissingEvidence, match="unknown price-list version"):
        validate_line_evidence(line_item, catalog)


def test_validate_line_evidence_rejects_evidence_for_another_product() -> None:
    catalog = make_price_list_catalog()
    line_item = replace(
        attach_evidence(make_line_item(), catalog.get("v1"), TEST_DISCOUNT_RULE),
        evidence=LineEvidence(
            product_id="different-product",
            price_list_version="v1",
            unit_price_snapshot=Decimal("10.00"),
            discount_rule_id=TEST_DISCOUNT_RULE,
        ),
    )

    with pytest.raises(ValidationError, match="product does not match"):
        validate_line_evidence(line_item, catalog)


def test_validate_line_evidence_rejects_price_snapshot_mismatch() -> None:
    catalog = make_price_list_catalog()
    line_item = replace(
        attach_evidence(make_line_item(), catalog.get("v1"), TEST_DISCOUNT_RULE),
        evidence=LineEvidence(
            product_id="sample-widget",
            price_list_version="v1",
            unit_price_snapshot=Decimal("11.00"),
            discount_rule_id=TEST_DISCOUNT_RULE,
        ),
    )

    with pytest.raises(ValidationError, match="price does not match"):
        validate_line_evidence(line_item, catalog)


def test_old_line_snapshot_validates_after_new_version_is_published() -> None:
    catalog = PriceListCatalog(
        [PriceList("v1", {"sample-widget": Decimal("10.00")})]
    )
    line_item = attach_evidence(
        make_line_item(),
        catalog.get("v1"),
        TEST_DISCOUNT_RULE,
    )
    catalog.publish(PriceList("v2", {"sample-widget": Decimal("12.00")}))

    validate_line_evidence(line_item, catalog)

    assert line_item.unit_price == Decimal("10.00")
    assert line_item.evidence is not None
    assert line_item.evidence.price_list_version == "v1"
