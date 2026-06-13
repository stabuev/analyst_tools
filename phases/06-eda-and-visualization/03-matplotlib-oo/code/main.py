from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
from matplotlib.figure import Figure


def main() -> None:
    figure = Figure(figsize=(8, 3), layout="constrained")
    trend_axis, count_axis = figure.subplots(1, 2)
    weeks = ["до релиза", "после релиза"]
    activation = [0.72, 0.60]
    users = [12_304, 6_399]
    trend_axis.plot(weeks, activation, marker="o")
    count_axis.bar(weeks, users)
    trend_axis.set(ylabel="Доля activation_7d", ylim=(0, 1))
    count_axis.set(ylabel="Пользователи")
    print(
        json.dumps(
            {
                "axes": len(figure.axes),
                "trend_ylim": list(trend_axis.get_ylim()),
                "count_labels": [tick.get_text() for tick in count_axis.get_xticklabels()],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
