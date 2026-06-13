from __future__ import annotations

import json
import random


def bootstrap_mean(values: list[float], *, repeats: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [sum(rng.choices(values, k=len(values))) / len(values) for _ in range(repeats)]


def main() -> None:
    draws = sorted(bootstrap_mean([1, 1, 0, 1, 0], repeats=1000, seed=7))
    print(
        json.dumps(
            {
                "estimate": 0.6,
                "lower": draws[25],
                "upper": draws[974],
                "resampling_unit": "user",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
