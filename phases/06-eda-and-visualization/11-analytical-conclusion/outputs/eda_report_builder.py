from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import plotly.io as pio

PHASE_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DATE = pd.Timestamp("2026-03-02")

QUESTION_BRIEF = {
    "version": "2.0.0",
    "review": {
        "status": "reviewed",
        "method": "06/01 visual-question-brief-rubric",
        "note": "Rubric review checks reasoning; data readiness is evidenced in audit.json.",
    },
    "decision": (
        "Choose one predeclared segment for the next technical diagnostic, or leave the "
        "release explanation unconfirmed when the difference does not localize."
    ),
    "question": (
        "For new users with a complete seven-day window, how does activation_7d change "
        "across weekly cohorts before and after 2026-03-02, and does the change differ "
        "across predeclared platform and acquisition-channel segments?"
    ),
    "population": "New subscription-service users with a complete seven-day window.",
    "observation_window": "Seven complete days after registration.",
    "analysis_unit": "One user and their seven-day activation outcome.",
    "metric": {
        "name": "activation_7d",
        "numerator": "Unique users with activated_7d=true.",
        "denominator": "Unique users with observed_days=7 after duplicate resolution.",
    },
    "comparison": {
        "operation": "change over time with predeclared segment comparisons",
        "time_grain": "cohort_week",
        "reference_point": "2026-03-02 release date",
        "segments": ["platform", "acquisition_channel"],
    },
    "possible_outcomes": [
        {
            "observation": "The decline appears across all major segments.",
            "next_step": "Investigate a mechanism shared across platforms and channels.",
        },
        {
            "observation": "The aggregate decline is compatible with changing channel mix.",
            "next_step": "Compare like-for-like channels before escalating a release hypothesis.",
        },
        {
            "observation": "No stable difference remains after comparable-window checks.",
            "next_step": "Do not attribute the aggregate movement to the release.",
        },
    ],
    "data_readiness": {
        "status": "requires-audit",
        "evidence": "audit.json",
        "gates": [
            "unique user grain or an explicit duplicate-resolution policy",
            "complete observation windows",
            "reproducible numerator and denominator",
            "comparable periods and segments",
        ],
    },
    "interpretation_boundary": (
        "The report may describe checked associations. Release causality requires an "
        "experiment or a separate causal design."
    ),
    "stop_rule": (
        "Stop this EDA after the predeclared platform and acquisition-channel comparisons; "
        "record additional segment questions separately."
    ),
}


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module(lesson: str, filename: str) -> ModuleType:
    return load_module(
        f"phase06_{lesson.replace('-', '_')}",
        PHASE_ROOT / lesson / "outputs" / filename,
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def activation_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    period = (
        frame.groupby("period", observed=True)
        .agg(activation=("activated_7d", "mean"), users=("user_id", "nunique"))
        .to_dict(orient="index")
    )
    android = (
        frame[frame["platform"].eq("android")]
        .groupby("period", observed=True)
        .agg(activation=("activated_7d", "mean"), users=("user_id", "nunique"))
        .to_dict(orient="index")
    )
    channel = pd.crosstab(frame["period"], frame["acquisition_channel"], normalize="index")
    before = float(period["до релиза"]["activation"])
    after = float(period["после релиза"]["activation"])
    return {
        "period": period,
        "android": android,
        "channel_share": channel.to_dict(orient="index"),
        "change_percentage_points": (after - before) * 100,
    }


def segment_figure(frame: pd.DataFrame, path: Path) -> None:
    table = frame.groupby(["platform", "period"], observed=True, as_index=False).agg(
        activation=("activated_7d", "mean"), users=("user_id", "nunique")
    )
    platforms = ["web", "ios", "android"]
    periods = ["до релиза", "после релиза"]
    colors = {"до релиза": "#64748b", "после релиза": "#2563eb"}
    figure, axis = plt.subplots(figsize=(8, 4.5), layout="constrained")
    width = 0.34
    positions = range(len(platforms))
    for offset_index, period in enumerate(periods):
        values = []
        labels = []
        for platform in platforms:
            row = table[table["platform"].eq(platform) & table["period"].eq(period)]
            values.append(float(row["activation"].iloc[0]) if not row.empty else 0.0)
            labels.append(int(row["users"].iloc[0]) if not row.empty else 0)
        offset = (offset_index - 0.5) * width
        bars = axis.bar(
            [position + offset for position in positions],
            values,
            width=width,
            label=period,
            color=colors[period],
        )
        axis.bar_label(bars, labels=[f"n={value}" for value in labels], padding=3, fontsize=8)
    axis.set(
        title="Activation до и после релиза по платформам",
        xlabel="Платформа",
        ylabel="Доля пользователей",
        ylim=(0, 1),
        xticks=list(positions),
        xticklabels=platforms,
    )
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    figure.savefig(path, dpi=120, metadata={"Software": "analyst-tools-course"})
    plt.close(figure)


def report_markdown(
    metrics: dict[str, Any],
    bootstrap_report: dict[str, Any],
    *,
    source_rows: int,
    raw_rows: int,
) -> str:
    before = metrics["period"]["до релиза"]
    after = metrics["period"]["после релиза"]
    android_before = metrics["android"].get("до релиза", {"activation": float("nan"), "users": 0})
    android_after = metrics["android"].get(
        "после релиза",
        {"activation": float("nan"), "users": 0},
    )
    paid_before = metrics["channel_share"].get("до релиза", {}).get("paid_social", 0.0)
    paid_after = metrics["channel_share"].get("после релиза", {}).get("paid_social", 0.0)
    intervals = {row["group"]: row for row in bootstrap_report["groups"]}
    return f"""# EDA-report: активация после мартовского релиза

## Вопрос

Как изменилась семидневная активация после релиза 2026-03-02 и какой сегмент нужно
проверить следующим?

## Наблюдения

1. После удаления повторной доставки и исключения неполных окон в анализ вошло
   {source_rows} из {raw_rows} строк.
2. Activation снизилась с {before["activation"]:.1%} (n={before["users"]}) до
   {after["activation"]:.1%} (n={after["users"]}), изменение
   {metrics["change_percentage_points"]:.1f} процентного пункта.
3. Доля paid_social изменилась с {paid_before:.1%} до {paid_after:.1%}, поэтому общий
   тренд частично связан с изменением состава каналов.
4. В Android activation изменилась с {android_before["activation"]:.1%}
   (n={android_before["users"]}) до {android_after["activation"]:.1%}
   (n={android_after["users"]}).
5. 95% percentile bootstrap interval по пользователям:
   до релиза [{intervals["до релиза"]["lower"]:.1%},
   {intervals["до релиза"]["upper"]:.1%}], после релиза
   [{intervals["после релиза"]["lower"]:.1%},
   {intervals["после релиза"]["upper"]:.1%}].

## Объяснения-гипотезы

- Изменение channel mix может объяснять часть aggregate decline.
- Отдельное ухудшение Android после релиза согласуется с версией о regression 2.4.
- Наблюдательные данные и графики не доказывают причинный эффект релиза.

## Ограничения

- Данные синтетические и описывают только первые семь дней после регистрации.
- Последние неполные окна исключены, а не трактованы как отсутствие activation.
- Малые сегменты имеют широкую неопределенность; sample size показан рядом с estimates.
- EDA не заменяет эксперимент или технический event-level разбор.

## Следующий шаг

Проверить Android 2.4 по шагам onboarding и crash/error events, сохранив channel и
cohort composition в сравнении. Если технический сигнал подтвердится, сформировать
отдельную продуктовую гипотезу и дизайн проверки.

## Карта доказательств

| Утверждение | Расчет | Артефакт |
|---|---|---|
| Общий тренд | activation по cohort week | `figures/activation-overview.png` |
| Размер когорт | unique users | `figures/activation-overview.svg` |
| Сегментный паттерн | activation по platform и period | `figures/segment-comparison.png` |
| Отдельные аномалии | user-level rows | `interactive/anomaly-explorer.html` |
| Linked selection | Vega-Lite encodings и filter | `specs/linked-segments.vl.json` |
| Пригодность входа | grain, nulls, ranges, windows | `audit.json` |
"""


def build_delivery(
    input_path: Path,
    contract_path: Path,
    output_dir: Path,
    *,
    seed: int = 20260613,
    bootstrap_repeats: int = 1000,
) -> dict[str, Any]:
    audit_module = module("02-data-audit", "eda_audit.py")
    figure_module = module("03-matplotlib-oo", "figure_factory.py")
    bootstrap_module = module("06-uncertainty", "bootstrap_visualizer.py")
    plotly_module = module("08-plotly", "anomaly_explorer.py")
    altair_module = module("09-altair", "chart_spec_builder.py")
    review_module = module("10-design-and-accessibility", "visual_review.py")

    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    interactive_dir = output_dir / "interactive"
    specs_dir = output_dir / "specs"
    figures_dir.mkdir(exist_ok=True)
    interactive_dir.mkdir(exist_ok=True)
    specs_dir.mkdir(exist_ok=True)

    raw_frame = audit_module.load_frame(input_path)
    audit = audit_module.audit_frame(
        raw_frame,
        audit_module.load_contract(contract_path),
        source_sha256=audit_module.sha256_file(input_path),
        contract_sha256=audit_module.sha256_file(contract_path),
    )
    write_json(output_dir / "audit.json", audit)

    question = deepcopy(QUESTION_BRIEF)
    question["data_readiness"]["status"] = audit["readiness"]["activation_7d"]["status"]
    question["data_readiness"]["decision_ids"] = audit["readiness"]["activation_7d"]["decision_ids"]
    write_json(output_dir / "question.json", question)

    frame = audit_module.prepare_analysis_frame(input_path, audit, "activation_7d")
    frame["period"] = (
        frame["cohort_week"].ge(RELEASE_DATE).map({False: "до релиза", True: "после релиза"})
    )
    matplotlib.rcParams["svg.hashsalt"] = "analyst-tools-course"
    figure_module.export_figure(frame, figures_dir, audit_report=audit)
    segment_figure(frame, figures_dir / "segment-comparison.png")

    boot_frame = bootstrap_module.load_frame(input_path)
    _, bootstrap_report = bootstrap_module.build_report(
        boot_frame,
        repeats=bootstrap_repeats,
        seed=seed,
    )
    metrics = activation_metrics(frame)
    (output_dir / "report.md").write_text(
        report_markdown(
            metrics,
            bootstrap_report,
            source_rows=len(frame),
            raw_rows=len(raw_frame),
        ),
        encoding="utf-8",
    )

    interactive_frame = plotly_module.load_frame(input_path)
    plotly_figure = plotly_module.build_figure(interactive_frame)
    pio.write_html(
        plotly_figure,
        interactive_dir / "anomaly-explorer.html",
        include_plotlyjs=True,
        full_html=True,
        auto_open=False,
        div_id="anomaly-explorer",
        config={"displaylogo": False, "responsive": True},
    )

    altair_spec = altair_module.build_spec(altair_module.load_frame(input_path))
    write_json(specs_dir / "linked-segments.vl.json", altair_spec)
    visual_review = review_module.audit_review(review_module.EXAMPLE_REVIEW)
    write_json(output_dir / "visual-review.json", visual_review)

    manifest_files: dict[str, Any] = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative = path.relative_to(output_dir).as_posix()
            manifest_files[relative] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    manifest = {
        "version": "1.0.0",
        "builder": "eda_report_builder.py",
        "input": {
            "path": str(input_path),
            "sha256": sha256_file(input_path),
            "raw_rows": len(raw_frame),
            "analysis_rows": len(frame),
        },
        "parameters": {
            "release_date": RELEASE_DATE.date().isoformat(),
            "bootstrap_seed": seed,
            "bootstrap_repeats": bootstrap_repeats,
            "resampling_unit": "user",
        },
        "files": manifest_files,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the phase 06 EDA report delivery")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260613)
    parser.add_argument("--bootstrap-repeats", type=int, default=1000)
    args = parser.parse_args()
    manifest = build_delivery(
        args.input,
        args.contract,
        args.output_dir,
        seed=args.seed,
        bootstrap_repeats=args.bootstrap_repeats,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
