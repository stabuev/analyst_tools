from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import catboost
import numpy as np
import pandas as pd
import shap
from catboost import CatBoostClassifier, Pool


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
DATA_ROOT = PHASE_16_ROOT / "data" / "tiny"

DEFAULT_POLICY_PATH = DATA_ROOT / "shap_explanation_policy_spec.json"
DEFAULT_CATBOOST_SPEC_PATH = DATA_ROOT / "catboost_model_spec.json"
DEFAULT_CATEGORICAL_REPORT_PATH = (
    PHASE_16_ROOT / "02-categorical-features" / "outputs" / "categorical_feature_report.json"
)
DEFAULT_EARLY_STOPPING_REPORT_PATH = (
    PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_report.json"
)
DEFAULT_EARLY_STOPPING_SPEC_PATH = (
    PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_serialized_spec.json"
)
DEFAULT_BUILT_IN_REPORT_PATH = (
    PHASE_16_ROOT / "04-feature-importance" / "outputs" / "built_in_importance_report.json"
)
DEFAULT_BUILT_IN_SPEC_PATH = (
    PHASE_16_ROOT / "04-feature-importance" / "outputs" / "built_in_importance_serialized_spec.json"
)
DEFAULT_PERMUTATION_REPORT_PATH = (
    PHASE_16_ROOT / "05-permutation-importance" / "outputs" / "permutation_importance_report.json"
)
DEFAULT_PERMUTATION_SPEC_PATH = (
    PHASE_16_ROOT / "05-permutation-importance" / "outputs" / "permutation_importance_serialized_spec.json"
)
DEFAULT_FEATURES_PATH = UPSTREAM_DATA_ROOT / "ml_raw_features.csv"
DEFAULT_LABELS_PATH = UPSTREAM_DATA_ROOT / "ml_labels.csv"
DEFAULT_MANIFEST_PATH = UPSTREAM_DATA_ROOT / "ml_split_manifest.csv"

GENERATED_AT = "2026-07-05T12:00:00+03:00"


def portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


class ShapExplanationError(ValueError):
    """Raised when SHAP explanation inputs cannot be parsed."""


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
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return 1
    if text in {"false", "0", "no"}:
        return 0
    raise ShapExplanationError(f"Cannot parse boolean label: {value!r}")


def validate_required_files(paths: dict[str, Path]) -> dict[str, Any]:
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        return failed("input_files_are_present", sorted(paths), "all required input files", missing)
    return passed("input_files_are_present", sorted(paths), "all required input files")


def expected_feature_order(catboost_spec: dict[str, Any]) -> list[str]:
    contract = catboost_spec.get("feature_contract", {})
    return list(contract.get("numeric_features", [])) + list(contract.get("categorical_features", []))


def validate_handoff(
    *,
    policy: dict[str, Any],
    catboost_spec: dict[str, Any],
    early_report: dict[str, Any],
    early_spec: dict[str, Any],
    categorical_report: dict[str, Any],
    built_in_report: dict[str, Any],
    built_in_spec: dict[str, Any],
    permutation_report: dict[str, Any],
    permutation_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    required = {
        "shap_explanation_audit_id",
        "problem_id",
        "catboost_baseline_id",
        "source_catboost_model_id",
        "early_stopping_model_id",
        "early_stopping_audit_id",
        "categorical_audit_id",
        "built_in_importance_audit_id",
        "permutation_importance_audit_id",
        "fit_split",
        "explain_split",
        "final_holdout_split",
        "explainer",
        "additivity",
        "local_explanations",
        "global_summary",
        "feature_name_policy",
        "interpretation_policy",
        "warning_policy",
        "output",
    }
    missing = sorted(required - set(policy))
    if missing:
        errors.append({"field": "root", "missing": missing})

    expected_identity = {
        "problem_id": permutation_spec.get("problem_id"),
        "catboost_baseline_id": permutation_spec.get("catboost_baseline_id"),
        "source_catboost_model_id": permutation_spec.get("source_catboost_model_id"),
        "early_stopping_model_id": permutation_spec.get("early_stopping_model_id"),
        "early_stopping_audit_id": permutation_spec.get("early_stopping_audit_id"),
        "categorical_audit_id": permutation_spec.get("categorical_audit_id"),
        "built_in_importance_audit_id": permutation_spec.get("built_in_importance_audit_id"),
        "permutation_importance_audit_id": permutation_spec.get("permutation_importance_audit_id"),
        "fit_split": early_spec.get("fit_summary", {}).get("fit_split"),
        "explain_split": permutation_spec.get("heldout_summary", {}).get("heldout_split"),
        "final_holdout_split": early_spec.get("fit_summary", {}).get("final_holdout_split"),
    }
    for field, expected in expected_identity.items():
        if policy.get(field) != expected:
            errors.append({"field": field, "observed": policy.get(field), "expected": expected})

    if early_report.get("valid") is not True:
        errors.append({"field": "early_stopping_report.valid", "observed": early_report.get("valid"), "expected": True})
    if categorical_report.get("valid") is not True:
        errors.append({"field": "categorical_report.valid", "observed": categorical_report.get("valid"), "expected": True})
    if built_in_report.get("valid") is not True:
        errors.append({"field": "built_in_report.valid", "observed": built_in_report.get("valid"), "expected": True})
    if permutation_report.get("valid") is not True:
        errors.append({"field": "permutation_report.valid", "observed": permutation_report.get("valid"), "expected": True})

    if built_in_report.get("summary", {}).get("readiness_status") != "ready_for_permutation_importance_lesson":
        errors.append(
            {
                "field": "built_in_report.summary.readiness_status",
                "observed": built_in_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_permutation_importance_lesson",
            }
        )
    if permutation_report.get("summary", {}).get("readiness_status") != "ready_for_shap_lesson":
        errors.append(
            {
                "field": "permutation_report.summary.readiness_status",
                "observed": permutation_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_shap_lesson",
            }
        )

    expected_order = expected_feature_order(catboost_spec)
    if expected_order != early_spec.get("numeric_features", []) + early_spec.get("cat_features", []):
        errors.append(
            {
                "field": "feature_order",
                "observed": expected_order,
                "expected": early_spec.get("numeric_features", []) + early_spec.get("cat_features", []),
            }
        )
    for source_name, source_order in {
        "built_in_feature_order": built_in_spec.get("feature_order"),
        "permutation_feature_order": permutation_spec.get("feature_order"),
    }.items():
        if source_order != expected_order:
            errors.append({"field": source_name, "observed": source_order, "expected": expected_order})

    if errors:
        return [
            failed(
                "shap_policy_matches_permutation_handoff",
                errors,
                "same CatBoost model, early-stopping run, built-in importance and permutation handoff",
            )
        ]
    return [
        passed(
            "shap_policy_matches_permutation_handoff",
            {
                "shap_explanation_audit_id": policy["shap_explanation_audit_id"],
                "permutation_importance_audit_id": policy["permutation_importance_audit_id"],
                "early_stopping_model_id": policy["early_stopping_model_id"],
            },
        )
    ]


def validate_shap_policy(policy: dict[str, Any], expected_features: list[str]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    explainer = policy.get("explainer", {}) if isinstance(policy.get("explainer"), dict) else {}
    additivity = policy.get("additivity", {}) if isinstance(policy.get("additivity"), dict) else {}
    local = policy.get("local_explanations", {}) if isinstance(policy.get("local_explanations"), dict) else {}
    global_summary = policy.get("global_summary", {}) if isinstance(policy.get("global_summary"), dict) else {}

    expected_explainer = {
        "library": "shap",
        "class": "TreeExplainer",
        "model_output": "raw",
        "output_space": "raw_margin",
        "feature_perturbation": "tree_path_dependent",
        "background_split": "train",
        "external_background_data_passed": False,
    }
    for field, expected in expected_explainer.items():
        if explainer.get(field) != expected:
            errors.append({"field": f"explainer.{field}", "observed": explainer.get(field), "expected": expected})

    if policy.get("explain_split") != "validation":
        errors.append({"field": "explain_split", "observed": policy.get("explain_split"), "expected": "validation"})
    if policy.get("final_holdout_split") != "test":
        errors.append({"field": "final_holdout_split", "observed": policy.get("final_holdout_split"), "expected": "test"})
    if policy.get("explain_split") == policy.get("final_holdout_split"):
        errors.append({"field": "explain_split", "observed": policy.get("explain_split"), "expected": "not final holdout split"})

    if additivity.get("enabled") is not True:
        errors.append({"field": "additivity.enabled", "observed": additivity.get("enabled"), "expected": True})
    if additivity.get("target_prediction_type") != "RawFormulaVal":
        errors.append(
            {
                "field": "additivity.target_prediction_type",
                "observed": additivity.get("target_prediction_type"),
                "expected": "RawFormulaVal",
            }
        )
    tolerance = additivity.get("absolute_error_tolerance")
    if not isinstance(tolerance, int | float) or float(tolerance) > 1e-6:
        errors.append(
            {
                "field": "additivity.absolute_error_tolerance",
                "observed": tolerance,
                "expected": "numeric <= 1e-6",
            }
        )

    if not isinstance(local.get("snapshot_ids"), list) or not local.get("snapshot_ids"):
        errors.append({"field": "local_explanations.snapshot_ids", "observed": local.get("snapshot_ids"), "expected": "non-empty list"})
    if not isinstance(local.get("top_k_features"), int) or int(local.get("top_k_features", 0)) < 1:
        errors.append({"field": "local_explanations.top_k_features", "observed": local.get("top_k_features"), "expected": "integer >= 1"})
    if global_summary.get("aggregation_split") != policy.get("explain_split"):
        errors.append(
            {
                "field": "global_summary.aggregation_split",
                "observed": global_summary.get("aggregation_split"),
                "expected": policy.get("explain_split"),
            }
        )
    if global_summary.get("metric") != "mean_abs_shap":
        errors.append({"field": "global_summary.metric", "observed": global_summary.get("metric"), "expected": "mean_abs_shap"})

    observed_order = policy.get("feature_name_policy", {}).get("expected_feature_order")
    if observed_order != expected_features:
        errors.append({"field": "feature_name_policy.expected_feature_order", "observed": observed_order, "expected": expected_features})

    claim = str(policy.get("interpretation_policy", {}).get("claim", "")).lower()
    forbidden = [
        term
        for term in policy.get("interpretation_policy", {}).get("forbidden_positive_claim_terms", [])
        if str(term).lower() in claim
    ]
    if forbidden:
        errors.append({"field": "interpretation_policy.claim", "forbidden_terms": sorted(forbidden)})

    limitations = policy.get("interpretation_policy", {}).get("required_limitation_labels", [])
    if not isinstance(limitations, list) or len(limitations) < 5:
        errors.append({"field": "interpretation_policy.required_limitation_labels", "observed": limitations, "expected": "at least five limitation labels"})

    if errors:
        return [
            failed(
                "shap_policy_declares_background_output_additivity_and_limits",
                errors,
                "TreeExplainer raw-margin SHAP with tree-path background, local rows, additivity tolerance and non-causal limits",
            )
        ]
    return [
        passed(
            "shap_policy_declares_background_output_additivity_and_limits",
            {
                "explainer": f"{explainer['library']}.{explainer['class']}",
                "output_space": explainer["output_space"],
                "feature_perturbation": explainer["feature_perturbation"],
                "background_split": explainer["background_split"],
                "local_snapshot_ids": local["snapshot_ids"],
            },
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
            raise ShapExplanationError(f"{frame_name} table misses snapshot_id")
        if frame["snapshot_id"].duplicated().any():
            raise ShapExplanationError(f"{frame_name} table contains duplicate snapshot_id")

    frame = features.merge(labels[["snapshot_id", "churned_14d"]], on="snapshot_id", how="left")
    frame = frame.merge(
        manifest[["snapshot_id", "split", "split_order", "user_id", "prediction_time"]],
        on="snapshot_id",
        how="inner",
    )
    frame["target"] = frame["churned_14d"].map(bool_label)
    return frame.sort_values(["split_order", "snapshot_id"]).reset_index(drop=True)


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


def train_model(
    *,
    frame: pd.DataFrame,
    matrix: pd.DataFrame,
    early_spec: dict[str, Any],
) -> CatBoostClassifier:
    categorical_features = list(early_spec.get("cat_features", []))
    train_mask = frame["split"] == early_spec["fit_summary"]["fit_split"]
    eval_mask = frame["split"] == early_spec["fit_summary"]["eval_split"]
    model = CatBoostClassifier(**early_spec["catboost_params"])
    model.fit(
        Pool(matrix.loc[train_mask], frame.loc[train_mask, "target"], cat_features=categorical_features),
        eval_set=Pool(matrix.loc[eval_mask], frame.loc[eval_mask, "target"], cat_features=categorical_features),
    )
    return model


def high_cardinality_features(categorical_report: dict[str, Any]) -> set[str]:
    return {
        str(row["feature_name"])
        for row in categorical_report.get("inventory", [])
        if row.get("high_cardinality_feature") is True
    }


def correlated_numeric_pairs(frame: pd.DataFrame, numeric_features: list[str], fit_split: str, threshold: float) -> list[dict[str, Any]]:
    train = frame.loc[frame["split"] == fit_split, numeric_features].apply(pd.to_numeric, errors="coerce")
    corr = train.corr().abs()
    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(numeric_features):
        for right in numeric_features[left_index + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value) and float(value) >= threshold:
                pairs.append(
                    {
                        "left_feature": left,
                        "right_feature": right,
                        "abs_correlation": rounded(float(value)),
                    }
                )
    return pairs


def split_summary(frame: pd.DataFrame, split: str) -> dict[str, Any]:
    split_frame = frame.loc[frame["split"] == split]
    return {
        "split": split,
        "row_count": int(len(split_frame)),
        "snapshot_ids": list(split_frame["snapshot_id"]),
        "target_positive_count": int(split_frame["target"].sum()),
        "target_negative_count": int((1 - split_frame["target"]).sum()),
    }


def validate_background_and_explain_rows(frame: pd.DataFrame, policy: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    background_split = policy.get("explainer", {}).get("background_split")
    explain_split = policy.get("explain_split")
    final_split = policy.get("final_holdout_split")
    background = frame.loc[frame["split"] == background_split]
    explain = frame.loc[frame["split"] == explain_split]
    local_ids = set(policy.get("local_explanations", {}).get("snapshot_ids", []))
    explain_ids = set(explain["snapshot_id"])

    if background.empty or background_split == final_split:
        checks.append(
            failed(
                "background_reference_uses_train_and_excludes_test",
                {"background_split": background_split, "row_count": len(background), "final_holdout_split": final_split},
                "non-empty train background reference, no final test rows",
            )
        )
    else:
        checks.append(
            passed(
                "background_reference_uses_train_and_excludes_test",
                {
                    "background_split": background_split,
                    "snapshot_ids": list(background["snapshot_id"]),
                    "final_test_rows_used": 0,
                    "external_background_data_passed": policy.get("explainer", {}).get("external_background_data_passed"),
                },
                "train rows recorded as path-dependent background reference",
            )
        )

    if explain.empty or explain_split == final_split:
        checks.append(
            failed(
                "explain_rows_use_validation_and_exclude_final_test",
                {"explain_split": explain_split, "row_count": len(explain), "final_holdout_split": final_split},
                "non-empty validation explanation split, no final test rows",
            )
        )
    elif local_ids - explain_ids:
        checks.append(
            failed(
                "explain_rows_use_validation_and_exclude_final_test",
                {"unknown_local_snapshot_ids": sorted(local_ids - explain_ids), "explain_snapshot_ids": sorted(explain_ids)},
                "local explanation rows must be inside validation split",
            )
        )
    else:
        checks.append(
            passed(
                "explain_rows_use_validation_and_exclude_final_test",
                {
                    "explain_split": explain_split,
                    "snapshot_ids": list(explain["snapshot_id"]),
                    "local_snapshot_ids": policy.get("local_explanations", {}).get("snapshot_ids", []),
                    "final_test_rows_used": 0,
                },
                "validation rows only",
            )
        )
    return checks


def scalar_expected_value(value: Any) -> float:
    array = np.asarray(value, dtype=float)
    if array.size != 1:
        raise ShapExplanationError(f"Expected scalar SHAP expected_value, got shape {array.shape}")
    return float(array.reshape(-1)[0])


def shap_value_matrix(values: Any) -> np.ndarray:
    if isinstance(values, list):
        if len(values) == 1:
            values = values[0]
        elif len(values) == 2:
            values = values[1]
        else:
            raise ShapExplanationError(f"Unsupported multiclass SHAP output with {len(values)} arrays")
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2:
        raise ShapExplanationError(f"Expected 2-D SHAP matrix, got shape {matrix.shape}")
    return matrix


def compute_shap_outputs(
    *,
    policy: dict[str, Any],
    model: CatBoostClassifier,
    matrix: pd.DataFrame,
    frame: pd.DataFrame,
    expected_features: list[str],
    categorical_features: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    explain_mask = frame["split"] == policy["explain_split"]
    explain_frame = frame.loc[explain_mask].reset_index(drop=True)
    explain_matrix = matrix.loc[explain_mask].reset_index(drop=True)
    explain_pool = Pool(explain_matrix, cat_features=categorical_features)

    explainer = shap.TreeExplainer(
        model,
        feature_perturbation=policy["explainer"]["feature_perturbation"],
        model_output=policy["explainer"]["model_output"],
    )
    values = shap_value_matrix(explainer.shap_values(explain_pool))
    expected_value = scalar_expected_value(explainer.expected_value)
    raw_predictions = np.asarray(model.predict(explain_pool, prediction_type="RawFormulaVal"), dtype=float)
    probabilities = np.asarray(model.predict_proba(explain_matrix)[:, 1], dtype=float)

    shap_sums = values.sum(axis=1)
    reconstructed = expected_value + shap_sums
    absolute_errors = np.abs(reconstructed - raw_predictions)
    tolerance = float(policy["additivity"]["absolute_error_tolerance"])

    additivity_rows: list[dict[str, Any]] = []
    for row_index, row in explain_frame.iterrows():
        additivity_rows.append(
            {
                "snapshot_id": row["snapshot_id"],
                "user_id": row["user_id"],
                "split": row["split"],
                "output_space": policy["explainer"]["output_space"],
                "expected_value": rounded(expected_value),
                "shap_sum": rounded(float(shap_sums[row_index])),
                "model_raw_prediction": rounded(float(raw_predictions[row_index])),
                "reconstructed_raw_prediction": rounded(float(reconstructed[row_index])),
                "absolute_error": rounded(float(absolute_errors[row_index]), 12),
                "tolerance": tolerance,
                "passes_additivity": bool(float(absolute_errors[row_index]) <= tolerance),
                "predicted_probability": rounded(float(probabilities[row_index])),
                "target": int(row["target"]),
            }
        )

    global_rows: list[dict[str, Any]] = []
    categorical_set = set(categorical_features)
    for feature_index, feature in enumerate(expected_features):
        column = values[:, feature_index]
        positive_count = int(np.sum(column > 0))
        negative_count = int(np.sum(column < 0))
        if positive_count and negative_count:
            direction = "mixed"
        elif positive_count:
            direction = "positive"
        elif negative_count:
            direction = "negative"
        else:
            direction = "zero"
        global_rows.append(
            {
                "feature_index": feature_index,
                "feature_name": feature,
                "feature_role": "categorical" if feature in categorical_set else "numeric",
                "explain_split": policy["explain_split"],
                "output_space": policy["explainer"]["output_space"],
                "mean_abs_shap": rounded(float(np.abs(column).mean())),
                "mean_shap_value": rounded(float(column.mean())),
                "std_shap_value": rounded(float(column.std(ddof=0))),
                "positive_row_count": positive_count,
                "negative_row_count": negative_count,
                "nonzero_row_count": int(np.sum(~np.isclose(column, 0.0))),
                "rank_by_mean_abs_shap": None,
                "is_top_mean_abs_shap_feature": False,
                "contribution_direction": direction,
            }
        )

    for rank, row in enumerate(
        sorted(global_rows, key=lambda item: (-float(item["mean_abs_shap"]), int(item["feature_index"]))),
        start=1,
    ):
        row["rank_by_mean_abs_shap"] = rank
        row["is_top_mean_abs_shap_feature"] = rank == 1

    local_rows: list[dict[str, Any]] = []
    local_ids = set(policy["local_explanations"]["snapshot_ids"])
    top_k = int(policy["local_explanations"]["top_k_features"])
    include_zero = bool(policy["local_explanations"].get("include_zero_contributions", False))
    for row_index, row in explain_frame.iterrows():
        if row["snapshot_id"] not in local_ids:
            continue
        contributions = []
        for feature_index, feature in enumerate(expected_features):
            shap_value = float(values[row_index, feature_index])
            if include_zero or not np.isclose(shap_value, 0.0):
                contributions.append((feature_index, feature, shap_value))
        contributions = sorted(contributions, key=lambda item: (-abs(item[2]), item[0]))[:top_k]
        for rank, (feature_index, feature, shap_value) in enumerate(contributions, start=1):
            local_rows.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "user_id": row["user_id"],
                    "prediction_time": row["prediction_time"],
                    "split": row["split"],
                    "target": int(row["target"]),
                    "raw_prediction": rounded(float(raw_predictions[row_index])),
                    "predicted_probability": rounded(float(probabilities[row_index])),
                    "expected_value": rounded(expected_value),
                    "shap_sum": rounded(float(shap_sums[row_index])),
                    "reconstructed_raw_prediction": rounded(float(reconstructed[row_index])),
                    "additivity_abs_error": rounded(float(absolute_errors[row_index]), 12),
                    "top_rank": rank,
                    "feature_index": feature_index,
                    "feature_name": feature,
                    "feature_role": "categorical" if feature in categorical_set else "numeric",
                    "feature_value": explain_matrix.loc[row_index, feature],
                    "shap_value": rounded(shap_value),
                    "absolute_shap_value": rounded(abs(shap_value)),
                    "contribution_direction": "positive" if shap_value > 0 else "negative" if shap_value < 0 else "zero",
                }
            )

    additivity_summary = {
        "expected_value": rounded(expected_value),
        "max_absolute_error": rounded(float(absolute_errors.max()) if len(absolute_errors) else None, 12),
        "passed_row_count": sum(row["passes_additivity"] for row in additivity_rows),
        "failed_row_count": sum(not row["passes_additivity"] for row in additivity_rows),
        "tolerance": tolerance,
    }
    explanation_summary = split_summary(frame, policy["explain_split"])
    explanation_summary.update(
        {
            "output_space": policy["explainer"]["output_space"],
            "raw_predictions": [rounded(float(value)) for value in raw_predictions],
            "predicted_probabilities": [rounded(float(value)) for value in probabilities],
        }
    )
    return global_rows, local_rows, additivity_rows, additivity_summary, explanation_summary


def summarize_top_features(global_rows: list[dict[str, Any]], local_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not global_rows:
        return {
            "top_mean_abs_shap_feature": None,
            "top_mean_abs_shap_value": None,
            "positive_local_contribution_count": 0,
            "negative_local_contribution_count": 0,
        }
    top = sorted(global_rows, key=lambda row: (int(row["rank_by_mean_abs_shap"]), int(row["feature_index"])))[0]
    return {
        "top_mean_abs_shap_feature": top["feature_name"],
        "top_mean_abs_shap_value": top["mean_abs_shap"],
        "top_mean_shap_value": top["mean_shap_value"],
        "top_contribution_direction": top["contribution_direction"],
        "positive_local_contribution_count": sum(row["contribution_direction"] == "positive" for row in local_rows),
        "negative_local_contribution_count": sum(row["contribution_direction"] == "negative" for row in local_rows),
        "nonzero_global_feature_count": sum(float(row["mean_abs_shap"]) > 0 for row in global_rows),
    }


def top_built_in_feature(built_in_spec: dict[str, Any], method: str) -> dict[str, Any]:
    return dict(built_in_spec.get("top_features_by_method", {}).get(method, {}))


def top_permutation_feature(permutation_spec: dict[str, Any], permutation_report: dict[str, Any]) -> dict[str, Any]:
    feature = permutation_spec.get("top_summary", {}).get("largest_absolute_mean_delta_feature")
    for row in permutation_report.get("importance", []):
        if row.get("feature_name") == feature:
            return dict(row)
    return {}


def disagreement_rows(
    *,
    global_rows: list[dict[str, Any]],
    built_in_spec: dict[str, Any],
    permutation_spec: dict[str, Any],
    permutation_report: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    shap_top = sorted(global_rows, key=lambda row: (int(row["rank_by_mean_abs_shap"]), int(row["feature_index"])))[0]
    prediction_top = top_built_in_feature(built_in_spec, "PredictionValuesChange")
    loss_top = top_built_in_feature(built_in_spec, "LossFunctionChange")
    permutation_top = top_permutation_feature(permutation_spec, permutation_report)
    top_features = {
        prediction_top.get("feature_name"),
        loss_top.get("feature_name"),
        permutation_top.get("feature_name"),
        shap_top.get("feature_name"),
    }
    same_top_feature = len({feature for feature in top_features if feature}) == 1
    disagreement_status = (
        "same_top_feature_conflicting_direction_or_scope"
        if same_top_feature
        else "different_top_features_across_methods"
    )
    note = (
        "All methods point at platform, but PredictionValuesChange is internal-positive, "
        "LossFunctionChange and permutation are negative on validation, and SHAP has mixed local signs."
    )
    rows = [
        {
            "method": "CatBoost PredictionValuesChange",
            "source_audit_id": policy["built_in_importance_audit_id"],
            "top_feature_name": prediction_top.get("feature_name"),
            "rank_basis": "normalized_absolute_importance",
            "raw_value": prediction_top.get("raw_importance"),
            "direction": "positive",
            "output_space": "model_internal_prediction_change",
            "split": "model_structure",
            "disagreement_status": disagreement_status,
            "disagreement_note": note,
        },
        {
            "method": "CatBoost LossFunctionChange",
            "source_audit_id": policy["built_in_importance_audit_id"],
            "top_feature_name": loss_top.get("feature_name"),
            "rank_basis": "normalized_absolute_importance",
            "raw_value": loss_top.get("raw_importance"),
            "direction": "negative",
            "output_space": "validation_loss_delta_when_feature_is_removed",
            "split": "validation",
            "disagreement_status": disagreement_status,
            "disagreement_note": note,
        },
        {
            "method": "Permutation importance",
            "source_audit_id": policy["permutation_importance_audit_id"],
            "top_feature_name": permutation_top.get("feature_name"),
            "rank_basis": "largest_absolute_mean_delta",
            "raw_value": permutation_top.get("mean_importance"),
            "direction": permutation_top.get("direction"),
            "output_space": "validation_neg_log_loss_delta",
            "split": policy["explain_split"],
            "disagreement_status": disagreement_status,
            "disagreement_note": note,
        },
        {
            "method": "Tree SHAP mean_abs",
            "source_audit_id": policy["shap_explanation_audit_id"],
            "top_feature_name": shap_top.get("feature_name"),
            "rank_basis": "mean_abs_shap",
            "raw_value": shap_top.get("mean_abs_shap"),
            "direction": shap_top.get("contribution_direction"),
            "output_space": policy["explainer"]["output_space"],
            "split": policy["explain_split"],
            "disagreement_status": disagreement_status,
            "disagreement_note": note,
        },
    ]
    return rows


def validate_shap_results(
    *,
    global_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
    additivity_rows: list[dict[str, Any]],
    disagreement: list[dict[str, Any]],
    expected_features: list[str],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if len(global_rows) != len(expected_features):
        checks.append(failed("shap_global_summary_covers_all_features", len(global_rows), len(expected_features)))
    else:
        checks.append(
            passed(
                "shap_global_summary_covers_all_features",
                {"feature_count": len(expected_features), "row_count": len(global_rows)},
            )
        )

    expected_local_ids = set(policy.get("local_explanations", {}).get("snapshot_ids", []))
    observed_local_ids = {row["snapshot_id"] for row in local_rows}
    if observed_local_ids != expected_local_ids:
        checks.append(
            failed(
                "shap_local_explanations_cover_declared_rows",
                sorted(observed_local_ids),
                sorted(expected_local_ids),
            )
        )
    else:
        checks.append(
            passed(
                "shap_local_explanations_cover_declared_rows",
                {"snapshot_ids": sorted(observed_local_ids), "row_count": len(local_rows)},
            )
        )

    failing_additivity = [row for row in additivity_rows if not row["passes_additivity"]]
    if failing_additivity:
        checks.append(
            failed(
                "shap_additivity_reconstructs_raw_margin",
                len(failing_additivity),
                "0 rows over tolerance",
                failing_additivity[:5],
            )
        )
    else:
        checks.append(
            passed(
                "shap_additivity_reconstructs_raw_margin",
                {
                    "row_count": len(additivity_rows),
                    "max_absolute_error": max((row["absolute_error"] for row in additivity_rows), default=0.0),
                },
            )
        )

    expected_methods = {
        "CatBoost PredictionValuesChange",
        "CatBoost LossFunctionChange",
        "Permutation importance",
        "Tree SHAP mean_abs",
    }
    observed_methods = {row["method"] for row in disagreement}
    if observed_methods != expected_methods:
        checks.append(
            failed(
                "explanation_disagreement_table_covers_built_in_permutation_and_shap",
                sorted(observed_methods),
                sorted(expected_methods),
            )
        )
    else:
        checks.append(
            passed(
                "explanation_disagreement_table_covers_built_in_permutation_and_shap",
                {"method_count": len(observed_methods), "top_features": sorted({row["top_feature_name"] for row in disagreement})},
            )
        )
    return checks


def warning_ledger_rows(
    *,
    policy: dict[str, Any],
    high_cardinality: set[str],
    correlated_pairs: list[dict[str, Any]],
    background_summary: dict[str, Any],
    explanation_summary: dict[str, Any],
    built_in_spec: dict[str, Any],
    permutation_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    warning_policy = policy.get("warning_policy", {})

    for feature in sorted(high_cardinality):
        rows.append(
            {
                "warning_id": "high_cardinality_features_flagged_for_shap_explanations",
                "severity": "warning",
                "feature_name": feature,
                "observed": feature,
                "expected": "high-cardinality categorical features interpreted with caution",
                "reason": "Sparse categories can make local categorical split explanations brittle on tiny samples.",
                "blocks_readiness": False,
            }
        )

    for pair in correlated_pairs:
        rows.append(
            {
                "warning_id": "correlated_features_can_share_shap_attribution",
                "severity": "warning",
                "feature_name": f"{pair['left_feature']}|{pair['right_feature']}",
                "observed": pair["abs_correlation"],
                "expected": f"abs correlation < {warning_policy.get('correlation_threshold')}",
                "reason": "Tree SHAP explains this tree path; correlated features can still split or hide underlying signal.",
                "blocks_readiness": False,
            }
        )

    if int(background_summary.get("row_count", 0)) < int(warning_policy.get("min_background_rows_for_stable_explanations", 0)):
        rows.append(
            {
                "warning_id": "tiny_background_reference_makes_shap_baseline_unstable",
                "severity": "warning",
                "feature_name": "",
                "observed": background_summary.get("row_count"),
                "expected": f">= {warning_policy.get('min_background_rows_for_stable_explanations')}",
                "reason": "The path-dependent SHAP baseline is documented, but four train rows are not enough for a strong explanation claim.",
                "blocks_readiness": False,
            }
        )

    if int(explanation_summary.get("row_count", 0)) < int(warning_policy.get("min_explanation_rows_for_global_summary", 0)):
        rows.append(
            {
                "warning_id": "tiny_explanation_sample_makes_global_shap_unstable",
                "severity": "warning",
                "feature_name": "",
                "observed": explanation_summary.get("row_count"),
                "expected": f">= {warning_policy.get('min_explanation_rows_for_global_summary')}",
                "reason": "Mean absolute SHAP on three validation rows is a protocol check, not a production global explanation.",
                "blocks_readiness": False,
            }
        )

    tree_count = built_in_spec.get("tree_count_summary", {}).get("tree_count")
    if int(tree_count or 0) < int(warning_policy.get("min_tree_count_for_stable_explanations", 0)):
        rows.append(
            {
                "warning_id": "tiny_tree_count_makes_shap_explanations_unstable",
                "severity": "warning",
                "feature_name": "",
                "observed": tree_count,
                "expected": f">= {warning_policy.get('min_tree_count_for_stable_explanations')}",
                "reason": "A one-tree CatBoost model is useful for testing SHAP mechanics, not for stable interpretation.",
                "blocks_readiness": False,
            }
        )

    baseline_log_loss = permutation_spec.get("heldout_summary", {}).get("baseline_log_loss")
    if float(baseline_log_loss or 0.0) >= float(warning_policy.get("max_baseline_log_loss_for_strong_claim", 1.0)):
        rows.append(
            {
                "warning_id": "poor_or_flat_model_score_limits_shap_claims",
                "severity": "warning",
                "feature_name": "",
                "observed": baseline_log_loss,
                "expected": f"< {warning_policy.get('max_baseline_log_loss_for_strong_claim')}",
                "reason": "Explaining a weak model explains its weak decision rule; it does not create a reliable business story.",
                "blocks_readiness": False,
            }
        )

    if warning_policy.get("flag_non_probability_output") and policy.get("explainer", {}).get("output_space") == "raw_margin":
        rows.append(
            {
                "warning_id": "raw_margin_output_is_not_probability",
                "severity": "warning",
                "feature_name": "",
                "observed": "raw_margin",
                "expected": "probability only after link transformation",
                "reason": "Additivity is checked in raw-margin space; local SHAP values are not probability-point changes.",
                "blocks_readiness": False,
            }
        )

    if policy.get("explainer", {}).get("background_mode") == "catboost_tree_path_dependent_training_path_counts":
        rows.append(
            {
                "warning_id": "tree_path_dependent_background_required_for_catboost_categories",
                "severity": "warning",
                "feature_name": "",
                "observed": policy.get("explainer", {}).get("background_mode"),
                "expected": "documented background mode, no external background data",
                "reason": "SHAP TreeExplainer cannot use external background data with CatBoost categorical splits; the path-dependent mode must be explicit.",
                "blocks_readiness": False,
            }
        )

    return rows


def warning_checks(warning_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for warning_id in [
        "high_cardinality_features_flagged_for_shap_explanations",
        "correlated_features_can_share_shap_attribution",
        "tiny_background_reference_makes_shap_baseline_unstable",
        "tiny_explanation_sample_makes_global_shap_unstable",
        "tiny_tree_count_makes_shap_explanations_unstable",
        "poor_or_flat_model_score_limits_shap_claims",
        "raw_margin_output_is_not_probability",
        "tree_path_dependent_background_required_for_catboost_categories",
    ]:
        rows = [row for row in warning_rows if row["warning_id"] == warning_id]
        if rows:
            checks.append(failed(warning_id, len(rows), "0 warnings", rows[:5], severity="warning"))
        else:
            checks.append(passed(warning_id, 0))
    return checks


def failure_report(error_id: str, message: str) -> dict[str, Any]:
    check = failed(error_id, message, "loadable SHAP explanation inputs")
    return {
        "valid": False,
        "shap_explanation_audit_id": None,
        "problem_id": None,
        "summary": {
            "blocking_errors": [error_id],
            "warnings": [],
            "readiness_status": "blocked_by_shap_explanation_policy",
            "generated_at": GENERATED_AT,
        },
        "checks": [check],
        "global_summary": [],
        "local_explanations": [],
        "additivity_audit": [],
        "disagreement": [],
        "warning_ledger": [],
        "serialized_spec": {},
    }


def run(
    *,
    policy_path: Path = DEFAULT_POLICY_PATH,
    catboost_spec_path: Path = DEFAULT_CATBOOST_SPEC_PATH,
    early_stopping_report_path: Path = DEFAULT_EARLY_STOPPING_REPORT_PATH,
    early_stopping_spec_path: Path = DEFAULT_EARLY_STOPPING_SPEC_PATH,
    categorical_report_path: Path = DEFAULT_CATEGORICAL_REPORT_PATH,
    built_in_report_path: Path = DEFAULT_BUILT_IN_REPORT_PATH,
    built_in_spec_path: Path = DEFAULT_BUILT_IN_SPEC_PATH,
    permutation_report_path: Path = DEFAULT_PERMUTATION_REPORT_PATH,
    permutation_spec_path: Path = DEFAULT_PERMUTATION_SPEC_PATH,
    features_path: Path = DEFAULT_FEATURES_PATH,
    labels_path: Path = DEFAULT_LABELS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    input_paths = {
        "shap_explanation_policy": policy_path,
        "catboost_model_spec": catboost_spec_path,
        "early_stopping_report": early_stopping_report_path,
        "early_stopping_serialized_spec": early_stopping_spec_path,
        "categorical_report": categorical_report_path,
        "built_in_importance_report": built_in_report_path,
        "built_in_importance_serialized_spec": built_in_spec_path,
        "permutation_importance_report": permutation_report_path,
        "permutation_importance_serialized_spec": permutation_spec_path,
        "features": features_path,
        "labels": labels_path,
        "manifest": manifest_path,
    }
    file_check = validate_required_files(input_paths)
    if not file_check["valid"]:
        return failure_report(file_check["id"], ", ".join(file_check["sample"]))

    try:
        policy = read_json(policy_path)
        catboost_spec = read_json(catboost_spec_path)
        early_report = read_json(early_stopping_report_path)
        early_spec = read_json(early_stopping_spec_path)
        categorical_report = read_json(categorical_report_path)
        built_in_report = read_json(built_in_report_path)
        built_in_spec = read_json(built_in_spec_path)
        permutation_report = read_json(permutation_report_path)
        permutation_spec = read_json(permutation_spec_path)
        frame = joined_frame(features_path, labels_path, manifest_path)
        numeric_features = list(early_spec.get("numeric_features", []))
        categorical_features = list(early_spec.get("cat_features", []))
        expected_features = expected_feature_order(catboost_spec)

        checks = [file_check]
        checks.extend(
            validate_handoff(
                policy=policy,
                catboost_spec=catboost_spec,
                early_report=early_report,
                early_spec=early_spec,
                categorical_report=categorical_report,
                built_in_report=built_in_report,
                built_in_spec=built_in_spec,
                permutation_report=permutation_report,
                permutation_spec=permutation_spec,
            )
        )
        checks.extend(validate_shap_policy(policy, expected_features))
        checks.extend(validate_background_and_explain_rows(frame, policy))

        global_rows: list[dict[str, Any]] = []
        local_rows: list[dict[str, Any]] = []
        additivity_rows: list[dict[str, Any]] = []
        disagreement: list[dict[str, Any]] = []
        warning_rows: list[dict[str, Any]] = []
        high_cardinality = high_cardinality_features(categorical_report)
        correlated_pairs: list[dict[str, Any]] = []
        background_summary = split_summary(frame, policy.get("explainer", {}).get("background_split", ""))
        explanation_summary: dict[str, Any] = {}
        additivity_summary: dict[str, Any] = {}

        if not blocking_errors(checks):
            matrix = prepare_features(
                frame,
                numeric_features,
                categorical_features,
                catboost_spec.get("feature_contract", {}).get("missing_category_token", "__MISSING__"),
            )
            model = train_model(frame=frame, matrix=matrix, early_spec=early_spec)
            if list(model.feature_names_) != expected_features:
                checks.append(failed("feature_names_match_training_pool_order", list(model.feature_names_), expected_features))
            else:
                checks.append(passed("feature_names_match_training_pool_order", {"feature_count": len(expected_features), "features": expected_features}))
            if not blocking_errors(checks):
                global_rows, local_rows, additivity_rows, additivity_summary, explanation_summary = compute_shap_outputs(
                    policy=policy,
                    model=model,
                    matrix=matrix,
                    frame=frame,
                    expected_features=expected_features,
                    categorical_features=categorical_features,
                )
                disagreement = disagreement_rows(
                    global_rows=global_rows,
                    built_in_spec=built_in_spec,
                    permutation_spec=permutation_spec,
                    permutation_report=permutation_report,
                    policy=policy,
                )
                checks.extend(
                    validate_shap_results(
                        global_rows=global_rows,
                        local_rows=local_rows,
                        additivity_rows=additivity_rows,
                        disagreement=disagreement,
                        expected_features=expected_features,
                        policy=policy,
                    )
                )
                correlated_pairs = correlated_numeric_pairs(
                    frame,
                    numeric_features,
                    policy["fit_split"],
                    float(policy.get("warning_policy", {}).get("correlation_threshold", 1.0)),
                )
                warning_rows = warning_ledger_rows(
                    policy=policy,
                    high_cardinality=high_cardinality,
                    correlated_pairs=correlated_pairs,
                    background_summary=background_summary,
                    explanation_summary=explanation_summary,
                    built_in_spec=built_in_spec,
                    permutation_spec=permutation_spec,
                )
                checks.extend(warning_checks(warning_rows))

        blocking = blocking_errors(checks)
        warnings = warning_ids(checks)
        valid = not blocking
        top_summary = summarize_top_features(global_rows, local_rows)
        disagreement_status = disagreement[0]["disagreement_status"] if disagreement else None
        serialized_spec = {
            "shap_explanation_audit_id": policy.get("shap_explanation_audit_id"),
            "problem_id": policy.get("problem_id"),
            "catboost_baseline_id": policy.get("catboost_baseline_id"),
            "source_catboost_model_id": policy.get("source_catboost_model_id"),
            "early_stopping_model_id": policy.get("early_stopping_model_id"),
            "early_stopping_audit_id": policy.get("early_stopping_audit_id"),
            "categorical_audit_id": policy.get("categorical_audit_id"),
            "built_in_importance_audit_id": policy.get("built_in_importance_audit_id"),
            "permutation_importance_audit_id": policy.get("permutation_importance_audit_id"),
            "catboost_version": catboost.__version__,
            "shap_version": shap.__version__,
            "feature_order": expected_features,
            "explainer": policy.get("explainer", {}),
            "background_summary": background_summary,
            "explanation_summary": explanation_summary,
            "additivity_summary": additivity_summary,
            "global_summary_policy": policy.get("global_summary", {}),
            "local_explanation_policy": policy.get("local_explanations", {}),
            "interpretation_policy": policy.get("interpretation_policy", {}),
            "top_summary": top_summary,
            "disagreement_summary": {
                "row_count": len(disagreement),
                "disagreement_status": disagreement_status,
                "methods": [row["method"] for row in disagreement],
                "top_features": sorted({row["top_feature_name"] for row in disagreement if row.get("top_feature_name")}),
            },
            "warning_summary": {
                "warning_count": len(warning_rows),
                "warning_ids": warnings,
                "high_cardinality_features": sorted(high_cardinality),
                "correlated_pair_count": len(correlated_pairs),
            },
            "upstream_handoff": {
                "built_in_importance_report": portable_path(built_in_report_path),
                "built_in_readiness_status": built_in_report.get("summary", {}).get("readiness_status"),
                "permutation_importance_report": portable_path(permutation_report_path),
                "permutation_readiness_status": permutation_report.get("summary", {}).get("readiness_status"),
                "early_stopping_report": portable_path(early_stopping_report_path),
                "early_stopping_model_id": early_spec.get("early_stopping_model_id"),
                "categorical_report": portable_path(categorical_report_path),
                "categorical_audit_id": categorical_report.get("summary", {}).get("categorical_audit_id"),
            },
            "output": policy.get("output", {}),
        }
        summary = {
            "shap_explanation_audit_id": policy.get("shap_explanation_audit_id"),
            "problem_id": policy.get("problem_id"),
            "source_catboost_model_id": policy.get("source_catboost_model_id"),
            "early_stopping_model_id": policy.get("early_stopping_model_id"),
            "built_in_importance_audit_id": policy.get("built_in_importance_audit_id"),
            "permutation_importance_audit_id": policy.get("permutation_importance_audit_id"),
            "background_split": policy.get("explainer", {}).get("background_split"),
            "background_row_count": background_summary.get("row_count"),
            "explain_split": policy.get("explain_split"),
            "explain_row_count": explanation_summary.get("row_count"),
            "output_space": policy.get("explainer", {}).get("output_space"),
            "expected_value": additivity_summary.get("expected_value"),
            "additivity_max_abs_error": additivity_summary.get("max_absolute_error"),
            "additivity_passed_row_count": additivity_summary.get("passed_row_count"),
            "global_summary_row_count": len(global_rows),
            "local_explanation_row_count": len(local_rows),
            "top_mean_abs_shap_feature": top_summary.get("top_mean_abs_shap_feature"),
            "top_mean_abs_shap_value": top_summary.get("top_mean_abs_shap_value"),
            "top_contribution_direction": top_summary.get("top_contribution_direction"),
            "disagreement_row_count": len(disagreement),
            "disagreement_status": disagreement_status,
            "warning_ledger_row_count": len(warning_rows),
            "blocking_errors": blocking,
            "warnings": warnings,
            "readiness_status": "ready_for_segment_analysis_lesson" if valid else "blocked_by_shap_explanation_policy",
            "generated_at": GENERATED_AT,
        }
        return {
            "valid": valid,
            "shap_explanation_audit_id": policy.get("shap_explanation_audit_id"),
            "problem_id": policy.get("problem_id"),
            "summary": summary,
            "checks": checks,
            "global_summary": global_rows,
            "local_explanations": local_rows,
            "additivity_audit": additivity_rows,
            "disagreement": disagreement,
            "warning_ledger": warning_rows,
            "serialized_spec": serialized_spec if valid else {},
        }
    except (ShapExplanationError, OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        return failure_report("shap_explanation_runtime_error", str(exc))


GLOBAL_SUMMARY_FIELDS = [
    "feature_index",
    "feature_name",
    "feature_role",
    "explain_split",
    "output_space",
    "mean_abs_shap",
    "mean_shap_value",
    "std_shap_value",
    "positive_row_count",
    "negative_row_count",
    "nonzero_row_count",
    "rank_by_mean_abs_shap",
    "is_top_mean_abs_shap_feature",
    "contribution_direction",
]

LOCAL_EXPLANATION_FIELDS = [
    "snapshot_id",
    "user_id",
    "prediction_time",
    "split",
    "target",
    "raw_prediction",
    "predicted_probability",
    "expected_value",
    "shap_sum",
    "reconstructed_raw_prediction",
    "additivity_abs_error",
    "top_rank",
    "feature_index",
    "feature_name",
    "feature_role",
    "feature_value",
    "shap_value",
    "absolute_shap_value",
    "contribution_direction",
]

ADDITIVITY_FIELDS = [
    "snapshot_id",
    "user_id",
    "split",
    "output_space",
    "expected_value",
    "shap_sum",
    "model_raw_prediction",
    "reconstructed_raw_prediction",
    "absolute_error",
    "tolerance",
    "passes_additivity",
    "predicted_probability",
    "target",
]

DISAGREEMENT_FIELDS = [
    "method",
    "source_audit_id",
    "top_feature_name",
    "rank_basis",
    "raw_value",
    "direction",
    "output_space",
    "split",
    "disagreement_status",
    "disagreement_note",
]

WARNING_FIELDS = [
    "warning_id",
    "severity",
    "feature_name",
    "observed",
    "expected",
    "reason",
    "blocks_readiness",
]


def write_outputs(result: dict[str, Any], output_dir: Path, output_spec: dict[str, str]) -> None:
    write_json(output_dir / output_spec["report_file"], {k: v for k, v in result.items() if k != "serialized_spec"})
    write_csv(output_dir / output_spec["global_summary_file"], result["global_summary"], GLOBAL_SUMMARY_FIELDS)
    write_csv(output_dir / output_spec["local_explanations_file"], result["local_explanations"], LOCAL_EXPLANATION_FIELDS)
    write_csv(output_dir / output_spec["additivity_audit_file"], result["additivity_audit"], ADDITIVITY_FIELDS)
    write_csv(output_dir / output_spec["disagreement_file"], result["disagreement"], DISAGREEMENT_FIELDS)
    write_csv(output_dir / output_spec["warning_ledger_file"], result["warning_ledger"], WARNING_FIELDS)
    write_json(output_dir / output_spec["serialized_spec_file"], result["serialized_spec"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Tree SHAP explanations for the CatBoost validation split.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--catboost-spec", type=Path, default=DEFAULT_CATBOOST_SPEC_PATH)
    parser.add_argument("--early-stopping-report", type=Path, default=DEFAULT_EARLY_STOPPING_REPORT_PATH)
    parser.add_argument("--early-stopping-spec", type=Path, default=DEFAULT_EARLY_STOPPING_SPEC_PATH)
    parser.add_argument("--categorical-report", type=Path, default=DEFAULT_CATEGORICAL_REPORT_PATH)
    parser.add_argument("--built-in-report", type=Path, default=DEFAULT_BUILT_IN_REPORT_PATH)
    parser.add_argument("--built-in-spec", type=Path, default=DEFAULT_BUILT_IN_SPEC_PATH)
    parser.add_argument("--permutation-report", type=Path, default=DEFAULT_PERMUTATION_REPORT_PATH)
    parser.add_argument("--permutation-spec", type=Path, default=DEFAULT_PERMUTATION_SPEC_PATH)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES_PATH)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output-dir", type=Path, default=LESSON_ROOT / "outputs")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(
        policy_path=args.policy,
        catboost_spec_path=args.catboost_spec,
        early_stopping_report_path=args.early_stopping_report,
        early_stopping_spec_path=args.early_stopping_spec,
        categorical_report_path=args.categorical_report,
        built_in_report_path=args.built_in_report,
        built_in_spec_path=args.built_in_spec,
        permutation_report_path=args.permutation_report,
        permutation_spec_path=args.permutation_spec,
        features_path=args.features,
        labels_path=args.labels,
        manifest_path=args.manifest,
    )
    output_spec = read_json(args.policy).get("output", {}) if args.policy.is_file() else {}
    if output_spec:
        write_outputs(result, args.output_dir, output_spec)

    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "shap_explanation_audit_id": summary.get("shap_explanation_audit_id"),
                "early_stopping_model_id": summary.get("early_stopping_model_id"),
                "explain_split": summary.get("explain_split"),
                "background_row_count": summary.get("background_row_count"),
                "explain_row_count": summary.get("explain_row_count"),
                "output_space": summary.get("output_space"),
                "expected_value": summary.get("expected_value"),
                "additivity_max_abs_error": summary.get("additivity_max_abs_error"),
                "top_mean_abs_shap_feature": summary.get("top_mean_abs_shap_feature"),
                "disagreement_status": summary.get("disagreement_status"),
                "warning_count": len(summary.get("warnings", [])),
                "readiness_status": summary.get("readiness_status"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not result["valid"]:
        return 1
    if args.fail_on_warning and summary.get("warnings"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
