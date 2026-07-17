from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


class FunnelDataError(ValueError):
    """Raised when funnel events violate the analytical data contract."""


@dataclass(frozen=True)
class FunnelResult:
    entrants: int
    converters: int
    conversion_rate: float


def calculate_conversion(
    events: Iterable[Mapping[str, str]],
    *,
    start_event: str = "view",
    conversion_event: str = "purchase",
) -> FunnelResult:
    entrants: set[str] = set()
    converters: set[str] = set()
    for row_number, event in enumerate(events, start=1):
        user_id = (event.get("user_id") or "").strip()
        event_name = (event.get("event") or "").strip()
        if not user_id or not event_name:
            raise FunnelDataError(f"row {row_number}: user_id and event are required")
        if event_name == start_event:
            entrants.add(user_id)
        elif event_name == conversion_event:
            converters.add(user_id)

    orphan_converters = converters - entrants
    if orphan_converters:
        raise FunnelDataError(
            "conversion without start event: " + ", ".join(sorted(orphan_converters))
        )
    if not entrants:
        raise FunnelDataError("funnel has no entrants")
    return FunnelResult(
        entrants=len(entrants),
        converters=len(converters),
        conversion_rate=len(converters) / len(entrants),
    )
