"""Fake user directory: roles come from data, never from the caller's own claim."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from quote_sim.access import PermissionDenied, Role
from quote_sim.pricing import ValidationError

POLICY_ACTOR_ID = "policy"


@dataclass(frozen=True)
class User:
    """Bind an id to exactly one role so separation-of-duties checks compare stable ids."""

    user_id: str
    display_name: str
    role: Role

    def __post_init__(self) -> None:
        for field_name in ("user_id", "display_name"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{field_name} must be a non-empty string")
        if not isinstance(self.role, Role):
            raise ValidationError("role must be a Role")
        if self.user_id == POLICY_ACTOR_ID:
            # The audit log uses "policy" for automatic approvals; a human with that id
            # would make those entries ambiguous.
            raise ValidationError(f"user id {POLICY_ACTOR_ID!r} is reserved")


class UserDirectory:
    """Resolve actor ids to roles; an unknown id is treated as an unauthorized actor."""

    def __init__(self, users: Iterable[User]) -> None:
        self._users: dict[str, User] = {}
        for user in users:
            if not isinstance(user, User):
                raise TypeError("users must contain User records")
            if user.user_id in self._users:
                raise ValidationError(f"duplicate user id: {user.user_id}")
            self._users[user.user_id] = user

    @property
    def users(self) -> tuple[User, ...]:
        return tuple(self._users.values())

    def get(self, user_id: str) -> User:
        try:
            return self._users[user_id]
        except (KeyError, TypeError) as error:
            raise PermissionDenied(f"unknown user: {user_id}") from error


def load_users(path: str | Path) -> UserDirectory:
    """Load the fake directory and reject unknown roles instead of guessing one."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ValidationError(f"cannot read users file: {path}") from error
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid users JSON: {path}") from error

    if not isinstance(document, dict) or not isinstance(document.get("users"), list):
        raise ValidationError("users file must contain a users list")

    users: list[User] = []
    for record in document["users"]:
        if not isinstance(record, dict):
            raise ValidationError("each user must be an object")
        try:
            role = Role(record.get("role"))
        except ValueError as error:
            raise ValidationError(f"unknown role: {record.get('role')}") from error
        users.append(
            User(
                user_id=record.get("user_id"),
                display_name=record.get("display_name"),
                role=role,
            )
        )
    return UserDirectory(users)
