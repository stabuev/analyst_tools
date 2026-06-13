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
from matplotlib.axes import Axes
from matplotlib.figure import Figure

STYLE = {
    "figure.figsize": (10, 4.5),
    "figure.dpi": 120,
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_clean_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame = frame.drop_duplicates("user_id").copy()
    frame["registered_at"] = pd.to_datetime(frame["registered_at"], utc=True)
    frame["cohort_week"] = pd.to_datetime(frame["cohort_week"])
    frame = frame[frame["observed_days"].eq(7)]
    return frame


def activation_table(frame: pd.DataFrame) -> pd.DataFrame:
    result = (
        frame.groupby("cohort_week", as_index=False, observed=True)
        .agg(activation=("activated_7d", "mean"), users=("user_id", "nunique"))
        .sort_values("cohort_week")
    )
    return result


def build_figure(frame: pd.DataFrame) -> tuple[Figure, tuple[Axes, Axes], pd.DataFrame]:
    table = activation_table(frame)
    with plt.rc_context(STYLE):
        figure, axes = plt.subplots(1, 2, layout="constrained")
        trend_axis, count_axis = axes
        trend_axis.plot(
            table["cohort_week"],
            table["activation"],
            color="#2563eb",
            marker="o",
            linewidth=2,
        )
        trend_axis.axvline(pd.Timestamp("2026-03-02"), color="#9ca3af", linestyle="--")
        trend_axis.set(
            title="Семидневная активация",
            xlabel="Неделя регистрации",
            ylabel="Доля пользователей",
            ylim=(0, 1),
        )
        trend_axis.grid(axis="y", alpha=0.25)
        count_axis.bar(
            table["cohort_week"],
            table["users"],
            width=5,
            color="#94a3b8",
        )
        count_axis.set(
            title="Размер когорт",
            xlabel="Неделя регистрации",
            ylabel="Пользователи",
        )
        count_axis.grid(axis="y", alpha=0.25)
        figure.suptitle("Activation: значение и знаменатель")
        for axis in axes:
            axis.tick_params(axis="x", rotation=35)
    return figure, (trend_axis, count_axis), table


def export_figure(
    frame: pd.DataFrame,
    output_dir: Path,
    *,
    stem: str = "activation-overview",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    figure, axes, table = build_figure(frame)
    png_path = output_dir / f"{stem}.png"
    svg_path = output_dir / f"{stem}.svg"
    figure.savefig(png_path, dpi=120, metadata={"Software": "analyst-tools-course"})
    figure.savefig(svg_path, metadata={"Date": None, "Creator": "analyst-tools-course"})
    plt.close(figure)
    manifest = {
        "version": "1.0.0",
        "backend": matplotlib.get_backend(),
        "figure": {
            "axes": len(axes),
            "size_inches": [10.0, 4.5],
            "dpi": 120,
            "layout": "constrained",
        },
        "data": {
            "source_rows": len(frame),
            "cohorts": len(table),
            "activation_min": float(table["activation"].min()),
            "activation_max": float(table["activation"].max()),
        },
        "files": {
            png_path.name: {
                "bytes": png_path.stat().st_size,
                "sha256": sha256_file(png_path),
            },
            svg_path.name: {
                "bytes": svg_path.stat().st_size,
                "sha256": sha256_file(svg_path),
            },
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a reproducible Matplotlib figure")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = export_figure(load_clean_frame(args.input), args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
