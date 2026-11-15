import json
from pathlib import Path

import pytest

from quote_sim.access import PermissionDenied, Role
from quote_sim.pricing import ValidationError
from quote_sim.users import User, UserDirectory, load_users

DATA_DIRECTORY = Path(__file__).resolve().parents[1] / "data"


def write_users(tmp_path: Path, users: list[dict[str, str]]) -> Path:
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": users}), encoding="utf-8")
    return path


def test_users_file_maps_each_id_to_its_role() -> None:
    directory = load_users(DATA_DIRECTORY / "users.json")

    assert directory.get("agent-01").role is Role.AGENT
    assert directory.get("sales-01").role is Role.SALES
    assert directory.get("manager-01").role is Role.MANAGER
    assert directory.get("viewer-01").role is Role.VIEWER


def test_unknown_user_id_is_denied() -> None:
    directory = UserDirectory([User("sales-1", "Test Sales", Role.SALES)])

    with pytest.raises(PermissionDenied, match="unknown user"):
        directory.get("intruder-1")


def test_duplicate_user_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate user id"):
        UserDirectory(
            [
                User("sales-1", "First", Role.SALES),
                User("sales-1", "Second", Role.MANAGER),
            ]
        )


def test_unknown_role_in_users_file_is_rejected(tmp_path: Path) -> None:
    path = write_users(
        tmp_path,
        [{"user_id": "boss-1", "display_name": "Boss", "role": "admin"}],
    )

    with pytest.raises(ValidationError, match="unknown role"):
        load_users(path)


def test_policy_user_id_is_reserved() -> None:
    with pytest.raises(ValidationError, match="reserved"):
        User("policy", "Not a person", Role.MANAGER)
