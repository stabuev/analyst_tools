from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from seaborn.axisgrid import FacetGrid

RELEASE_DATE = pd.Timestamp("2026-03-02")
PERIOD_ORDER = ["до релиза", "после релиза"]
PLATFORM_ORDER = ["web", "ios", "android"]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    frame["activated_7d"] = frame["activated_7d"].astype(float)
    frame["period"] = pd.Categorical(
        frame["cohort_week"].ge(RELEASE_DATE).map({False: "до релиза", True: "после релиза"}),
        categories=PERIOD_ORDER,
        ordered=True,
    )
    return frame


def control_table(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby(["platform", "period"], observed=True, as_index=False)
        .agg(estimate=("activated_7d", "mean"), users=("user_id", "nunique"))
        .sort_values(["platform", "period"])
    )


def build_panel(
    frame: pd.DataFrame,
    *,
    confidence: int = 95,
    n_boot: int = 1000,
    seed: int = 20260613,
) -> FacetGrid:
    grid = sns.catplot(
        data=frame,
        x="period",
        y="activated_7d",
        col="platform",
        col_order=PLATFORM_ORDER,
        order=PERIOD_ORDER,
        kind="point",
        estimator="mean",
        errorbar=("ci", confidence),
        n_boot=n_boot,
        seed=seed,
        color="#2563eb",
        capsize=0.15,
        height=3.6,
        aspect=0.8,
    )
    grid.set_axis_labels("Период", "Доля activation_7d")
    grid.set_titles("{col_name}")
    for axis in grid.axes.flat:
        axis.set_ylim(0, 1)
        axis.set_ylabel("Доля activation_7d")
        axis.grid(axis="y", alpha=0.2)
    grid.figure.suptitle(
        f"Средняя activation и {confidence}% bootstrap CI по платформам",
        y=1.04,
    )
    return grid


def export_panel(
    input_path: Path,
    output_dir: Path,
    *,
    confidence: int = 95,
    n_boot: int = 1000,
    seed: int = 20260613,
) -> dict[str, Any]:
    frame = load_frame(input_path)
    table = control_table(frame)
    grid = build_panel(frame, confidence=confidence, n_boot=n_boot, seed=seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_path = output_dir / "platform-activation-panel.png"
    table_path = output_dir / "control-table.csv"
    grid.figure.savefig(
        figure_path,
        dpi=120,
        bbox_inches="tight",
        metadata={"Software": "analyst-tools-course"},
    )
    plt.close(grid.figure)
    table.to_csv(table_path, index=False)
    report = {
        "version": "1.0.0",
        "library": f"seaborn {sns.__version__}",
        "estimator": "mean",
        "errorbar": {"method": "ci", "level": confidence},
        "n_boot": n_boot,
        "seed": seed,
        "facet": "platform",
        "source_rows": len(frame),
        "files": {
            figure_path.name: sha256_file(figure_path),
            table_path.name: sha256_file(table_path),
        },
    }
    (output_dir / "seaborn-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a faceted Seaborn comparison")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--confidence", type=int, default=95)
    parser.add_argument("--n-boot", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260613)
    args = parser.parse_args()
    report = export_panel(
        args.input,
        args.output_dir,
        confidence=args.confidence,
        n_boot=args.n_boot,
        seed=args.seed,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
