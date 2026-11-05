"""Serve a small, stateless browser demo using only Python's standard library."""

import os
from decimal import Decimal
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from quote_sim.demo import (
    DemoResult,
    DEMO_AUTO_APPROVE_THRESHOLD,
    DEMO_DISCOUNT,
    DEMO_MAX_DISCOUNT,
    DEMO_QUANTITY,
    run_scenario,
)
from quote_sim.pricing import ValidationError

MAX_REQUEST_BYTES = 4096
PERCENT = Decimal("100")


class QuoteDemoHandler(BaseHTTPRequestHandler):
    """Expose only a fake-data simulation; requests never persist quote state."""

    server_version = "quote-sim"

    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/":
            self._respond(404, _render_page("<h1>Not found</h1>"))
            return
        self._respond(200, _render_form())

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/simulate":
            self._respond(404, _render_page("<h1>Not found</h1>"))
            return
        if (
            self.headers.get("Content-Type", "").split(";", maxsplit=1)[0].strip().lower()
            != "application/x-www-form-urlencoded"
        ):
            self._respond(415, _render_error("Use the quote form to submit a simulation."))
            return

        content_length = self.headers.get("Content-Length", "")
        if not content_length.isascii() or not content_length.isdecimal():
            self._respond(400, _render_error("Invalid form request."))
            return
        try:
            body_size = int(content_length)
        except ValueError:
            self._respond(400, _render_error("Invalid form request."))
            return
        if body_size > MAX_REQUEST_BYTES:
            self._respond(413, _render_error("Form request is too large."))
            return

        try:
            self.connection.settimeout(10)
            body = self.rfile.read(body_size).decode("utf-8")
            fields = parse_qs(body, keep_blank_values=True, strict_parsing=True)
            quantity = int(_single_field(fields, "quantity"))
            discount_percent = Decimal(_single_field(fields, "discount_percent"))
            price_list_version = _single_field(fields, "price_list_version")
            if not discount_percent.is_finite() or discount_percent < 0:
                raise ValidationError("discount must be a non-negative percentage")
            if discount_percent > DEMO_MAX_DISCOUNT * PERCENT:
                raise ValidationError(
                    f"discount must not exceed {DEMO_MAX_DISCOUNT * PERCENT}%"
                )
            result = run_scenario(
                quantity=quantity,
                discount=discount_percent / PERCENT,
                price_list_version=price_list_version,
            )
        except TimeoutError:
            self._respond(408, _render_error("Form request timed out."))
            return
        except (ArithmeticError, UnicodeDecodeError, ValueError) as error:
            self._respond(400, _render_error(str(error)))
            return
        except ArithmeticError:
            self._respond(400, _render_error("Input exceeds the supported calculation range."))
            return

        self._respond(200, _render_result(result, quantity, discount_percent))

    def _respond(self, status: int, page: str) -> None:
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)


def _single_field(fields: dict[str, list[str]], name: str) -> str:
    values = fields.get(name, [])
    if len(values) != 1 or not values[0].strip():
        raise ValidationError(f"provide one value for {name}")
    return values[0].strip()


def _render_page(content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>quote-sim</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; background: #f3f5f8; color: #172033; }}
    main {{ max-width: 760px; margin: 3rem auto; padding: 2rem; background: white;
      border-radius: 12px; box-shadow: 0 8px 30px #15233a18; }}
    h1 {{ margin-top: 0; }}
    .note {{ color: #45536b; }}
    form {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem; align-items: end; margin: 2rem 0; }}
    label {{ display: grid; gap: .4rem; font-weight: 600; }}
    input, select, button {{ box-sizing: border-box; padding: .7rem; font: inherit; }}
    button {{ grid-column: 1 / -1; color: white; background: #2457c5; border: 0;
      border-radius: 6px; cursor: pointer; }}
    pre {{ overflow-x: auto; padding: 1rem; background: #f3f5f8; border-radius: 8px; }}
    .error {{ padding: 1rem; background: #fff0ef; border-left: 4px solid #bd3028; }}
  </style>
</head>
<body>
  <main>
    <h1>quote-sim</h1>
    <p class="note">A fake-data quote workflow demo. No account is needed and nothing is saved.</p>
    {content}
  </main>
</body>
</html>"""


def _render_form(error_message: str | None = None) -> str:
    error = (
        f'<p class="error">{escape(error_message)}</p>'
        if error_message is not None
        else ""
    )
    max_percent = DEMO_MAX_DISCOUNT * PERCENT
    return _render_page(
        f"""{error}
<form action="/simulate" method="post">
  <label>Price-list version
    <select name="price_list_version">
      <option value="v1">v1 — sample-widget, $10.00</option>
      <option value="v2">v2 — sample-widget, $12.00</option>
    </select>
  </label>
  <label>Quantity
    <input name="quantity" type="number" min="1" step="1" value="{DEMO_QUANTITY}" required>
  </label>
  <label>Discount (%)
    <input name="discount_percent" type="number" min="0" max="{max_percent}"
      step="0.1" value="{DEMO_DISCOUNT * PERCENT}" required>
  </label>
  <button type="submit">Run quote simulation</button>
</form>
<p class="note">Maximum discount: {max_percent}%. Auto-approval threshold:
{DEMO_AUTO_APPROVE_THRESHOLD * PERCENT}%.</p>"""
    )


def _render_error(message: str) -> str:
    return _render_form(message)


def _render_result(
    result: DemoResult,
    quantity: int,
    discount_percent: Decimal,
) -> str:
    # Keep rendering data escaped because some values originate from submitted form fields.
    quote_state = escape(result.quote.state.value)
    line_items = "\n".join(
        f"  {item.quantity} x {item.product_id} @ {item.unit_price} "
        f"({item.discount * PERCENT}% discount)"
        for item in result.quote.line_items
    )
    totals = result.totals
    audit = "\n".join(
        f"  {entry.actor_id} ({entry.role}) | {entry.action} | "
        f"{entry.from_state.value if entry.from_state else 'none'} -> "
        f"{entry.to_state.value if entry.to_state else 'none'}"
        + (
            f" | {', '.join(f'{key}={value}' for key, value in entry.details.items())}"
            if entry.details
            else ""
        )
        for entry in result.audit_entries
    )
    summary = (
        f"Price list: {result.price_list_version}\n"
        f"Quote state: {quote_state}\n"
        f"Line items:\n{line_items}\n"
        f"Subtotal: {totals.subtotal} USD\n"
        f"VAT: {totals.vat} USD\n"
        f"Total: {totals.total} USD\n\n"
        f"Audit log:\n{audit}"
    )
    return _render_page(
        f"""<p>Simulation completed: quantity {quantity}, discount
{escape(str(discount_percent))}%.</p>
<pre>{escape(summary)}</pre>
<p><a href="/">Run another simulation</a></p>"""
    )


def main() -> None:
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError as error:
        raise SystemExit("PORT must be a valid TCP port number") from error
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be between 1 and 65535")

    server = ThreadingHTTPServer(("0.0.0.0", port), QuoteDemoHandler)
    print(f"quote-sim web demo listening on port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping quote-sim web demo.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
