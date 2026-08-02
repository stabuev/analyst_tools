from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
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


def load_audit_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "02-data-audit" / "outputs" / "eda_audit.py"
    spec = importlib.util.spec_from_file_location("phase06_eda_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load audit artifact: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = load_audit_module()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_audited_frame(path: Path, audit_report: dict[str, Any]) -> pd.DataFrame:
    return AUDIT.prepare_analysis_frame(path, audit_report, "activation_7d")


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
    audit_report: dict[str, Any] | None = None,
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
            "audit": None
            if audit_report is None
            else {
                "source_sha256": audit_report["source"]["sha256"],
                "readiness": audit_report["readiness"]["activation_7d"]["status"],
                "decision_ids": audit_report["readiness"]["activation_7d"]["decision_ids"],
            },
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
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit_report = AUDIT.load_report(args.audit)
    manifest = export_figure(
        load_audited_frame(args.input, audit_report),
        args.output_dir,
        audit_report=audit_report,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
