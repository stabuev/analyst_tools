from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

RELEASE_DATE = pd.Timestamp("2026-03-02")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path).drop_duplicates("user_id").copy()
    frame["cohort_week"] = pd.to_datetime(frame["cohort_week"])
    frame = frame[frame["observed_days"].eq(7)]
    if frame["activated_7d"].dtype != bool:
        frame["activated_7d"] = (
            frame["activated_7d"]
            .astype("string")
            .map({"True": True, "False": False, "true": True, "false": False})
        )
    frame["period"] = np.where(
        frame["cohort_week"].lt(RELEASE_DATE),
        "до релиза",
        "после релиза",
    )
    return frame


def bootstrap_rate(
    values: np.ndarray,
    *,
    repeats: int,
    confidence: float,
    rng: np.random.Generator,
) -> dict[str, float]:
    if len(values) == 0:
        raise ValueError("cannot bootstrap an empty group")
    indices = rng.integers(0, len(values), size=(repeats, len(values)))
    estimates = values[indices].mean(axis=1)
    alpha = (1 - confidence) / 2
    lower, upper = np.quantile(estimates, [alpha, 1 - alpha])
    return {
        "estimate": float(values.mean()),
        "lower": float(lower),
        "upper": float(upper),
    }


def interval_table(
    frame: pd.DataFrame,
    *,
    group_column: str = "period",
    repeats: int = 2000,
    confidence: float = 0.95,
    seed: int = 20260613,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for group, part in frame.groupby(group_column, sort=True, observed=True):
        interval = bootstrap_rate(
            part["activated_7d"].astype(float).to_numpy(),
            repeats=repeats,
            confidence=confidence,
            rng=rng,
        )
        rows.append(
            {
                "group": str(group),
                **interval,
                "users": int(part["user_id"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def build_figure(table: pd.DataFrame, *, confidence: float) -> Figure:
    figure, axis = plt.subplots(figsize=(7, 4), layout="constrained")
    positions = np.arange(len(table))
    lower_error = table["estimate"] - table["lower"]
    upper_error = table["upper"] - table["estimate"]
    axis.errorbar(
        positions,
        table["estimate"],
        yerr=np.vstack([lower_error, upper_error]),
        fmt="o",
        capsize=5,
        color="#1d4ed8",
    )
    axis.set(
        title=f"Activation rate и {confidence:.0%} bootstrap interval",
        xlabel="Группа",
        ylabel="Доля пользователей",
        ylim=(0, 1),
        xticks=positions,
        xticklabels=table["group"],
    )
    for position, row in table.iterrows():
        axis.annotate(
            f"n={int(row['users'])}",
            (position, row["upper"]),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
        )
    axis.grid(axis="y", alpha=0.2)
    return figure


def build_report(
    frame: pd.DataFrame,
    *,
    group_column: str = "period",
    repeats: int = 2000,
    confidence: float = 0.95,
    seed: int = 20260613,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    table = interval_table(
        frame,
        group_column=group_column,
        repeats=repeats,
        confidence=confidence,
        seed=seed,
    )
    user_ids = "\n".join(sorted(frame["user_id"].astype(str)))
    report = {
        "version": "1.0.0",
        "method": "percentile bootstrap",
        "metric": "mean of activated_7d",
        "resampling_unit": "user",
        "group_column": group_column,
        "repeats": repeats,
        "confidence": confidence,
        "seed": seed,
        "source_rows": len(frame),
        "unique_users": int(frame["user_id"].nunique()),
        "source_user_ids_sha256": sha256_text(user_ids),
        "groups": table.to_dict(orient="records"),
    }
    return table, report


def export_report(
    input_path: Path,
    output_dir: Path,
    *,
    group_column: str = "period",
    repeats: int = 2000,
    confidence: float = 0.95,
    seed: int = 20260613,
) -> dict[str, Any]:
    frame = load_frame(input_path)
    table, report = build_report(
        frame,
        group_column=group_column,
        repeats=repeats,
        confidence=confidence,
        seed=seed,
    )
    figure = build_figure(table, confidence=confidence)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_path = output_dir / "activation-intervals.png"
    table_path = output_dir / "intervals.csv"
    figure.savefig(figure_path, dpi=120, metadata={"Software": "analyst-tools-course"})
    plt.close(figure)
    table.to_csv(table_path, index=False)
    report["files"] = {
        figure_path.name: hashlib.sha256(figure_path.read_bytes()).hexdigest(),
        table_path.name: hashlib.sha256(table_path.read_bytes()).hexdigest(),
    }
    report_path = output_dir / "bootstrap-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build bootstrap intervals by user")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--group-column", default="period")
    parser.add_argument("--repeats", type=int, default=2000)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=20260613)
    args = parser.parse_args()
    report = export_report(
        args.input,
        args.output_dir,
        group_column=args.group_column,
        repeats=args.repeats,
        confidence=args.confidence,
        seed=args.seed,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
