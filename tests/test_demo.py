from quote_sim.demo import run


def demo_output() -> list[str]:
    lines: list[str] = []
    run(out=lines.append)
    return lines


def test_terminal_demo_ends_with_sent_quote() -> None:
    lines = demo_output()

    assert "6. SALES sales-01 sent it -> sent (final)" in lines
    assert lines[-1].endswith("send_quote | Q-0001 | approved -> sent")


def test_terminal_demo_shows_denied_approval_attempt() -> None:
    lines = demo_output()

    assert (
        "3. SALES sales-01 tried to approve it -> denied: sales cannot perform approve_quote"
        in lines
    )
    assert any(
        "sales-01 (sales) | approve_quote" in line and "result=denied" in line for line in lines
    )


def test_terminal_demo_hides_margin_from_viewer() -> None:
    lines = demo_output()

    manager = next(line for line in lines if line.strip().startswith("MANAGER "))
    viewer = next(line for line in lines if line.strip().startswith("VIEWER "))
    assert manager.endswith("margin: 352.00 USD")
    assert viewer.endswith("margin: hidden")


def test_terminal_demo_output_is_identical_on_every_run() -> None:
    assert demo_output() == demo_output()
