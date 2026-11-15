import json
import shutil
from pathlib import Path

import pytest

from quote_sim import config
from tools.check_data import check_data, main


def copy_repository_data(tmp_path: Path) -> tuple[Path, list[Path], Path, Path]:
    """Copy data/ so each test can break exactly one thing without touching the real files."""
    data = tmp_path / "data"
    shutil.copytree(config.DATA_DIRECTORY, data)
    listed = [data / path.name for path in config.PRICE_LIST_FILES]
    return data, listed, data / config.USERS_FILE.name, data / config.COST_SHEET_FILE.name


def write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def test_repository_data_passes_all_checks() -> None:
    assert (
        check_data(
            config.DATA_DIRECTORY,
            config.PRICE_LIST_FILES,
            config.USERS_FILE,
            config.COST_SHEET_FILE,
        )
        == []
    )


def test_price_list_missing_from_config_is_reported(tmp_path: Path) -> None:
    data, listed, users, costs = copy_repository_data(tmp_path)
    write_json(data / "price_list_v4.json", {"version": "v4", "products": {"sample-widget": "13.00"}})

    problems = check_data(data, listed, users, costs)

    assert problems == ["price_list_v4.json is not listed in config.PRICE_LIST_FILES"]


def test_version_not_matching_file_name_is_reported(tmp_path: Path) -> None:
    data, listed, users, costs = copy_repository_data(tmp_path)
    wrong = data / "price_list_v4.json"
    write_json(wrong, {"version": "v5", "products": {"sample-widget": "13.00"}})

    problems = check_data(data, [*listed, wrong], users, costs)

    assert any("declares version 'v5'" in problem for problem in problems)


def test_role_without_any_user_is_reported(tmp_path: Path) -> None:
    data, listed, users, costs = copy_repository_data(tmp_path)
    document = json.loads(users.read_text(encoding="utf-8"))
    document["users"] = [user for user in document["users"] if user["role"] != "viewer"]
    write_json(users, document)

    problems = check_data(data, listed, users, costs)

    assert problems == ["users.json has no viewer user; the demo needs one"]


def test_product_without_cost_in_latest_price_list_is_reported(tmp_path: Path) -> None:
    data, listed, users, costs = copy_repository_data(tmp_path)
    document = json.loads(costs.read_text(encoding="utf-8"))
    del document["costs"]["sample-cable"]
    write_json(costs, document)

    problems = check_data(data, listed, users, costs)

    assert len(problems) == 1
    assert "no cost for sample-cable (sold in v3)" in problems[0]


def test_unreadable_file_is_reported_and_other_checks_still_run(tmp_path: Path) -> None:
    data, listed, users, costs = copy_repository_data(tmp_path)
    (data / "price_list_v1.json").write_text("{ not json", encoding="utf-8")
    document = json.loads(users.read_text(encoding="utf-8"))
    document["users"] = [user for user in document["users"] if user["role"] != "agent"]
    write_json(users, document)

    problems = check_data(data, listed, users, costs)

    assert any(problem.startswith("price_list_v1.json: invalid price-list JSON") for problem in problems)
    assert "users.json has no agent user; the demo needs one" in problems


def test_main_exits_zero_for_repository_data(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    assert "Data OK" in capsys.readouterr().out
