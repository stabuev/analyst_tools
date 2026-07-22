from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "time_normalizer.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("time_normalizer", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    time = load_artifact()

    orders = pd.read_csv(DATA)
    calendar = time.add_business_calendar(
        orders,
        column="ordered_at",
        timezone="Europe/Moscow",
    )
    print("Календарный день заказа в бизнес-зоне:")
    print(
        calendar[["order_id", "ordered_at_utc", "ordered_at_local", "local_day"]]
        .head(3)
        .to_string(index=False)
    )

    delivery = pd.DataFrame(
        {
            "started_at": ["2026-03-29T01:30:00+01:00", None],
            "finished_at": ["2026-03-29T03:30:00+02:00", None],
        },
        index=["D1", "D2"],
    )
    duration = time.elapsed_time(delivery["started_at"], delivery["finished_at"])
    delivery = delivery.assign(
        elapsed_time=duration,
        elapsed_hours=time.duration_to_hours(duration),
    )
    print("\nФактически прошедшее время:")
    print(delivery.to_string())


if __name__ == "__main__":
    main()
