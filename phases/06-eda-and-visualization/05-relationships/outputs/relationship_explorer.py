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

PLATFORM_COLORS = {"web": "#2563eb", "ios": "#059669", "android": "#dc2626"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_analysis_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path).drop_duplicates("user_id").copy()
    frame = frame[frame["observed_days"].eq(7)]
    frame["activated_7d"] = frame["activated_7d"].astype(bool)
    frame["sessions_7d"] = pd.to_numeric(frame["sessions_7d"])
    return frame


def control_table(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby(["platform", "sessions_7d"], observed=True, as_index=False)
        .agg(
            activation_rate=("activated_7d", "mean"),
            users=("user_id", "nunique"),
        )
        .sort_values(["platform", "sessions_7d"])
    )


def reconcile_rate(table: pd.DataFrame) -> float:
    return float((table["activation_rate"] * table["users"]).sum() / table["users"].sum())


def overplotting_report(frame: pd.DataFrame) -> dict[str, int]:
    coordinates = frame.groupby(["sessions_7d", "activated_7d"]).size()
    return {
        "observations": len(frame),
        "unique_coordinates": len(coordinates),
        "overplotted_observations": int((coordinates - 1).clip(lower=0).sum()),
        "maximum_stack": int(coordinates.max()),
    }


def build_figure(
    frame: pd.DataFrame,
    *,
    seed: int = 20260613,
) -> tuple[Figure, pd.DataFrame]:
    table = control_table(frame)
    rng = np.random.default_rng(seed)
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    raw_axis, summary_axis = axes
    for platform, group in frame.groupby("platform", observed=True):
        y = group["activated_7d"].astype(int).to_numpy()
        jitter = rng.uniform(-0.06, 0.06, size=len(group))
        raw_axis.scatter(
            group["sessions_7d"],
            y + jitter,
            alpha=0.45,
            s=22,
            label=platform,
            color=PLATFORM_COLORS[platform],
        )
    raw_axis.set(
        title="Наблюдения с jitter",
        xlabel="sessions_7d",
        ylabel="activated_7d",
        yticks=[0, 1],
        yticklabels=["false", "true"],
    )
    raw_axis.legend(title="platform")
    for platform, group in table.groupby("platform", observed=True):
        summary_axis.plot(
            group["sessions_7d"],
            group["activation_rate"],
            marker="o",
            label=platform,
            color=PLATFORM_COLORS[platform],
        )
    summary_axis.set(
        title="Стратифицированные rates",
        xlabel="sessions_7d",
        ylabel="activation rate",
        ylim=(0, 1),
    )
    summary_axis.legend(title="platform")
    for axis in axes:
        axis.grid(alpha=0.2)
    return figure, table


def export_relationship(
    input_path: Path,
    output_dir: Path,
    *,
    seed: int = 20260613,
) -> dict[str, Any]:
    frame = load_analysis_frame(input_path)
    table = control_table(frame)
    figure, _ = build_figure(frame, seed=seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_path = output_dir / "sessions-activation.png"
    control_path = output_dir / "control-table.csv"
    figure.savefig(figure_path, dpi=120, metadata={"Software": "analyst-tools-course"})
    plt.close(figure)
    table.to_csv(control_path, index=False)
    overall_rate = float(frame["activated_7d"].mean())
    report = {
        "version": "1.0.0",
        "question": "How does activation vary with sessions within platforms?",
        "association_only": True,
        "source_rows": len(frame),
        "overall_activation_rate": overall_rate,
        "reconciled_activation_rate": reconcile_rate(table),
        "overplotting": overplotting_report(frame),
        "strata": sorted(frame["platform"].unique().tolist()),
        "files": {
            figure_path.name: {"sha256": sha256_file(figure_path)},
            control_path.name: {"sha256": sha256_file(control_path)},
        },
    }
    report_path = output_dir / "relationship-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Explore a stratified relationship")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260613)
    args = parser.parse_args()
    report = export_relationship(args.input, args.output_dir, seed=args.seed)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
