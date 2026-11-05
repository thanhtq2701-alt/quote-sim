from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from quote_sim.models import QuoteState

AuditClock = Callable[[], datetime]


@dataclass(frozen=True)
class AuditEntry:
    """Freeze each event and its details so readers cannot rewrite the audit history."""

    timestamp: datetime
    actor_id: str
    role: str
    action: str
    quote_id: str
    from_state: QuoteState | None
    to_state: QuoteState | None
    details: Mapping[str, object]


class AuditLog:
    """Keep the event store append-only while exposing immutable snapshots to readers."""

    def __init__(self, clock: AuditClock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._entries: list[AuditEntry] = []

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    def record(
        self,
        *,
        actor_id: str,
        role: str,
        action: str,
        quote_id: str,
        from_state: QuoteState | None,
        to_state: QuoteState | None,
        details: Mapping[str, object],
    ) -> AuditEntry:
        timestamp = self._clock()
        if (
            timestamp.tzinfo is None
            or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp)
        ):
            raise ValueError("audit clock must return a timezone-aware UTC datetime")
        entry = AuditEntry(
            timestamp=timestamp,
            actor_id=actor_id,
            role=role,
            action=action,
            quote_id=quote_id,
            from_state=from_state,
            to_state=to_state,
            details=_freeze_mapping(details),
        )
        self._entries.append(entry)
        return entry


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(value) for key, value in values.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value
