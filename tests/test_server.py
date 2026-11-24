import json
import socket
from collections.abc import Iterator
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread
from typing import Any

import pytest

from server.app import MAX_REQUEST_BYTES, REQUEST_TIMEOUT_SECONDS, QuoteSimHandler
from server.scenario import MAX_STEPS, StepFormatError, replay

AGENT_DRAFT = {"action": "agent_draft", "actor": "agent-01", "request": "60 x sample-widget"}
SUBMIT = {"action": "submit", "actor": "sales-01", "quote_id": "Q-0001"}


# ----- replay, without HTTP -------------------------------------------------------------------


def test_same_steps_replay_to_identical_audit_log() -> None:
    steps = [AGENT_DRAFT, SUBMIT]

    first = replay(steps).desk.audit_entries
    second = replay(steps).desk.audit_entries

    assert first == second
    assert first[0].timestamp != first[1].timestamp


def test_refused_step_is_reported_and_replay_continues() -> None:
    result = replay(
        [
            AGENT_DRAFT,
            SUBMIT,
            {"action": "approve", "actor": "sales-01", "quote_id": "Q-0001"},
            {"action": "approve", "actor": "manager-01", "quote_id": "Q-0001"},
        ]
    )

    assert [step.ok for step in result.steps] == [True, True, False, True]
    assert "sales cannot perform approve_quote" in result.steps[2].message
    assert result.steps[3].message == "Q-0001 is now approved"


def test_malformed_step_rejects_whole_request() -> None:
    bad_line = {
        "action": "add_line",
        "actor": "sales-01",
        "quote_id": "Q-0001",
        "product_id": "sample-widget",
        "quantity": 2.5,
        "discount": "0",
    }

    with pytest.raises(StepFormatError, match="step 1: quantity must be an integer"):
        replay([AGENT_DRAFT, bad_line])


def test_unknown_action_is_rejected() -> None:
    with pytest.raises(StepFormatError, match="unknown action"):
        replay([{"action": "delete_audit_log", "actor": "manager-01"}])


def test_exactly_max_steps_is_accepted_and_one_more_is_rejected() -> None:
    harmless = {"action": "submit", "actor": "sales-01", "quote_id": "Q-9999"}

    assert len(replay([harmless] * MAX_STEPS).steps) == MAX_STEPS
    with pytest.raises(StepFormatError, match=f"at most {MAX_STEPS} steps"):
        replay([harmless] * (MAX_STEPS + 1))


def test_discount_text_with_percent_sign_becomes_exact_fraction() -> None:
    result = replay(
        [
            {"action": "agent_draft", "actor": "agent-01", "request": "1 x sample-cable"},
            {
                "action": "add_line",
                "actor": "sales-01",
                "quote_id": "Q-0001",
                "product_id": "sample-widget",
                "quantity": 1,
                "discount": "12.5%",
            },
        ]
    )

    line = result.desk.view("sales-01", "Q-0001").lines[1]
    assert str(line.discount) == "0.125"


# ----- HTTP -----------------------------------------------------------------------------------


@pytest.fixture
def port() -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuoteSimHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    content_type: str = "application/json",
) -> tuple[int, dict[str, str], bytes]:
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": content_type} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def post_replay(port: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    status, _, body = request(port, "POST", "/api/replay", json.dumps(payload).encode())
    return status, json.loads(body)


def test_page_and_assets_are_served_with_security_headers(port: int) -> None:
    for path, content_type in [
        ("/", "text/html"),
        ("/app.js", "text/javascript"),
        ("/styles.css", "text/css"),
    ]:
        status, headers, _ = request(port, "GET", path)

        assert status == 200
        assert headers["Content-Type"].startswith(content_type)
        assert "script-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Strict-Transport-Security"].startswith("max-age=")


def test_path_outside_whitelist_returns_404(port: int) -> None:
    status, _, body = request(port, "GET", "/../data/cost_sheet.json")

    assert status == 404
    assert b"7.00" not in body


def test_catalog_lists_users_and_price_lists_but_no_costs(port: int) -> None:
    status, _, body = request(port, "GET", "/api/catalog")
    catalog = json.loads(body)

    assert status == 200
    assert {user["user_id"] for user in catalog["users"]} >= {"agent-01", "manager-01"}
    assert [price_list["version"] for price_list in catalog["price_lists"]] == ["v1", "v2", "v3"]
    text = body.decode()
    assert "unit_cost" not in text
    # No value from data/cost_sheet.json may leak (none of them is also a sale price).
    for secret in ("7.00", "30.00", "1.20", "40.00"):
        assert secret not in text


def test_replay_shows_cost_to_manager_but_not_viewer(port: int) -> None:
    _, as_manager = post_replay(port, {"viewer": "manager-01", "steps": [AGENT_DRAFT]})
    _, as_viewer = post_replay(port, {"viewer": "viewer-01", "steps": [AGENT_DRAFT]})

    assert as_manager["quotes"][0]["total_margin"] == "192.00"
    assert as_manager["quotes"][0]["lines"][0]["unit_cost"] == "7.00"
    assert as_viewer["quotes"][0]["total_margin"] is None
    assert as_viewer["quotes"][0]["lines"][0]["unit_cost"] is None


def test_money_values_are_sent_as_strings(port: int) -> None:
    _, result = post_replay(port, {"viewer": "sales-01", "steps": [AGENT_DRAFT]})
    quote = result["quotes"][0]

    assert (quote["subtotal"], quote["vat"], quote["total"]) == ("612.00", "61.20", "673.20")
    assert quote["lines"][0]["unit_price"] == "12.00"


def test_unknown_viewer_returns_400(port: int) -> None:
    status, result = post_replay(port, {"viewer": "intruder-1", "steps": []})

    assert status == 400
    assert "unknown user" in result["error"]


def test_non_json_content_type_returns_400(port: int) -> None:
    status, _, body = request(
        port, "POST", "/api/replay", b"viewer=sales-01", "application/x-www-form-urlencoded"
    )

    assert status == 400
    assert "application/json" in json.loads(body)["error"]


def test_body_at_size_limit_is_accepted_and_one_byte_over_is_rejected(port: int) -> None:
    payload = json.dumps({"viewer": "sales-01", "steps": []})
    at_limit = payload + " " * (MAX_REQUEST_BYTES - len(payload))

    status_at_limit, _, _ = request(port, "POST", "/api/replay", at_limit.encode())
    status_over, _, body = request(port, "POST", "/api/replay", (at_limit + " ").encode())

    assert status_at_limit == 200
    assert status_over == 400
    assert "too large" in json.loads(body)["error"]


def test_nan_in_request_body_returns_400(port: int) -> None:
    status, _, body = request(
        port, "POST", "/api/replay", b'{"viewer": "sales-01", "steps": [], "x": NaN}'
    )

    assert status == 400
    assert "not valid JSON" in json.loads(body)["error"]


def test_deeply_nested_json_is_rejected_with_400(port: int) -> None:
    depth = 20_000  # About 40 KB: under the size limit, far beyond the JSON parser's stack.
    body = b'{"viewer": "sales-01", "steps": ' + b"[" * depth + b"]" * depth + b"}"

    status, _, response = request(port, "POST", "/api/replay", body)

    assert status == 400
    assert "not valid JSON" in json.loads(response)["error"]


def test_slow_client_is_disconnected_after_timeout(
    port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The standard library default is None (wait forever), so this line fails without the fix.
    assert QuoteSimHandler.timeout == REQUEST_TIMEOUT_SECONDS
    # A short timeout keeps the test fast; the server reads it when the connection opens.
    monkeypatch.setattr(QuoteSimHandler, "timeout", 0.5)
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(b"GET / HTTP/1.0\r\n")  # The request line, then the headers never finish.

        # The server closes the connection without answering. If it kept waiting, recv would
        # raise TimeoutError after our own 5 seconds and the test would fail.
        assert client.recv(1024) == b""


def ambiguous_line(**extra: str) -> dict[str, Any]:
    return {
        "action": "add_line",
        "actor": "sales-01",
        "quote_id": "Q-0001",
        "product_id": "sample-cable",
        "quantity": 2,
        "discount": "0.3",
        **extra,
    }


def test_ambiguous_discount_returns_422_with_both_readings(port: int) -> None:
    status, result = post_replay(
        port, {"viewer": "sales-01", "steps": [AGENT_DRAFT, ambiguous_line()]}
    )

    assert status == 422
    assert result["clarify"]["step"] == 1
    assert [(option["label"], option["discount_unit"]) for option in result["clarify"]["options"]] == [
        ("30% (fraction 0.3)", "fraction"),
        ("0.3%", "percent"),
    ]


def test_answering_with_discount_unit_runs_the_step(port: int) -> None:
    status, result = post_replay(
        port,
        {"viewer": "sales-01", "steps": [AGENT_DRAFT, ambiguous_line(discount_unit="fraction")]},
    )

    assert status == 200
    assert result["steps"][1]["ok"] is True
    assert result["quotes"][0]["lines"][1]["discount_percent"] == "30"
