from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd

EXPECTED_FIELD_TYPES = {
    "sessions_7d": "quantitative",
    "onboarding_seconds": "quantitative",
    "platform": "nominal",
    "user_id": "nominal",
    "app_version": "nominal",
    "cohort_week": "temporal",
}


def load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path).drop_duplicates("user_id").copy()
    frame = frame[frame["observed_days"].eq(7)]
    frame = frame[pd.to_numeric(frame["onboarding_seconds"], errors="coerce").ge(0)]
    frame["cohort_week"] = pd.to_datetime(frame["cohort_week"])
    return frame


def build_chart(frame: pd.DataFrame) -> alt.ConcatChart:
    alt.data_transformers.disable_max_rows()
    brush = alt.selection_interval(name="journey_brush")
    scatter = (
        alt.Chart(frame)
        .mark_circle(opacity=0.65, size=70)
        .encode(
            x=alt.X("sessions_7d:Q", title="Сессии за 7 дней"),
            y=alt.Y("onboarding_seconds:Q", title="Onboarding, секунды"),
            color=alt.Color("platform:N", title="Платформа"),
            tooltip=[
                alt.Tooltip("user_id:N"),
                alt.Tooltip("platform:N"),
                alt.Tooltip("app_version:N"),
                alt.Tooltip("cohort_week:T"),
            ],
        )
        .add_params(brush)
        .properties(width=420, height=300, title="Выберите область наблюдений")
    )
    bars = (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("platform:N", title="Платформа"),
            y=alt.Y("count():Q", title="Пользователи"),
            color=alt.Color("platform:N", legend=None),
        )
        .transform_filter(brush)
        .properties(width=220, height=300, title="Состав выбранной области")
    )
    return alt.hconcat(scatter, bars).resolve_scale(color="shared")


def walk_encodings(value: Any) -> list[dict[str, Any]]:
    encodings: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "field" in value:
            encodings.append(value)
        encoding = value.get("encoding")
        if isinstance(encoding, dict):
            encodings.extend(walk_encodings(encoding))
        for item in value.values():
            if item is not encoding:
                encodings.extend(walk_encodings(item))
    elif isinstance(value, list):
        for item in value:
            encodings.extend(walk_encodings(item))
    return encodings


def validate_semantics(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for encoding in walk_encodings(spec):
        field = encoding["field"]
        expected = EXPECTED_FIELD_TYPES.get(field)
        actual = encoding.get("type")
        if expected and actual != expected:
            errors.append(f"{field} must be {expected}, got {actual}")
    serialized = json.dumps(spec, sort_keys=True)
    if "journey_brush" not in serialized:
        errors.append("missing journey_brush parameter")
    if '"filter"' not in serialized or '"param": "journey_brush"' not in serialized:
        errors.append("linked view must filter by journey_brush")
    if "hconcat" not in spec:
        errors.append("spec must contain linked hconcat views")
    return errors


def build_spec(frame: pd.DataFrame) -> dict[str, Any]:
    spec = build_chart(frame).to_dict(validate=True)
    errors = validate_semantics(spec)
    if errors:
        raise ValueError("; ".join(errors))
    return spec


def export_spec(input_path: Path, output_path: Path) -> dict[str, Any]:
    frame = load_frame(input_path)
    spec = build_spec(frame)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "version": "1.0.0",
        "library": f"altair {alt.__version__}",
        "rows": len(frame),
        "output": str(output_path),
        "semantic_errors": [],
        "selection": "journey_brush",
        "views": len(spec["hconcat"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a validated Vega-Lite spec")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = export_spec(args.input, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
