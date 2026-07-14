from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import catboost
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
DATA_ROOT = PHASE_16_ROOT / "data" / "tiny"

DEFAULT_POLICY_PATH = DATA_ROOT / "strong_model_segment_policy_spec.json"
DEFAULT_CATBOOST_SPEC_PATH = DATA_ROOT / "catboost_model_spec.json"
DEFAULT_EARLY_STOPPING_REPORT_PATH = (
    PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_report.json"
)
DEFAULT_EARLY_STOPPING_SPEC_PATH = (
    PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_serialized_spec.json"
)
DEFAULT_SHAP_REPORT_PATH = PHASE_16_ROOT / "06-shap" / "outputs" / "shap_explanation_report.json"
DEFAULT_SHAP_SPEC_PATH = PHASE_16_ROOT / "06-shap" / "outputs" / "shap_explanation_serialized_spec.json"
DEFAULT_BASELINE_PACKAGE_REPORT_PATH = (
    PHASE_15_ROOT / "15-model-card" / "outputs" / "ml_baseline_package_report.json"
)
DEFAULT_IMBALANCE_PREDICTIONS_PATH = (
    PHASE_15_ROOT / "11-imbalanced-data" / "outputs" / "imbalance_predictions.csv"
)
DEFAULT_FEATURES_PATH = UPSTREAM_DATA_ROOT / "ml_raw_features.csv"
DEFAULT_LABELS_PATH = UPSTREAM_DATA_ROOT / "ml_labels.csv"
DEFAULT_MANIFEST_PATH = UPSTREAM_DATA_ROOT / "ml_split_manifest.csv"

GENERATED_AT = "2026-07-05T12:00:00+03:00"


class StrongModelSegmentAnalysisError(ValueError):
    """Raised when strong-model segment analysis inputs cannot be parsed."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows([{field: csv_ready(row.get(field)) for field in fieldnames} for row in rows])


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def csv_ready(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return str(rounded(value))
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def rounded(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def passed(check_id: str, observed: Any = None, expected: Any = None, sample: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def failed(
    check_id: str,
    observed: Any = None,
    expected: Any = None,
    sample: Any = None,
    *,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def warning_ids(checks: list[dict[str, Any]]) -> list[str]:
    return [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]


def blocking_errors(checks: list[dict[str, Any]]) -> list[str]:
    return [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]


def bool_label(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return int(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return 1
    if text in {"false", "0", "no"}:
        return 0
    raise StrongModelSegmentAnalysisError(f"Cannot parse boolean label: {value!r}")


def parse_selected(value: Any) -> bool:
    return bool(bool_label(value))


def safe_rate(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return rounded(float(numerator) / float(denominator))


def validate_required_files(paths: dict[str, Path]) -> dict[str, Any]:
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        return failed("input_files_are_present", sorted(paths), "all required input files", missing)
    return passed("input_files_are_present", sorted(paths), "all required input files")


def validate_policy(
    *,
    policy: dict[str, Any],
    catboost_spec: dict[str, Any],
    early_report: dict[str, Any],
    early_spec: dict[str, Any],
    shap_report: dict[str, Any],
    shap_spec: dict[str, Any],
    baseline_package_report: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    required = {
        "segment_analysis_audit_id",
        "problem_id",
        "baseline_package_id",
        "baseline_model_id",
        "catboost_baseline_id",
        "source_catboost_model_id",
        "early_stopping_model_id",
        "early_stopping_audit_id",
        "shap_explanation_audit_id",
        "analysis_split",
        "final_holdout_split",
        "selection_policy",
        "slice_policy",
        "score_band_policy",
        "metric_policy",
        "small_n_policy",
        "delta_policy",
        "interpretation_policy",
        "warning_policy",
        "output",
    }
    missing = sorted(required - set(policy))
    if missing:
        errors.append({"field": "root", "missing": missing})

    expected_identity = {
        "problem_id": catboost_spec.get("problem_id"),
        "baseline_package_id": catboost_spec.get("baseline_package_id"),
        "baseline_model_id": catboost_spec.get("baseline_package_source_model_id"),
        "catboost_baseline_id": catboost_spec.get("catboost_baseline_id"),
        "source_catboost_model_id": catboost_spec.get("candidate", {}).get("model_id"),
        "early_stopping_model_id": early_spec.get("early_stopping_model_id"),
        "early_stopping_audit_id": early_spec.get("early_stopping_audit_id"),
        "shap_explanation_audit_id": shap_spec.get("shap_explanation_audit_id"),
        "analysis_split": shap_spec.get("explanation_summary", {}).get("explain_split", "validation"),
        "final_holdout_split": early_spec.get("fit_summary", {}).get("final_holdout_split"),
    }
    for field, expected in expected_identity.items():
        if policy.get(field) != expected:
            errors.append({"field": field, "observed": policy.get(field), "expected": expected})

    baseline_summary = baseline_package_report.get("summary", {})
    baseline_package_id = baseline_summary.get("package_id") or baseline_package_report.get("package_id")
    if baseline_package_id != policy.get("baseline_package_id"):
        errors.append(
            {
                "field": "baseline_package_report.summary.package_id",
                "observed": baseline_package_id,
                "expected": policy.get("baseline_package_id"),
            }
        )
    if baseline_summary.get("readiness_status") != "phase_15_complete_baseline_package":
        errors.append(
            {
                "field": "baseline_package_report.summary.readiness_status",
                "observed": baseline_summary.get("readiness_status"),
                "expected": "phase_15_complete_baseline_package",
            }
        )
    if early_report.get("valid") is not True:
        errors.append({"field": "early_report.valid", "observed": early_report.get("valid"), "expected": True})
    if early_report.get("summary", {}).get("readiness_status") != "ready_for_feature_importance_lesson":
        errors.append(
            {
                "field": "early_report.summary.readiness_status",
                "observed": early_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_feature_importance_lesson",
            }
        )
    if shap_report.get("valid") is not True:
        errors.append({"field": "shap_report.valid", "observed": shap_report.get("valid"), "expected": True})
    if shap_report.get("summary", {}).get("readiness_status") != "ready_for_segment_analysis_lesson":
        errors.append(
            {
                "field": "shap_report.summary.readiness_status",
                "observed": shap_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_segment_analysis_lesson",
            }
        )

    selection_policy = policy.get("selection_policy")
    if not isinstance(selection_policy, dict):
        errors.append({"field": "selection_policy", "reason": "object required"})
    else:
        if selection_policy.get("budget_count") != 2:
            errors.append({"field": "selection_policy.budget_count", "observed": selection_policy.get("budget_count"), "expected": 2})
        if selection_policy.get("test_used_for_segment_analysis") is not False:
            errors.append(
                {
                    "field": "selection_policy.test_used_for_segment_analysis",
                    "observed": selection_policy.get("test_used_for_segment_analysis"),
                    "expected": False,
                }
            )
    slice_policy = policy.get("slice_policy")
    if not isinstance(slice_policy, dict):
        errors.append({"field": "slice_policy", "reason": "object required"})
    else:
        for field in (
            "forbid_training_split_slice_claims",
            "forbid_final_holdout_slice_claims",
            "forbid_dropping_small_slices",
        ):
            if slice_policy.get(field) is not True:
                errors.append({"field": f"slice_policy.{field}", "observed": slice_policy.get(field), "expected": True})
        required_dimensions = set(slice_policy.get("required_dimensions") or [])
        if not {"segment_id", "platform", "country"}.issubset(required_dimensions):
            errors.append(
                {
                    "field": "slice_policy.required_dimensions",
                    "observed": sorted(required_dimensions),
                    "expected": ["segment_id", "platform", "country"],
                }
            )
        derived_dimensions = set(slice_policy.get("derived_dimensions") or [])
        if not {"business_cohort", "score_band"}.issubset(derived_dimensions):
            errors.append(
                {
                    "field": "slice_policy.derived_dimensions",
                    "observed": sorted(derived_dimensions),
                    "expected": ["business_cohort", "score_band"],
                }
            )
    score_band_policy = policy.get("score_band_policy")
    if not isinstance(score_band_policy, dict):
        errors.append({"field": "score_band_policy", "reason": "object required"})
    else:
        if score_band_policy.get("membership_policy") != "computed_per_model_score":
            errors.append(
                {
                    "field": "score_band_policy.membership_policy",
                    "observed": score_band_policy.get("membership_policy"),
                    "expected": "computed_per_model_score",
                }
            )
        bands = score_band_policy.get("bands")
        if not isinstance(bands, list) or len(bands) < 3:
            errors.append({"field": "score_band_policy.bands", "reason": "at least 3 bands required"})
        else:
            previous_upper = 0.0
            for index, band in enumerate(bands):
                if not {"band_id", "lower", "upper"}.issubset(band):
                    errors.append({"field": f"score_band_policy.bands[{index}]", "reason": "bad band"})
                    continue
                if float(band["lower"]) != previous_upper:
                    errors.append(
                        {
                            "field": f"score_band_policy.bands[{index}].lower",
                            "observed": band["lower"],
                            "expected": previous_upper,
                        }
                    )
                if float(band["upper"]) <= float(band["lower"]):
                    errors.append({"field": f"score_band_policy.bands[{index}].upper", "reason": "must exceed lower"})
                previous_upper = float(band["upper"])
    small_n_policy = policy.get("small_n_policy")
    if not isinstance(small_n_policy, dict):
        errors.append({"field": "small_n_policy", "reason": "object required"})
    else:
        if int(small_n_policy.get("min_rows_per_slice", 0)) < 2:
            errors.append({"field": "small_n_policy.min_rows_per_slice", "observed": small_n_policy.get("min_rows_per_slice"), "expected": ">= 2"})
        if small_n_policy.get("action") != "warn_not_hide":
            errors.append({"field": "small_n_policy.action", "observed": small_n_policy.get("action"), "expected": "warn_not_hide"})
    delta_policy = policy.get("delta_policy")
    if not isinstance(delta_policy, dict):
        errors.append({"field": "delta_policy", "reason": "object required"})
    else:
        if delta_policy.get("baseline_name") != "baseline" or delta_policy.get("candidate_name") != "catboost":
            errors.append(
                {
                    "field": "delta_policy.model_names",
                    "observed": [delta_policy.get("baseline_name"), delta_policy.get("candidate_name")],
                    "expected": ["baseline", "catboost"],
                }
            )
        if "score_band" not in set(delta_policy.get("critical_dimensions") or []):
            errors.append(
                {
                    "field": "delta_policy.critical_dimensions",
                    "observed": delta_policy.get("critical_dimensions"),
                    "expected": "score_band included",
                }
            )
    output = policy.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "report_file",
            "confusion_row_file",
            "slice_metric_file",
            "delta_file",
            "small_n_warning_file",
            "hidden_failure_file",
            "score_band_shift_file",
            "audit_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return [
            failed(
                "segment_policy_matches_upstream_handoff",
                errors,
                "same baseline package, early-stopped CatBoost, SHAP handoff and validation-only segment policy",
            )
        ]
    return [
        passed(
            "segment_policy_matches_upstream_handoff",
            {
                "segment_analysis_audit_id": policy["segment_analysis_audit_id"],
                "baseline_model_id": policy["baseline_model_id"],
                "early_stopping_model_id": policy["early_stopping_model_id"],
                "analysis_split": policy["analysis_split"],
            },
            "policy matches upstream handoffs",
        )
    ]


def joined_frame(features_path: Path, labels_path: Path, manifest_path: Path) -> pd.DataFrame:
    features = pd.read_csv(features_path)
    labels = pd.read_csv(labels_path)
    manifest = pd.read_csv(manifest_path)
    for frame_name, frame in {
        "features": features,
        "labels": labels,
        "manifest": manifest,
    }.items():
        if "snapshot_id" not in frame.columns:
            raise StrongModelSegmentAnalysisError(f"{frame_name} table misses snapshot_id")
        if frame["snapshot_id"].duplicated().any():
            raise StrongModelSegmentAnalysisError(f"{frame_name} table contains duplicate snapshot_id")
    frame = features.merge(labels[["snapshot_id", "churned_14d"]], on="snapshot_id", how="left")
    frame = frame.merge(
        manifest[["snapshot_id", "split", "split_order", "user_id", "prediction_time"]],
        on="snapshot_id",
        how="inner",
    )
    frame["target"] = frame["churned_14d"].map(bool_label)
    frame["acquisition_channel"] = frame["acquisition_channel"].fillna("").replace("", "__MISSING__")
    frame["segment_id"] = frame["platform"].astype(str) + "_" + frame["country"].astype(str).str.lower()
    frame["business_cohort"] = frame["plan_id"].astype(str) + ":" + frame["country"].astype(str)
    return frame.sort_values(["split_order", "snapshot_id"]).reset_index(drop=True)


def expected_feature_order(catboost_spec: dict[str, Any]) -> list[str]:
    contract = catboost_spec.get("feature_contract", {})
    return list(contract.get("numeric_features", [])) + list(contract.get("categorical_features", []))


def prepare_features(
    frame: pd.DataFrame,
    numeric_features: list[str],
    categorical_features: list[str],
    missing_category_token: str,
) -> pd.DataFrame:
    matrix = frame[numeric_features + categorical_features].copy()
    for column in numeric_features:
        matrix[column] = pd.to_numeric(matrix[column], errors="coerce")
    for column in categorical_features:
        matrix[column] = matrix[column].fillna(missing_category_token).replace("", missing_category_token).astype(str)
    return matrix


def train_early_stopped_catboost(
    *,
    frame: pd.DataFrame,
    catboost_spec: dict[str, Any],
    early_spec: dict[str, Any],
) -> CatBoostClassifier:
    contract = catboost_spec["feature_contract"]
    numeric_features = list(contract["numeric_features"])
    categorical_features = list(contract["categorical_features"])
    missing_category_token = contract.get("missing_category_token", "__MISSING__")
    feature_order = numeric_features + categorical_features
    matrix = prepare_features(frame, numeric_features, categorical_features, missing_category_token)
    train_mask = frame["split"] == early_spec["fit_summary"]["fit_split"]
    eval_mask = frame["split"] == early_spec["fit_summary"]["eval_split"]
    model = CatBoostClassifier(**early_spec["catboost_params"])
    model.fit(
        Pool(
            matrix.loc[train_mask, feature_order],
            label=frame.loc[train_mask, "target"].astype(int),
            cat_features=categorical_features,
        ),
        eval_set=Pool(
            matrix.loc[eval_mask, feature_order],
            label=frame.loc[eval_mask, "target"].astype(int),
            cat_features=categorical_features,
        ),
    )
    return model


def score_band(score: float, bands: list[dict[str, Any]]) -> str:
    for index, band in enumerate(bands):
        lower = float(band["lower"])
        upper = float(band["upper"])
        is_last = index == len(bands) - 1
        if score >= lower and (score < upper or (is_last and score <= upper)):
            return str(band["band_id"])
    raise StrongModelSegmentAnalysisError(f"score {score} is outside configured score bands")


def baseline_prediction_rows(
    *,
    imbalance_predictions_path: Path,
    frame: pd.DataFrame,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    predictions = pd.read_csv(imbalance_predictions_path)
    selected = predictions.loc[
        (predictions["model_id"] == policy["baseline_model_id"])
        & (predictions["split"] == policy["analysis_split"])
    ].copy()
    if selected.empty:
        raise StrongModelSegmentAnalysisError("baseline predictions are empty for the analysis split")
    selected["score_rank"] = selected["score"].rank(method="first", ascending=False).astype(int)
    target_by_id = frame.set_index("snapshot_id")["target"].to_dict()
    rows: list[dict[str, Any]] = []
    for row in selected.sort_values(["score_rank", "snapshot_id"]).to_dict("records"):
        snapshot_id = row["snapshot_id"]
        actual = int(row["actual_label"])
        if actual != int(target_by_id[snapshot_id]):
            raise StrongModelSegmentAnalysisError(f"baseline label mismatch for {snapshot_id}")
        rows.append(
            {
                "model_role": "baseline",
                "model_id": row["model_id"],
                "model_kind": row["model_kind"],
                "split": row["split"],
                "snapshot_id": snapshot_id,
                "score": rounded(float(row["score"])),
                "score_type": row.get("score_type", "churn_risk_probability"),
                "actual_label": actual,
                "selected_for_action": parse_selected(row["selected_at_budget"]),
                "score_rank": int(row["score_rank"]),
                "trained_on_split": row.get("trained_on_split", "train"),
            }
        )
    return rows


def candidate_prediction_rows(
    *,
    frame: pd.DataFrame,
    model: CatBoostClassifier,
    catboost_spec: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    contract = catboost_spec["feature_contract"]
    numeric_features = list(contract["numeric_features"])
    categorical_features = list(contract["categorical_features"])
    missing_category_token = contract.get("missing_category_token", "__MISSING__")
    feature_order = numeric_features + categorical_features
    matrix = prepare_features(frame, numeric_features, categorical_features, missing_category_token)
    analysis = frame.loc[frame["split"] == policy["analysis_split"]].copy()
    probabilities = model.predict(
        Pool(matrix.loc[analysis.index, feature_order], cat_features=categorical_features),
        prediction_type="Probability",
    )[:, 1]
    analysis["score"] = probabilities
    analysis = analysis.sort_values(["score", "split_order", "snapshot_id"], ascending=[False, True, True]).copy()
    analysis["score_rank"] = range(1, len(analysis) + 1)
    budget_count = int(policy["selection_policy"]["budget_count"])
    selected_ids = set(analysis.head(budget_count)["snapshot_id"].tolist())
    rows: list[dict[str, Any]] = []
    for row in analysis.to_dict("records"):
        rows.append(
            {
                "model_role": "catboost",
                "model_id": policy["early_stopping_model_id"],
                "model_kind": "catboost_classifier",
                "split": row["split"],
                "snapshot_id": row["snapshot_id"],
                "score": rounded(float(row["score"])),
                "score_type": "churn_risk_probability",
                "actual_label": int(row["target"]),
                "selected_for_action": row["snapshot_id"] in selected_ids,
                "score_rank": int(row["score_rank"]),
                "trained_on_split": "train",
            }
        )
    return rows


def confusion_label(selected: bool, actual: int) -> str:
    if selected and actual == 1:
        return "tp"
    if selected and actual == 0:
        return "fp"
    if not selected and actual == 1:
        return "fn"
    return "tn"


def build_confusion_rows(
    *,
    prediction_rows: list[dict[str, Any]],
    frame: pd.DataFrame,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    context = frame.set_index("snapshot_id").to_dict("index")
    bands = policy["score_band_policy"]["bands"]
    rows: list[dict[str, Any]] = []
    for prediction in sorted(prediction_rows, key=lambda row: (row["model_role"], row["score_rank"], row["snapshot_id"])):
        snapshot_id = prediction["snapshot_id"]
        if snapshot_id not in context:
            raise StrongModelSegmentAnalysisError(f"prediction {snapshot_id} has no feature context")
        metadata = context[snapshot_id]
        actual = int(prediction["actual_label"])
        selected = bool(prediction["selected_for_action"])
        label = confusion_label(selected, actual)
        rows.append(
            {
                "analysis_split": policy["analysis_split"],
                "model_role": prediction["model_role"],
                "model_id": prediction["model_id"],
                "model_kind": prediction["model_kind"],
                "split": prediction["split"],
                "snapshot_id": snapshot_id,
                "user_id": metadata["user_id"],
                "prediction_time": metadata["prediction_time"],
                "segment_id": metadata["segment_id"],
                "platform": metadata["platform"],
                "country": metadata["country"],
                "plan_id": metadata["plan_id"],
                "acquisition_channel": metadata["acquisition_channel"],
                "business_cohort": metadata["business_cohort"],
                "score_band": score_band(float(prediction["score"]), bands),
                "score": prediction["score"],
                "score_type": prediction["score_type"],
                "score_rank": prediction["score_rank"],
                "actual_label": actual,
                "selected_for_action": selected,
                "confusion_label": label,
                "is_error": label in {"fp", "fn"},
                "false_positive": label == "fp",
                "false_negative": label == "fn",
            }
        )
    return rows


def metric_dimensions(policy: dict[str, Any]) -> list[str]:
    return [
        "overall",
        *policy["slice_policy"]["required_dimensions"],
        *policy["slice_policy"]["business_dimensions"],
        *policy["slice_policy"]["derived_dimensions"],
    ]


def build_slice_metric_rows(
    *,
    confusion_rows: list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    dimensions = metric_dimensions(policy)
    min_rows = int(policy["small_n_policy"]["min_rows_per_slice"])
    min_positive_count = int(policy["small_n_policy"]["min_positive_count_for_recall_claim"])
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in confusion_rows:
        model_key = (row["model_role"], row["model_id"])
        grouped[(*model_key, "overall", "all")].append(row)
        for dimension in dimensions:
            if dimension == "overall":
                continue
            grouped[(*model_key, dimension, str(row[dimension]))].append(row)

    model_order = {"baseline": 0, "catboost": 1}
    rows: list[dict[str, Any]] = []
    for (model_role, model_id, dimension, value), members in sorted(
        grouped.items(),
        key=lambda item: (model_order.get(item[0][0], 99), dimensions.index(item[0][2]), item[0][3]),
    ):
        row_count = len(members)
        tp = sum(1 for row in members if row["confusion_label"] == "tp")
        fp = sum(1 for row in members if row["confusion_label"] == "fp")
        tn = sum(1 for row in members if row["confusion_label"] == "tn")
        fn = sum(1 for row in members if row["confusion_label"] == "fn")
        positive_count = tp + fn
        negative_count = tn + fp
        action_count = tp + fp
        precision = safe_rate(tp, action_count)
        recall = safe_rate(tp, positive_count)
        error_rate = safe_rate(fp + fn, row_count)
        small_n_warning = dimension != "overall" and row_count < min_rows
        rows.append(
            {
                "model_role": model_role,
                "model_id": model_id,
                "dimension": dimension,
                "slice_value": value,
                "row_count": row_count,
                "positive_count": positive_count,
                "negative_count": negative_count,
                "action_count": action_count,
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "false_positive_rate": safe_rate(fp, negative_count),
                "false_negative_rate": safe_rate(fn, positive_count),
                "error_rate": error_rate,
                "selection_rate": safe_rate(action_count, row_count),
                "brier_score": rounded(
                    sum((float(row["score"]) - float(row["actual_label"])) ** 2 for row in members) / row_count
                ),
                "selected_ids": ",".join(row["snapshot_id"] for row in members if row["selected_for_action"]),
                "false_positive_ids": ",".join(row["snapshot_id"] for row in members if row["false_positive"]),
                "false_negative_ids": ",".join(row["snapshot_id"] for row in members if row["false_negative"]),
                "small_n_warning": small_n_warning,
                "recall_claim_allowed": positive_count >= min_positive_count and row_count >= min_rows,
                "interpretation": "overall_reference"
                if dimension == "overall"
                else "diagnostic_only_small_n"
                if small_n_warning
                else "slice_diagnostic",
            }
        )
    return rows


def split_ids(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part for part in str(value).split(",") if part}


def numeric_delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return rounded(candidate - baseline)


def build_delta_rows(
    *,
    slice_metric_rows: list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    metrics_by_key = {
        (row["model_role"], row["dimension"], row["slice_value"]): row for row in slice_metric_rows
    }
    keys = sorted(
        {(row["dimension"], row["slice_value"]) for row in slice_metric_rows},
        key=lambda item: (metric_dimensions(policy).index(item[0]), item[1]),
    )
    delta_policy = policy["delta_policy"]
    max_error_delta = float(delta_policy["worse_if_error_rate_delta_above"])
    max_precision_delta = float(delta_policy["worse_if_precision_delta_below"])
    max_recall_delta = float(delta_policy["worse_if_recall_delta_below"])
    critical_dimensions = set(delta_policy["critical_dimensions"])
    min_hidden_rows = int(delta_policy["hidden_failure_min_rows"])
    rows: list[dict[str, Any]] = []
    for dimension, slice_value in keys:
        baseline = metrics_by_key.get(("baseline", dimension, slice_value))
        candidate = metrics_by_key.get(("catboost", dimension, slice_value))
        if baseline is None or candidate is None:
            raise StrongModelSegmentAnalysisError(f"missing baseline/candidate metrics for {dimension}={slice_value}")
        precision_delta = numeric_delta(candidate["precision"], baseline["precision"])
        recall_delta = numeric_delta(candidate["recall"], baseline["recall"])
        error_rate_delta = numeric_delta(candidate["error_rate"], baseline["error_rate"])
        reasons: list[str] = []
        if error_rate_delta is not None and error_rate_delta > max_error_delta:
            reasons.append("error_rate_worse")
        if precision_delta is not None and precision_delta < max_precision_delta:
            reasons.append("precision_worse")
        if recall_delta is not None and recall_delta < max_recall_delta:
            reasons.append("recall_worse")
        new_fp = sorted(split_ids(candidate["false_positive_ids"]) - split_ids(baseline["false_positive_ids"]))
        new_fn = sorted(split_ids(candidate["false_negative_ids"]) - split_ids(baseline["false_negative_ids"]))
        if new_fp:
            reasons.append("new_false_positive_ids:" + ",".join(new_fp))
        if new_fn:
            reasons.append("new_false_negative_ids:" + ",".join(new_fn))
        candidate_worse = bool(reasons)
        hidden_failure_candidate = (
            dimension != "overall"
            and dimension in critical_dimensions
            and candidate_worse
            and max(candidate["row_count"], baseline["row_count"]) >= min_hidden_rows
        )
        rows.append(
            {
                "dimension": dimension,
                "slice_value": slice_value,
                "baseline_row_count": baseline["row_count"],
                "candidate_row_count": candidate["row_count"],
                "row_count_delta": candidate["row_count"] - baseline["row_count"],
                "baseline_positive_count": baseline["positive_count"],
                "candidate_positive_count": candidate["positive_count"],
                "baseline_action_count": baseline["action_count"],
                "candidate_action_count": candidate["action_count"],
                "action_count_delta": candidate["action_count"] - baseline["action_count"],
                "baseline_precision": baseline["precision"],
                "candidate_precision": candidate["precision"],
                "precision_delta": precision_delta,
                "baseline_recall": baseline["recall"],
                "candidate_recall": candidate["recall"],
                "recall_delta": recall_delta,
                "baseline_error_rate": baseline["error_rate"],
                "candidate_error_rate": candidate["error_rate"],
                "error_rate_delta": error_rate_delta,
                "baseline_selected_ids": baseline["selected_ids"],
                "candidate_selected_ids": candidate["selected_ids"],
                "baseline_false_positive_ids": baseline["false_positive_ids"],
                "candidate_false_positive_ids": candidate["false_positive_ids"],
                "baseline_false_negative_ids": baseline["false_negative_ids"],
                "candidate_false_negative_ids": candidate["false_negative_ids"],
                "small_n_warning": bool(baseline["small_n_warning"] or candidate["small_n_warning"]),
                "candidate_worse_than_baseline": candidate_worse,
                "hidden_failure_candidate": hidden_failure_candidate,
                "hidden_failure_reasons": ",".join(reasons),
                "interpretation": "overall_delta"
                if dimension == "overall"
                else "hidden_failure_candidate"
                if hidden_failure_candidate
                else "diagnostic_delta",
            }
        )
    return rows


def build_score_band_shift_rows(confusion_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_snapshot: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in confusion_rows:
        by_snapshot[row["snapshot_id"]][row["model_role"]] = row
    rows: list[dict[str, Any]] = []
    for snapshot_id, roles in sorted(by_snapshot.items()):
        baseline = roles.get("baseline")
        candidate = roles.get("catboost")
        if baseline is None or candidate is None:
            continue
        if baseline["score_band"] != candidate["score_band"]:
            rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "actual_label": baseline["actual_label"],
                    "baseline_score": baseline["score"],
                    "candidate_score": candidate["score"],
                    "baseline_score_band": baseline["score_band"],
                    "candidate_score_band": candidate["score_band"],
                    "baseline_selected_for_action": baseline["selected_for_action"],
                    "candidate_selected_for_action": candidate["selected_for_action"],
                    "interpretation": "score_band_membership_changed_between_models",
                }
            )
    return rows


def build_audit_rows(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "check_id": check["id"],
            "severity": check["severity"],
            "valid": check["valid"],
            "observed": json.dumps(json_ready(check["observed"]), ensure_ascii=False),
            "expected": json.dumps(json_ready(check["expected"]), ensure_ascii=False),
        }
        for check in checks
    ]


def build_checks_after_outputs(
    *,
    policy: dict[str, Any],
    confusion_rows: list[dict[str, Any]],
    slice_metric_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    small_n_rows: list[dict[str, Any]],
    hidden_failure_rows: list[dict[str, Any]],
    score_band_shift_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    splits = sorted({row["split"] for row in confusion_rows})
    if splits == [policy["analysis_split"]] and policy["final_holdout_split"] not in splits:
        checks.append(
            passed(
                "segment_analysis_uses_validation_and_excludes_final_test",
                {"splits": splits, "final_holdout_rows": 0},
                "validation split only; final test excluded",
            )
        )
    else:
        checks.append(
            failed(
                "segment_analysis_uses_validation_and_excludes_final_test",
                {"splits": splits},
                [policy["analysis_split"]],
            )
        )
    ids_by_model: dict[str, set[str]] = defaultdict(set)
    for row in confusion_rows:
        ids_by_model[row["model_role"]].add(row["snapshot_id"])
    if ids_by_model.get("baseline") == ids_by_model.get("catboost") and ids_by_model.get("baseline"):
        checks.append(
            passed(
                "prediction_rows_cover_same_analysis_ids",
                {
                    "baseline_ids": sorted(ids_by_model["baseline"]),
                    "catboost_ids": sorted(ids_by_model["catboost"]),
                },
                "both models scored the same validation rows",
            )
        )
    else:
        checks.append(
            failed(
                "prediction_rows_cover_same_analysis_ids",
                {role: sorted(ids) for role, ids in ids_by_model.items()},
                "same analysis ids for both models",
            )
        )
    expected_dimensions = set(metric_dimensions(policy))
    observed_dimensions = {row["dimension"] for row in slice_metric_rows}
    if expected_dimensions.issubset(observed_dimensions):
        checks.append(
            passed(
                "slice_metrics_cover_required_dimensions",
                {"dimensions": sorted(observed_dimensions), "row_count": len(slice_metric_rows)},
                "overall, required, business and derived dimensions",
            )
        )
    else:
        checks.append(failed("slice_metrics_cover_required_dimensions", sorted(observed_dimensions), sorted(expected_dimensions)))
    if len(delta_rows) == len({(row["dimension"], row["slice_value"]) for row in slice_metric_rows}):
        checks.append(
            passed(
                "baseline_delta_rows_are_complete",
                {"delta_row_count": len(delta_rows)},
                "one baseline-to-CatBoost delta per slice",
            )
        )
    else:
        checks.append(
            failed(
                "baseline_delta_rows_are_complete",
                {"delta_row_count": len(delta_rows), "slice_metric_rows": len(slice_metric_rows)},
                "one delta per slice",
            )
        )
    if small_n_rows:
        checks.append(
            failed(
                "strong_model_small_n_slices_visible",
                {
                    "small_n_slice_count": len(small_n_rows),
                    "min_rows_per_slice": policy["small_n_policy"]["min_rows_per_slice"],
                },
                "small slices remain visible and diagnostic-only",
                severity="warning",
            )
        )
    else:
        checks.append(passed("strong_model_small_n_slices_visible", {"small_n_slice_count": 0}))
    if hidden_failure_rows:
        checks.append(
            failed(
                "strong_model_hidden_failure_slices_visible",
                [
                    {
                        "dimension": row["dimension"],
                        "slice_value": row["slice_value"],
                        "reasons": row["hidden_failure_reasons"],
                    }
                    for row in hidden_failure_rows
                ],
                "candidate-worse slices should be reported, not hidden by averages",
                severity="warning",
            )
        )
    else:
        checks.append(passed("strong_model_hidden_failure_slices_visible", {"hidden_failure_slice_count": 0}))
    overall_delta = next(row for row in delta_rows if row["dimension"] == "overall")
    if overall_delta["candidate_worse_than_baseline"]:
        checks.append(
            failed(
                "candidate_worse_than_baseline_on_validation",
                {
                    "baseline_precision": overall_delta["baseline_precision"],
                    "candidate_precision": overall_delta["candidate_precision"],
                    "baseline_recall": overall_delta["baseline_recall"],
                    "candidate_recall": overall_delta["candidate_recall"],
                    "error_rate_delta": overall_delta["error_rate_delta"],
                },
                "CatBoost must not be promoted on aggregate validation metrics",
                severity="warning",
            )
        )
    else:
        checks.append(passed("candidate_worse_than_baseline_on_validation", {"candidate_worse": False}))
    if score_band_shift_rows:
        checks.append(
            failed(
                "score_band_membership_differs_between_models",
                {"shift_count": len(score_band_shift_rows), "snapshot_ids": [row["snapshot_id"] for row in score_band_shift_rows]},
                "score-band slices are model-specific and must be interpreted as such",
                severity="warning",
            )
        )
    else:
        checks.append(passed("score_band_membership_differs_between_models", {"shift_count": 0}))
    if overall_delta["candidate_worse_than_baseline"] or hidden_failure_rows:
        checks.append(
            failed(
                "candidate_not_promoted_without_segment_gain",
                {
                    "overall_candidate_worse": overall_delta["candidate_worse_than_baseline"],
                    "hidden_failure_slice_count": len(hidden_failure_rows),
                },
                "strong model is diagnostic only until cost-sensitive decision confirms a gain",
                severity="warning",
            )
        )
    else:
        checks.append(passed("candidate_not_promoted_without_segment_gain", {"promotable": True}))
    return checks


def run(
    *,
    policy_path: Path = DEFAULT_POLICY_PATH,
    catboost_spec_path: Path = DEFAULT_CATBOOST_SPEC_PATH,
    early_stopping_report_path: Path = DEFAULT_EARLY_STOPPING_REPORT_PATH,
    early_stopping_spec_path: Path = DEFAULT_EARLY_STOPPING_SPEC_PATH,
    shap_report_path: Path = DEFAULT_SHAP_REPORT_PATH,
    shap_spec_path: Path = DEFAULT_SHAP_SPEC_PATH,
    baseline_package_report_path: Path = DEFAULT_BASELINE_PACKAGE_REPORT_PATH,
    imbalance_predictions_path: Path = DEFAULT_IMBALANCE_PREDICTIONS_PATH,
    features_path: Path = DEFAULT_FEATURES_PATH,
    labels_path: Path = DEFAULT_LABELS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    required_paths = {
        "policy": policy_path,
        "catboost_spec": catboost_spec_path,
        "early_stopping_report": early_stopping_report_path,
        "early_stopping_spec": early_stopping_spec_path,
        "shap_report": shap_report_path,
        "shap_spec": shap_spec_path,
        "baseline_package_report": baseline_package_report_path,
        "imbalance_predictions": imbalance_predictions_path,
        "features": features_path,
        "labels": labels_path,
        "manifest": manifest_path,
    }
    checks = [validate_required_files(required_paths)]
    if blocking_errors(checks):
        return {
            "valid": False,
            "summary": {
                "segment_analysis_audit_id": None,
                "blocking_errors": blocking_errors(checks),
                "warnings": warning_ids(checks),
                "readiness_status": "blocked_before_segment_analysis",
            },
            "checks": checks,
        }

    policy = read_json(policy_path)
    catboost_spec = read_json(catboost_spec_path)
    early_report = read_json(early_stopping_report_path)
    early_spec = read_json(early_stopping_spec_path)
    shap_report = read_json(shap_report_path)
    shap_spec = read_json(shap_spec_path)
    baseline_package_report = read_json(baseline_package_report_path)

    checks.extend(
        validate_policy(
            policy=policy,
            catboost_spec=catboost_spec,
            early_report=early_report,
            early_spec=early_spec,
            shap_report=shap_report,
            shap_spec=shap_spec,
            baseline_package_report=baseline_package_report,
        )
    )
    if blocking_errors(checks):
        return {
            "valid": False,
            "problem_id": policy.get("problem_id"),
            "summary": {
                "segment_analysis_audit_id": policy.get("segment_analysis_audit_id"),
                "blocking_errors": blocking_errors(checks),
                "warnings": warning_ids(checks),
                "readiness_status": "blocked_before_segment_analysis",
            },
            "checks": checks,
        }

    frame = joined_frame(features_path, labels_path, manifest_path)
    model = train_early_stopped_catboost(frame=frame, catboost_spec=catboost_spec, early_spec=early_spec)
    baseline_rows = baseline_prediction_rows(
        imbalance_predictions_path=imbalance_predictions_path,
        frame=frame,
        policy=policy,
    )
    candidate_rows = candidate_prediction_rows(
        frame=frame,
        model=model,
        catboost_spec=catboost_spec,
        policy=policy,
    )
    prediction_rows = baseline_rows + candidate_rows
    confusion_rows = build_confusion_rows(prediction_rows=prediction_rows, frame=frame, policy=policy)
    slice_metric_rows = build_slice_metric_rows(confusion_rows=confusion_rows, policy=policy)
    delta_rows = build_delta_rows(slice_metric_rows=slice_metric_rows, policy=policy)
    small_n_rows = [row for row in slice_metric_rows if row["small_n_warning"]]
    hidden_failure_rows = [row for row in delta_rows if row["hidden_failure_candidate"]]
    score_band_shift_rows = build_score_band_shift_rows(confusion_rows)
    checks.extend(
        build_checks_after_outputs(
            policy=policy,
            confusion_rows=confusion_rows,
            slice_metric_rows=slice_metric_rows,
            delta_rows=delta_rows,
            small_n_rows=small_n_rows,
            hidden_failure_rows=hidden_failure_rows,
            score_band_shift_rows=score_band_shift_rows,
        )
    )
    overall_by_role = {
        row["model_role"]: row
        for row in slice_metric_rows
        if row["dimension"] == "overall" and row["slice_value"] == "all"
    }
    overall_delta = next(row for row in delta_rows if row["dimension"] == "overall")
    valid = not blocking_errors(checks)
    serialized_spec = {
        "segment_analysis_audit_id": policy["segment_analysis_audit_id"],
        "problem_id": policy["problem_id"],
        "catboost_version": catboost.__version__,
        "baseline_model_id": policy["baseline_model_id"],
        "early_stopping_model_id": policy["early_stopping_model_id"],
        "analysis_split": policy["analysis_split"],
        "final_holdout_split": policy["final_holdout_split"],
        "feature_order": expected_feature_order(catboost_spec),
        "selection_policy": policy["selection_policy"],
        "slice_policy": policy["slice_policy"],
        "score_band_policy": policy["score_band_policy"],
        "small_n_policy": policy["small_n_policy"],
        "delta_policy": policy["delta_policy"],
        "selection_summary": {
            "baseline_selected_ids": overall_by_role["baseline"]["selected_ids"].split(","),
            "catboost_selected_ids": overall_by_role["catboost"]["selected_ids"].split(","),
            "baseline_false_positive_ids": overall_by_role["baseline"]["false_positive_ids"].split(",")
            if overall_by_role["baseline"]["false_positive_ids"]
            else [],
            "catboost_false_positive_ids": overall_by_role["catboost"]["false_positive_ids"].split(",")
            if overall_by_role["catboost"]["false_positive_ids"]
            else [],
            "catboost_false_negative_ids": overall_by_role["catboost"]["false_negative_ids"].split(",")
            if overall_by_role["catboost"]["false_negative_ids"]
            else [],
        },
        "overall_delta": overall_delta,
        "warning_summary": {
            "small_n_slice_count": len(small_n_rows),
            "hidden_failure_slice_count": len(hidden_failure_rows),
            "score_band_shift_count": len(score_band_shift_rows),
        },
        "upstream_handoff": {
            "early_stopping_audit_id": early_spec["early_stopping_audit_id"],
            "shap_explanation_audit_id": shap_spec["shap_explanation_audit_id"],
            "shap_readiness_status": shap_report["summary"]["readiness_status"],
        },
        "generated_at": GENERATED_AT,
    }
    summary = {
        "segment_analysis_audit_id": policy["segment_analysis_audit_id"],
        "problem_id": policy["problem_id"],
        "catboost_version": catboost.__version__,
        "baseline_model_id": policy["baseline_model_id"],
        "early_stopping_model_id": policy["early_stopping_model_id"],
        "analysis_split": policy["analysis_split"],
        "final_holdout_split": policy["final_holdout_split"],
        "row_count_per_model": overall_by_role["baseline"]["row_count"],
        "baseline_action_count": overall_by_role["baseline"]["action_count"],
        "catboost_action_count": overall_by_role["catboost"]["action_count"],
        "baseline_precision": overall_by_role["baseline"]["precision"],
        "catboost_precision": overall_by_role["catboost"]["precision"],
        "precision_delta": overall_delta["precision_delta"],
        "baseline_recall": overall_by_role["baseline"]["recall"],
        "catboost_recall": overall_by_role["catboost"]["recall"],
        "recall_delta": overall_delta["recall_delta"],
        "baseline_error_rate": overall_by_role["baseline"]["error_rate"],
        "catboost_error_rate": overall_by_role["catboost"]["error_rate"],
        "error_rate_delta": overall_delta["error_rate_delta"],
        "baseline_selected_ids": overall_by_role["baseline"]["selected_ids"],
        "catboost_selected_ids": overall_by_role["catboost"]["selected_ids"],
        "confusion_row_count": len(confusion_rows),
        "slice_metric_row_count": len(slice_metric_rows),
        "delta_row_count": len(delta_rows),
        "small_n_slice_count": len(small_n_rows),
        "hidden_failure_slice_count": len(hidden_failure_rows),
        "score_band_shift_count": len(score_band_shift_rows),
        "blocking_errors": blocking_errors(checks),
        "warnings": warning_ids(checks),
        "readiness_status": "ready_for_cost_sensitive_decision_lesson"
        if valid
        else "blocked_by_segment_analysis",
    }
    report = {
        "valid": valid,
        "problem_id": policy["problem_id"],
        "summary": summary,
        "confusion_rows": confusion_rows,
        "slice_metrics": slice_metric_rows,
        "segment_deltas": delta_rows,
        "small_n_warnings": small_n_rows,
        "hidden_failure_slices": hidden_failure_rows,
        "score_band_shifts": score_band_shift_rows,
        "audit": build_audit_rows(checks),
        "serialized_spec": serialized_spec,
        "checks": checks,
    }
    return json_ready(report)


CONFUSION_FIELDS = [
    "analysis_split",
    "model_role",
    "model_id",
    "model_kind",
    "split",
    "snapshot_id",
    "user_id",
    "prediction_time",
    "segment_id",
    "platform",
    "country",
    "plan_id",
    "acquisition_channel",
    "business_cohort",
    "score_band",
    "score",
    "score_type",
    "score_rank",
    "actual_label",
    "selected_for_action",
    "confusion_label",
    "is_error",
    "false_positive",
    "false_negative",
]

SLICE_FIELDS = [
    "model_role",
    "model_id",
    "dimension",
    "slice_value",
    "row_count",
    "positive_count",
    "negative_count",
    "action_count",
    "tp",
    "fp",
    "tn",
    "fn",
    "precision",
    "recall",
    "false_positive_rate",
    "false_negative_rate",
    "error_rate",
    "selection_rate",
    "brier_score",
    "selected_ids",
    "false_positive_ids",
    "false_negative_ids",
    "small_n_warning",
    "recall_claim_allowed",
    "interpretation",
]

DELTA_FIELDS = [
    "dimension",
    "slice_value",
    "baseline_row_count",
    "candidate_row_count",
    "row_count_delta",
    "baseline_positive_count",
    "candidate_positive_count",
    "baseline_action_count",
    "candidate_action_count",
    "action_count_delta",
    "baseline_precision",
    "candidate_precision",
    "precision_delta",
    "baseline_recall",
    "candidate_recall",
    "recall_delta",
    "baseline_error_rate",
    "candidate_error_rate",
    "error_rate_delta",
    "baseline_selected_ids",
    "candidate_selected_ids",
    "baseline_false_positive_ids",
    "candidate_false_positive_ids",
    "baseline_false_negative_ids",
    "candidate_false_negative_ids",
    "small_n_warning",
    "candidate_worse_than_baseline",
    "hidden_failure_candidate",
    "hidden_failure_reasons",
    "interpretation",
]

SCORE_BAND_SHIFT_FIELDS = [
    "snapshot_id",
    "actual_label",
    "baseline_score",
    "candidate_score",
    "baseline_score_band",
    "candidate_score_band",
    "baseline_selected_for_action",
    "candidate_selected_for_action",
    "interpretation",
]


def write_outputs(result: dict[str, Any], output_root: Path, output_spec: dict[str, str]) -> None:
    write_json(output_root / output_spec["report_file"], result)
    write_csv(output_root / output_spec["confusion_row_file"], result["confusion_rows"], CONFUSION_FIELDS)
    write_csv(output_root / output_spec["slice_metric_file"], result["slice_metrics"], SLICE_FIELDS)
    write_csv(output_root / output_spec["delta_file"], result["segment_deltas"], DELTA_FIELDS)
    write_csv(output_root / output_spec["small_n_warning_file"], result["small_n_warnings"], SLICE_FIELDS)
    write_csv(output_root / output_spec["hidden_failure_file"], result["hidden_failure_slices"], DELTA_FIELDS)
    write_csv(output_root / output_spec["score_band_shift_file"], result["score_band_shifts"], SCORE_BAND_SHIFT_FIELDS)
    write_csv(output_root / output_spec["audit_file"], result["audit"], ["check_id", "severity", "valid", "observed", "expected"])
    write_json(output_root / output_spec["serialized_spec_file"], result["serialized_spec"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare baseline and CatBoost by validation segments")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--catboost-spec", type=Path, default=DEFAULT_CATBOOST_SPEC_PATH)
    parser.add_argument("--early-stopping-report", type=Path, default=DEFAULT_EARLY_STOPPING_REPORT_PATH)
    parser.add_argument("--early-stopping-spec", type=Path, default=DEFAULT_EARLY_STOPPING_SPEC_PATH)
    parser.add_argument("--shap-report", type=Path, default=DEFAULT_SHAP_REPORT_PATH)
    parser.add_argument("--shap-spec", type=Path, default=DEFAULT_SHAP_SPEC_PATH)
    parser.add_argument("--baseline-package-report", type=Path, default=DEFAULT_BASELINE_PACKAGE_REPORT_PATH)
    parser.add_argument("--imbalance-predictions", type=Path, default=DEFAULT_IMBALANCE_PREDICTIONS_PATH)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES_PATH)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = run(
            policy_path=args.policy,
            catboost_spec_path=args.catboost_spec,
            early_stopping_report_path=args.early_stopping_report,
            early_stopping_spec_path=args.early_stopping_spec,
            shap_report_path=args.shap_report,
            shap_spec_path=args.shap_spec,
            baseline_package_report_path=args.baseline_package_report,
            imbalance_predictions_path=args.imbalance_predictions,
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
        )
        if args.output_root is not None:
            write_outputs(result, args.output_root, read_json(args.policy)["output"])
        else:
            print(json.dumps(json_ready(result), ensure_ascii=False, indent=2))
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        StrongModelSegmentAnalysisError,
    ) as error:
        result = {
            "valid": False,
            "summary": {
                "blocking_errors": ["strong_model_segment_analysis_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "strong_model_segment_analysis_runtime_error",
                    str(error),
                    "readable inputs and valid strong-model segment policy",
                )
            ],
        }
        if args.output_root is not None:
            write_json(args.output_root / "strong_model_segment_report.json", result)
        else:
            print(json.dumps(json_ready(result), ensure_ascii=False, indent=2))

    has_errors = any(check["severity"] == "error" and not check["valid"] for check in result["checks"])
    has_warnings = any(check["severity"] == "warning" and not check["valid"] for check in result["checks"])
    if has_errors or (args.fail_on_warning and has_warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
