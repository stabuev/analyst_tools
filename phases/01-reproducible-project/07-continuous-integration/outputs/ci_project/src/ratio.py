from __future__ import annotations


def ratio(part: int, total: int) -> float:
    if part < 0 or total <= 0:
        raise ValueError("part must be non-negative and total must be positive")
    if part > total:
        raise ValueError("part cannot exceed total")
    return part / total
