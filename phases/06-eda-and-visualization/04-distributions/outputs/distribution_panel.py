from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_values(path: Path, column: str) -> tuple[pd.Series, pd.Series]:
    frame = pd.read_csv(path).drop_duplicates("user_id")
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    invalid = values[values < 0]
    valid = values[values >= 0]
    return valid.astype(float), invalid.astype(float)


def freedman_diaconis_edges(values: pd.Series) -> np.ndarray:
    array = values.to_numpy(dtype=float)
    if len(array) < 2 or np.all(array == array[0]):
        center = float(array[0]) if len(array) else 0.0
        return np.array([center - 0.5, center + 0.5])
    q25, q75 = np.quantile(array, [0.25, 0.75])
    width = 2 * (q75 - q25) / np.cbrt(len(array))
    if width <= 0:
        bins = max(1, math.ceil(math.log2(len(array)) + 1))
    else:
        bins = max(1, math.ceil((array.max() - array.min()) / width))
    bins = min(bins, 50)
    return np.linspace(array.min(), array.max(), bins + 1)


def robust_summary(values: pd.Series) -> dict[str, float | int]:
    q25, median, q75 = values.quantile([0.25, 0.5, 0.75])
    iqr = q75 - q25
    upper_fence = q75 + 1.5 * iqr
    return {
        "count": int(values.count()),
        "minimum": float(values.min()),
        "q25": float(q25),
        "median": float(median),
        "q75": float(q75),
        "iqr": float(iqr),
        "maximum": float(values.max()),
        "upper_fence": float(upper_fence),
        "above_upper_fence": int(values.gt(upper_fence).sum()),
    }


def ecdf(values: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(values.to_numpy(dtype=float))
    y = np.arange(1, len(x) + 1) / len(x)
    return x, y


def build_panel(
    values: pd.Series,
    *,
    column: str,
    scale: str = "linear",
) -> tuple[Figure, dict[str, Any]]:
    if scale not in {"linear", "log"}:
        raise ValueError("scale must be linear or log")
    if scale == "log" and values.le(0).any():
        raise ValueError("log scale requires strictly positive values")
    edges = freedman_diaconis_edges(values)
    summary = robust_summary(values)
    x, y = ecdf(values)
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    histogram_axis, ecdf_axis = axes
    histogram_axis.hist(values, bins=edges, color="#60a5fa", edgecolor="white")
    histogram_axis.axvline(summary["median"], color="#b91c1c", linestyle="--", label="median")
    histogram_axis.set(title="Histogram", xlabel=column, ylabel="Наблюдения", xscale=scale)
    histogram_axis.legend()
    ecdf_axis.step(x, y, where="post", color="#1d4ed8")
    ecdf_axis.set(
        title="ECDF",
        xlabel=column,
        ylabel="Доля наблюдений ≤ x",
        ylim=(0, 1.02),
        xscale=scale,
    )
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.suptitle(f"Распределение {column}: хвосты остаются видимыми")
    return figure, {
        "column": column,
        "scale": scale,
        "bin_policy": "Freedman-Diaconis, capped at 50 bins",
        "bin_edges": [float(value) for value in edges],
        "summary": summary,
    }


def export_panel(
    input_path: Path,
    column: str,
    output_dir: Path,
    *,
    scale: str = "linear",
) -> dict[str, Any]:
    valid, invalid = load_values(input_path, column)
    figure, report = build_panel(valid, column=column, scale=scale)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_path = output_dir / f"{column}-distribution.png"
    figure.savefig(figure_path, dpi=120, metadata={"Software": "analyst-tools-course"})
    plt.close(figure)
    report.update(
        {
            "invalid_negative_values": [float(value) for value in invalid],
            "source_rows": int(len(valid) + len(invalid)),
            "plotted_rows": int(len(valid)),
            "figure": {
                "path": figure_path.name,
                "sha256": sha256_file(figure_path),
                "bytes": figure_path.stat().st_size,
            },
        }
    )
    report_path = output_dir / "distribution-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a distribution diagnostic panel")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--column", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scale", choices=("linear", "log"), default="linear")
    args = parser.parse_args()
    report = export_panel(args.input, args.column, args.output_dir, scale=args.scale)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
