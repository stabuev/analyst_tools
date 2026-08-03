from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

ANALYSIS_ID = "activation_7d"
ARTIFACT_VERSION = "2.0.0"
CONTROL_COLUMNS = ["cohort_week", "activated_users", "eligible_users", "activation_rate"]
REQUIRED_FRAME_COLUMNS = {
    "user_id",
    "cohort_week",
    "observed_days",
    "activated_7d",
}
STYLE = {
    "figure.figsize": (10, 4.5),
    "figure.dpi": 120,
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "svg.hashsalt": "analyst-tools-06-03",
}


class FigureContractError(ValueError):
    """Raised when audited data cannot produce a trustworthy figure package."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_audit_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FigureContractError(f"cannot read audit report: {error}") from error
    if not isinstance(report, dict):
        raise FigureContractError("audit report must be a JSON object")
    return report


def analysis_evidence(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        readiness = report["readiness"][ANALYSIS_ID]
        plan = readiness["selection_plan"]
    except (KeyError, TypeError) as error:
        raise FigureContractError(
            f"audit report has no selection plan for {ANALYSIS_ID}"
        ) from error
    if not isinstance(readiness, dict) or not isinstance(plan, dict):
        raise FigureContractError("readiness and selection plan must be JSON objects")
    status = readiness.get("status")
    if status == "blocked":
        raise FigureContractError(
            f"analysis {ANALYSIS_ID} is blocked by {readiness.get('blocker_ids', [])}"
        )
    if status not in {"ready", "ready_with_decisions"}:
        raise FigureContractError(f"unsupported readiness status: {status!r}")
    return readiness, plan


def load_source(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype="string", keep_default_na=False)
    except OSError as error:
        raise FigureContractError(f"cannot read input: {error}") from error
    except pd.errors.ParserError as error:
        raise FigureContractError(f"cannot parse input CSV: {error}") from error


def convert_selected_types(frame: pd.DataFrame, column_types: dict[str, str]) -> pd.DataFrame:
    converted = frame.copy()
    try:
        for column, kind in column_types.items():
            if kind == "integer":
                converted[column] = pd.to_numeric(converted[column]).astype("Int64")
            elif kind == "decimal":
                converted[column] = pd.to_numeric(converted[column]).astype("Float64")
            elif kind == "boolean":
                converted[column] = (
                    converted[column]
                    .str.casefold()
                    .map({"true": True, "false": False})
                    .astype("boolean")
                )
            elif kind == "timestamp":
                converted[column] = pd.to_datetime(converted[column], utc=True)
            elif kind == "date":
                converted[column] = pd.to_datetime(converted[column])
            else:
                converted[column] = converted[column].astype("string")
    except (KeyError, TypeError, ValueError) as error:
        raise FigureContractError(f"cannot apply selected column types: {error}") from error
    return converted


def prepare_analysis_frame(path: Path, report: dict[str, Any]) -> pd.DataFrame:
    _, plan = analysis_evidence(report)
    source_sha256 = plan.get("source_sha256")
    source = report.get("source")
    if not isinstance(source, dict) or source.get("sha256") != source_sha256:
        raise FigureContractError("audit source evidence does not match its selection plan")
    if not isinstance(source_sha256, str) or sha256_file(path) != source_sha256:
        raise FigureContractError("input checksum does not match audit evidence")

    required_columns = plan.get("required_columns")
    column_types = plan.get("column_types")
    key = plan.get("key")
    if not isinstance(required_columns, list) or not required_columns:
        raise FigureContractError("selection plan must declare required_columns")
    if not isinstance(column_types, dict):
        raise FigureContractError("selection plan must declare column_types")
    if not isinstance(key, list) or not key:
        raise FigureContractError("selection plan must declare a non-empty key")

    frame = load_source(path)
    missing = sorted((set(required_columns) | set(key)) - set(frame.columns))
    if missing:
        raise FigureContractError(f"input misses selection columns: {missing}")

    if plan.get("drop_exact_duplicates"):
        duplicate_mask = frame.duplicated(key, keep=False)
        grouper: str | list[str] = key[0] if len(key) == 1 else key
        for _, group in frame.loc[duplicate_mask].groupby(grouper, dropna=False):
            if len(group.drop_duplicates()) != 1:
                raise FigureContractError(
                    "selection plan cannot resolve conflicting duplicate keys"
                )
        frame = frame.drop_duplicates(key, keep="first")

    eligibility = plan.get("eligibility")
    if eligibility:
        if not isinstance(eligibility, dict) or eligibility.get("operator") != "eq":
            raise FigureContractError("unsupported eligibility rule in selection plan")
        column = eligibility.get("column")
        if column not in frame:
            raise FigureContractError(f"eligibility column is missing: {column!r}")
        frame = frame[frame[column].astype("string").eq(str(eligibility.get("value")))]

    selected = convert_selected_types(frame[required_columns], column_types).reset_index(drop=True)
    validate_analysis_frame(selected)
    return selected


def validate_analysis_frame(frame: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_FRAME_COLUMNS - set(frame.columns))
    if missing:
        raise FigureContractError(f"analysis frame misses required columns: {missing}")
    if frame.empty:
        raise FigureContractError("analysis frame is empty after audited selection")
    if frame["user_id"].isna().any() or frame["user_id"].astype("string").str.strip().eq("").any():
        raise FigureContractError("analysis frame contains a missing user_id")
    if not frame["user_id"].is_unique:
        raise FigureContractError("analysis frame must have one row per user_id")
    if frame["cohort_week"].isna().any():
        raise FigureContractError("analysis frame contains an invalid cohort_week")
    if frame["observed_days"].isna().any() or not frame["observed_days"].eq(7).all():
        raise FigureContractError("activation_7d requires a complete seven-day window")
    if frame["activated_7d"].isna().any():
        raise FigureContractError("activation_7d outcome is missing for an eligible user")
    invalid_outcomes = ~frame["activated_7d"].isin([True, False])
    if invalid_outcomes.any():
        raise FigureContractError("activated_7d must contain only boolean outcomes")


def activation_table(frame: pd.DataFrame) -> pd.DataFrame:
    validate_analysis_frame(frame)
    table = (
        frame.groupby("cohort_week", as_index=False, observed=True)
        .agg(
            activated_users=("activated_7d", "sum"),
            eligible_users=("user_id", "nunique"),
        )
        .sort_values("cohort_week", kind="stable")
        .reset_index(drop=True)
    )
    table["activated_users"] = table["activated_users"].astype("Int64")
    table["eligible_users"] = table["eligible_users"].astype("Int64")
    table["activation_rate"] = (table["activated_users"] / table["eligible_users"]).astype(
        "Float64"
    )
    if table["activated_users"].gt(table["eligible_users"]).any():
        raise FigureContractError("activation numerator exceeds its denominator")
    if not table["eligible_users"].sum() == frame["user_id"].nunique():
        raise FigureContractError("control table denominator does not reconcile to input users")
    return table[CONTROL_COLUMNS]


def parse_release_date(value: str | date | pd.Timestamp) -> pd.Timestamp:
    try:
        if isinstance(value, str):
            parsed = date.fromisoformat(value)
            result = pd.Timestamp(parsed)
        else:
            result = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise FigureContractError("release date must use YYYY-MM-DD") from error
    if result.tzinfo is not None or result != result.normalize():
        raise FigureContractError("release date must be a timezone-free calendar date")
    return result


def build_figure(
    table: pd.DataFrame,
    *,
    release_date: str | date | pd.Timestamp,
) -> tuple[Figure, tuple[Axes, Axes]]:
    if list(table.columns) != CONTROL_COLUMNS or table.empty:
        raise FigureContractError("control table has an unexpected schema or no rows")
    release = parse_release_date(release_date)
    if not table["activation_rate"].between(0, 1).all():
        raise FigureContractError("activation rate must stay inside [0, 1]")

    with matplotlib.rc_context(STYLE):
        figure, axes = plt.subplots(1, 2, layout="constrained")
        trend_axis, count_axis = axes
        trend_axis.plot(
            table["cohort_week"],
            table["activation_rate"],
            color="#2563eb",
            marker="o",
            linewidth=2,
        )
        trend_axis.axvline(release, color="#4b5563", linestyle="--", label="релиз")
        trend_axis.set(
            title="Семидневная активация",
            xlabel="Неделя регистрации",
            ylabel="Доля пользователей",
            ylim=(0, 1),
        )
        trend_axis.legend()
        trend_axis.grid(axis="y", alpha=0.25)
        count_axis.bar(
            table["cohort_week"],
            table["eligible_users"],
            width=5,
            color="#94a3b8",
        )
        count_axis.set(
            title="Знаменатель по когортам",
            xlabel="Неделя регистрации",
            ylabel="Подходящие пользователи",
        )
        count_axis.grid(axis="y", alpha=0.25)
        figure.suptitle("Activation: значение и знаменатель")
        for axis in axes:
            axis.tick_params(axis="x", rotation=35)
    return figure, (trend_axis, count_axis)


def control_table_for_export(table: pd.DataFrame) -> pd.DataFrame:
    exported = table.copy()
    exported["cohort_week"] = exported["cohort_week"].dt.strftime("%Y-%m-%d")
    return exported


def file_metadata(path: Path) -> dict[str, int | str]:
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def export_figure(
    frame: pd.DataFrame,
    output_dir: Path,
    *,
    release_date: str | date | pd.Timestamp,
    audit_report: dict[str, Any],
    stem: str = "activation-overview",
) -> dict[str, Any]:
    readiness, _ = analysis_evidence(audit_report)
    release = parse_release_date(release_date)
    table = activation_table(frame)
    output_dir.mkdir(parents=True, exist_ok=True)
    control_path = output_dir / f"{stem}-control.csv"
    png_path = output_dir / f"{stem}.png"
    svg_path = output_dir / f"{stem}.svg"

    control_table_for_export(table).to_csv(
        control_path,
        index=False,
        lineterminator="\n",
        float_format="%.6f",
    )
    figure, axes = build_figure(table, release_date=release)
    try:
        with matplotlib.rc_context(STYLE):
            figure.savefig(
                png_path,
                dpi=120,
                metadata={"Software": "analyst-tools-course"},
            )
            figure.savefig(
                svg_path,
                metadata={"Date": None, "Creator": "analyst-tools-course"},
            )
    finally:
        plt.close(figure)

    source = audit_report.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("sha256"), str):
        raise FigureContractError("audit report misses source checksum evidence")
    manifest = {
        "version": ARTIFACT_VERSION,
        "artifact": "static-figure-factory",
        "runtime": {
            "python": platform.python_version(),
            "matplotlib": matplotlib.__version__,
            "pandas": pd.__version__,
            "backend": matplotlib.get_backend(),
        },
        "question": {
            "analysis_id": ANALYSIS_ID,
            "metric": "activation_rate",
            "numerator": "activated_users",
            "denominator": "eligible_users",
            "comparison_axis": "cohort_week",
            "release_date": release.date().isoformat(),
            "interpretation_boundary": "observed change does not prove a release effect",
        },
        "figure": {
            "axes": len(axes),
            "size_inches": [10.0, 4.5],
            "dpi": 120,
            "layout": "constrained",
            "rate_domain": [0.0, 1.0],
            "svg_hashsalt": STYLE["svg.hashsalt"],
        },
        "data": {
            "source_rows": len(frame),
            "control_rows": len(table),
            "audit": {
                "report_sha256": sha256_json(audit_report),
                "source_sha256": source["sha256"],
                "readiness": readiness["status"],
                "decision_ids": readiness.get("decision_ids", []),
            },
        },
        "files": {
            control_path.name: file_metadata(control_path),
            png_path.name: file_metadata(png_path),
            svg_path.name: file_metadata(svg_path),
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a reproducible activation figure package from audited data"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--release-date", required=True, help="calendar date in YYYY-MM-DD")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        audit_report = load_audit_report(args.audit)
        manifest = export_figure(
            prepare_analysis_frame(args.input, audit_report),
            args.output_dir,
            release_date=args.release_date,
            audit_report=audit_report,
        )
    except FigureContractError as error:
        parser.error(str(error))
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
