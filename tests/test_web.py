from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from http.client import HTTPConnection
from threading import Thread
from urllib.parse import urlencode

import pytest

from quote_sim.web import QuoteDemoHandler


@pytest.fixture
def web_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuoteDemoHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield str(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def post_simulation(
    port: str,
    *,
    quantity: str = "2",
    discount_percent: str = "20",
    price_list_version: str = "v1",
) -> tuple[int, str]:
    connection = HTTPConnection("127.0.0.1", int(port), timeout=5)
    body = urlencode(
        {
            "quantity": quantity,
            "discount_percent": discount_percent,
            "price_list_version": price_list_version,
        }
    )
    connection.request(
        "POST",
        "/simulate",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = connection.getresponse()
    result = response.status, response.read().decode("utf-8")
    connection.close()
    return result


def test_home_page_shows_fake_data_simulation_form(web_server: str) -> None:
    connection = HTTPConnection("127.0.0.1", int(web_server), timeout=5)
    connection.request("GET", "/")
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    connection.close()

    assert response.status == 200
    assert "Run quote simulation" in body
    assert "sample-widget" in body
    assert "nothing is saved" in body


def test_valid_form_runs_manager_approval_and_displays_totals_and_audit(
    web_server: str,
) -> None:
    status, body = post_simulation(web_server)

    assert status == 200
    assert "Quote state: sent" in body
    assert "manager-demo (manager) | approve_quote" in body
    assert "Subtotal: 16.00 USD" in body
    assert "VAT: 1.60 USD" in body
    assert "Total: 17.60 USD" in body
    assert "sales-demo (sales) | send_quote" in body


def test_discount_at_auto_approval_threshold_records_policy_approval(
    web_server: str,
) -> None:
    status, body = post_simulation(web_server, discount_percent="10")

    assert status == 200
    assert "policy (policy) | auto_approve" in body
    assert "manager-demo (manager) | approve_quote" not in body


def test_discount_just_above_threshold_waits_for_manager(
    web_server: str,
) -> None:
    status, body = post_simulation(web_server, discount_percent="10.1")

    assert status == 200
    assert "manager-demo (manager) | approve_quote" in body


def test_v2_price_list_changes_total_and_is_shown_as_evidence(
    web_server: str,
) -> None:
    status, body = post_simulation(web_server, price_list_version="v2")

    assert status == 200
    assert "Price list: v2" in body
    assert "Total: 21.12 USD" in body
    assert "price_list_version=v2" in body


@pytest.mark.parametrize(
    ("quantity", "discount_percent"),
    [
        ("0", "20"),
        ("2", "31"),
    ],
)
def test_invalid_form_input_returns_validation_error_without_success(
    web_server: str,
    quantity: str,
    discount_percent: str,
) -> None:
    status, body = post_simulation(
        web_server,
        quantity=quantity,
        discount_percent=discount_percent,
    )

    assert status == 400
    assert "error" in body
    assert "Quote state: sent" not in body
    assert "Traceback" not in body
