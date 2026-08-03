from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    # Сначала строим маленькую проверяемую таблицу, а не рисуем из сырых строк.
    rows = [
        {"cohort_week": "2026-02-23", "activated_users": 3, "eligible_users": 4},
        {"cohort_week": "2026-03-02", "activated_users": 2, "eligible_users": 5},
    ]
    for row in rows:
        row["activation_rate"] = row["activated_users"] / row["eligible_users"]

    # pyplot создаёт объекты, но все изменения направлены явным Figure/Axes references.
    figure, (trend_axis, count_axis) = plt.subplots(1, 2, figsize=(8, 3), layout="constrained")
    weeks = [row["cohort_week"] for row in rows]
    rates = [row["activation_rate"] for row in rows]
    users = [row["eligible_users"] for row in rows]
    trend_line = trend_axis.plot(weeks, rates, marker="o")[0]
    count_bars = count_axis.bar(weeks, users)
    trend_axis.set(ylabel="Доля activation_7d", ylim=(0, 1))
    count_axis.set(ylabel="Подходящие пользователи")

    result = {
        "control_table": rows,
        "figure_axes": len(figure.axes),
        "trend_points": len(trend_line.get_xdata()),
        "count_bars": len(count_bars),
        "trend_ylim": list(trend_axis.get_ylim()),
    }
    plt.close(figure)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
