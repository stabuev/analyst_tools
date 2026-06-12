from __future__ import annotations

import pytest

from funnel import FunnelDataError, calculate_conversion


@pytest.fixture
def basic_events() -> list[dict[str, str]]:
    return [
        {"user_id": "u-1", "event": "view"},
        {"user_id": "u-2", "event": "view"},
        {"user_id": "u-3", "event": "view"},
        {"user_id": "u-1", "event": "purchase"},
        {"user_id": "u-3", "event": "purchase"},
    ]


def test_calculates_conversion_for_unique_users(basic_events) -> None:
    result = calculate_conversion(basic_events)

    assert result.entrants == 3
    assert result.converters == 2
    assert result.conversion_rate == pytest.approx(2 / 3)


def test_duplicate_events_do_not_inflate_counts(basic_events) -> None:
    duplicated = [
        *basic_events,
        {"user_id": "u-1", "event": "view"},
        {"user_id": "u-1", "event": "purchase"},
    ]

    result = calculate_conversion(duplicated)

    assert (result.entrants, result.converters) == (3, 2)


@pytest.mark.parametrize(
    ("entrants", "converters", "expected"),
    [
        (1, 0, 0.0),
        (1, 1, 1.0),
        (4, 1, 0.25),
    ],
)
def test_conversion_boundaries(entrants, converters, expected) -> None:
    events = [
        *({"user_id": f"u-{index}", "event": "view"} for index in range(entrants)),
        *(
            {"user_id": f"u-{index}", "event": "purchase"}
            for index in range(converters)
        ),
    ]

    result = calculate_conversion(events)

    assert result.conversion_rate == pytest.approx(expected)


def test_rejects_conversion_without_start_event() -> None:
    events = [{"user_id": "u-1", "event": "purchase"}]

    with pytest.raises(FunnelDataError, match="conversion without start"):
        calculate_conversion(events)


def test_rejects_empty_funnel() -> None:
    with pytest.raises(FunnelDataError, match="no entrants"):
        calculate_conversion([])


def test_rejects_incomplete_event() -> None:
    with pytest.raises(FunnelDataError, match="user_id and event are required"):
        calculate_conversion([{"user_id": "", "event": "view"}])
