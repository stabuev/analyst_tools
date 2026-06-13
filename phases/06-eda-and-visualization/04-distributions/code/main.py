from __future__ import annotations

import json
import math


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def ecdf(values: list[float]) -> list[tuple[float, float]]:
    ordered = sorted(values)
    return [(value, (index + 1) / len(ordered)) for index, value in enumerate(ordered)]


def main() -> None:
    values = [70, 80, 90, 100, 110, 130, 145, 160, 300, 3600]
    print(
        json.dumps(
            {
                "median": median(values),
                "maximum": max(values),
                "ecdf_last": ecdf(values)[-1],
                "log10_max": math.log10(max(values)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
