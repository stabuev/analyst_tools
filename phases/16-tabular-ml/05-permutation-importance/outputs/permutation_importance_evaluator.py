from __future__ import annotations

# ruff: noqa: E402

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import catboost
import numpy as np
import pandas as pd
import sklearn
from catboost import CatBoostClassifier, Pool
from sklearn.inspection import permutation_importance
from sklearn.metrics import log_loss


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
DATA_ROOT = PHASE_16_ROOT / "data" / "tiny"

DEFAULT_POLICY_PATH = DATA_ROOT / "permutation_importance_policy_spec.json"
DEFAULT_CATBOOST_SPEC_PATH = DATA_ROOT / "catboost_model_spec.json"
DEFAULT_CATEGORICAL_REPORT_PATH = (
    PHASE_16_ROOT / "02-categorical-features" / "outputs" / "categorical_feature_report.json"
)
DEFAULT_EARLY_STOPPING_REPORT_PATH = PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_report.json"
DEFAULT_EARLY_STOPPING_SPEC_PATH = (
    PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_serialized_spec.json"
)
DEFAULT_BUILT_IN_REPORT_PATH = PHASE_16_ROOT / "04-feature-importance" / "outputs" / "built_in_importance_report.json"
DEFAULT_BUILT_IN_SPEC_PATH = (
    PHASE_16_ROOT / "04-feature-importance" / "outputs" / "built_in_importance_serialized_spec.json"
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


class PermutationImportanceError(ValueError):
    """Raised when permutation-importance inputs cannot be parsed."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    raise PermutationImportanceError(f"Cannot parse boolean label: {value!r}")


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
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    required = {
        "permutation_importance_audit_id",
        "problem_id",
        "catboost_baseline_id",
        "source_catboost_model_id",
        "early_stopping_model_id",
        "early_stopping_audit_id",
        "categorical_audit_id",
        "built_in_importance_audit_id",
        "fit_split",
        "heldout_split",
        "final_holdout_split",
        "scoring",
        "permutation",
        "feature_name_policy",
        "interpretation_policy",
        "warning_policy",
        "output",
    }
    missing = sorted(required - set(policy))
    if missing:
        errors.append({"field": "root", "missing": missing})

    expected_identity = {
        "problem_id": early_spec.get("problem_id"),
        "catboost_baseline_id": early_spec.get("catboost_baseline_id"),
        "source_catboost_model_id": early_spec.get("source_catboost_model_id"),
        "early_stopping_model_id": early_spec.get("early_stopping_model_id"),
        "early_stopping_audit_id": early_spec.get("early_stopping_audit_id"),
        "categorical_audit_id": early_spec.get("categorical_audit_id"),
        "fit_split": early_spec.get("fit_summary", {}).get("fit_split"),
        "heldout_split": early_spec.get("fit_summary", {}).get("eval_split"),
        "final_holdout_split": early_spec.get("fit_summary", {}).get("final_holdout_split"),
    }
    for field, expected in expected_identity.items():
        if policy.get(field) != expected:
            errors.append({"field": field, "observed": policy.get(field), "expected": expected})

    if policy.get("built_in_importance_audit_id") != built_in_spec.get("built_in_importance_audit_id"):
        errors.append(
            {
                "field": "built_in_importance_audit_id",
                "observed": policy.get("built_in_importance_audit_id"),
                "expected": built_in_spec.get("built_in_importance_audit_id"),
            }
        )
    if built_in_report.get("valid") is not True:
        errors.append({"field": "built_in_report.valid", "observed": built_in_report.get("valid"), "expected": True})
    if built_in_report.get("summary", {}).get("readiness_status") != "ready_for_permutation_importance_lesson":
        errors.append(
            {
                "field": "built_in_report.summary.readiness_status",
                "observed": built_in_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_permutation_importance_lesson",
            }
        )
    if early_report.get("valid") is not True:
        errors.append({"field": "early_stopping_report.valid", "observed": early_report.get("valid"), "expected": True})
    if categorical_report.get("valid") is not True:
        errors.append({"field": "categorical_report.valid", "observed": categorical_report.get("valid"), "expected": True})

    expected_order = expected_feature_order(catboost_spec)
    if expected_order != early_spec.get("numeric_features", []) + early_spec.get("cat_features", []):
        errors.append(
            {
                "field": "feature_order",
                "observed": expected_order,
                "expected": early_spec.get("numeric_features", []) + early_spec.get("cat_features", []),
            }
        )
    if built_in_spec.get("feature_order") != expected_order:
        errors.append(
            {
                "field": "built_in_feature_order",
                "observed": built_in_spec.get("feature_order"),
                "expected": expected_order,
            }
        )

    if errors:
        return [
            failed(
                "permutation_policy_matches_built_in_importance_handoff",
                errors,
                "same CatBoost model, early-stopping run, categorical audit and built-in importance report",
            )
        ]
    return [
        passed(
            "permutation_policy_matches_built_in_importance_handoff",
            {
                "permutation_importance_audit_id": policy["permutation_importance_audit_id"],
                "built_in_importance_audit_id": policy["built_in_importance_audit_id"],
                "early_stopping_model_id": policy["early_stopping_model_id"],
            },
        )
    ]


def validate_permutation_policy(policy: dict[str, Any], expected_features: list[str]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    scoring = policy.get("scoring", {}) if isinstance(policy.get("scoring"), dict) else {}
    permutation = policy.get("permutation", {}) if isinstance(policy.get("permutation"), dict) else {}
    expected_scoring = {
        "name": "neg_log_loss",
        "response_method": "predict_proba",
        "greater_is_better": True,
        "importance_unit": "log_loss_increase_when_feature_is_permuted",
    }
    for field, expected in expected_scoring.items():
        if scoring.get(field) != expected:
            errors.append({"field": f"scoring.{field}", "observed": scoring.get(field), "expected": expected})
    if scoring.get("target_label_order") != [0, 1]:
        errors.append({"field": "scoring.target_label_order", "observed": scoring.get("target_label_order"), "expected": [0, 1]})

    n_repeats = permutation.get("n_repeats")
    if not isinstance(n_repeats, int) or n_repeats < 2:
        errors.append({"field": "permutation.n_repeats", "observed": n_repeats, "expected": "integer >= 2"})
    if not isinstance(permutation.get("random_state"), int):
        errors.append({"field": "permutation.random_state", "observed": permutation.get("random_state"), "expected": "integer seed"})
    if permutation.get("max_samples") != 1.0:
        errors.append({"field": "permutation.max_samples", "observed": permutation.get("max_samples"), "expected": 1.0})

    if policy.get("heldout_split") != "validation":
        errors.append({"field": "heldout_split", "observed": policy.get("heldout_split"), "expected": "validation"})
    if policy.get("final_holdout_split") != "test":
        errors.append({"field": "final_holdout_split", "observed": policy.get("final_holdout_split"), "expected": "test"})
    if policy.get("heldout_split") == policy.get("final_holdout_split"):
        errors.append({"field": "heldout_split", "observed": policy.get("heldout_split"), "expected": "not final holdout split"})

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
    if not isinstance(limitations, list) or len(limitations) < 3:
        errors.append({"field": "interpretation_policy.required_limitation_labels", "observed": limitations, "expected": "at least three limitation labels"})

    if errors:
        return [
            failed(
                "permutation_policy_declares_validation_scoring_repeats_and_noncausal_scope",
                errors,
                "validation heldout split, neg_log_loss scoring, repeats, exact feature order and no positive causal claim",
            )
        ]
    return [
        passed(
            "permutation_policy_declares_validation_scoring_repeats_and_noncausal_scope",
            {
                "heldout_split": policy["heldout_split"],
                "scoring": scoring["name"],
                "n_repeats": n_repeats,
                "feature_count": len(expected_features),
                "claim": policy["interpretation_policy"]["claim"],
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
            raise PermutationImportanceError(f"{frame_name} table misses snapshot_id")
        if frame["snapshot_id"].duplicated().any():
            raise PermutationImportanceError(f"{frame_name} table contains duplicate snapshot_id")

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


def neg_log_loss_scorer(estimator: CatBoostClassifier, matrix: pd.DataFrame, target: pd.Series) -> float:
    probabilities = estimator.predict_proba(matrix)[:, 1]
    return -float(log_loss(target, probabilities, labels=[0, 1]))


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


def validate_heldout_rows(frame: pd.DataFrame, policy: dict[str, Any]) -> list[dict[str, Any]]:
    heldout = frame.loc[frame["split"] == policy.get("heldout_split")]
    if heldout.empty:
        return [
            failed(
                "heldout_rows_use_validation_and_exclude_final_test",
                {"heldout_split": policy.get("heldout_split"), "row_count": 0},
                "non-empty validation heldout split",
            )
        ]
    if policy.get("heldout_split") == policy.get("final_holdout_split"):
        return [
            failed(
                "heldout_rows_use_validation_and_exclude_final_test",
                {"heldout_split": policy.get("heldout_split"), "final_holdout_split": policy.get("final_holdout_split")},
                "heldout split separate from final test",
            )
        ]
    return [
        passed(
            "heldout_rows_use_validation_and_exclude_final_test",
            {
                "heldout_split": policy.get("heldout_split"),
                "snapshot_ids": list(heldout["snapshot_id"]),
                "final_test_rows_used": 0,
            },
            "validation rows only",
        )
    ]


def compute_permutation_rows(
    *,
    policy: dict[str, Any],
    model: CatBoostClassifier,
    matrix: pd.DataFrame,
    frame: pd.DataFrame,
    expected_features: list[str],
    categorical_features: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    heldout_mask = frame["split"] == policy["heldout_split"]
    holdout_matrix = matrix.loc[heldout_mask]
    holdout_target = frame.loc[heldout_mask, "target"]
    baseline_score = neg_log_loss_scorer(model, holdout_matrix, holdout_target)
    baseline_log_loss = -baseline_score
    permutation_spec = policy["permutation"]
    result = permutation_importance(
        model,
        holdout_matrix,
        holdout_target,
        scoring=neg_log_loss_scorer,
        n_repeats=int(permutation_spec["n_repeats"]),
        random_state=int(permutation_spec["random_state"]),
        n_jobs=int(permutation_spec.get("n_jobs", 1)),
        max_samples=float(permutation_spec.get("max_samples", 1.0)),
    )

    importance_rows: list[dict[str, Any]] = []
    repeat_rows: list[dict[str, Any]] = []
    for feature_index, feature in enumerate(expected_features):
        values = [float(value) for value in result.importances[feature_index]]
        mean_value = float(result.importances_mean[feature_index])
        std_value = float(result.importances_std[feature_index])
        lower = mean_value - 2 * std_value
        upper = mean_value + 2 * std_value
        role = "categorical" if feature in categorical_features else "numeric"
        importance_rows.append(
            {
                "feature_index": feature_index,
                "feature_name": feature,
                "feature_role": role,
                "scoring_name": policy["scoring"]["name"],
                "importance_unit": policy["scoring"]["importance_unit"],
                "heldout_split": policy["heldout_split"],
                "repeat_count": len(values),
                "mean_importance": rounded(mean_value),
                "std_importance": rounded(std_value),
                "two_std_lower": rounded(lower),
                "two_std_upper": rounded(upper),
                "positive_importance_with_two_std_margin": lower > 0,
                "absolute_mean_importance": rounded(abs(mean_value)),
                "nonzero_repeat_count": sum(not np.isclose(value, 0.0) for value in values),
                "positive_repeat_count": sum(value > 0 for value in values),
                "negative_repeat_count": sum(value < 0 for value in values),
                "direction": "loss_increase" if mean_value > 0 else "loss_decrease_when_permuted" if mean_value < 0 else "zero",
                "rank_by_mean": None,
                "rank_by_absolute_mean": None,
                "is_largest_absolute_mean_delta": False,
            }
        )
        for repeat_index, delta in enumerate(values, start=1):
            permuted_score = baseline_score - delta
            repeat_rows.append(
                {
                    "feature_index": feature_index,
                    "feature_name": feature,
                    "feature_role": role,
                    "repeat_index": repeat_index,
                    "heldout_split": policy["heldout_split"],
                    "random_state": int(permutation_spec["random_state"]),
                    "baseline_score": rounded(baseline_score),
                    "baseline_log_loss": rounded(baseline_log_loss),
                    "importance_delta": rounded(delta),
                    "permuted_score": rounded(permuted_score),
                    "permuted_log_loss": rounded(-permuted_score),
                    "direction": "loss_increase" if delta > 0 else "loss_decrease_when_permuted" if delta < 0 else "zero",
                }
            )

    by_mean = sorted(importance_rows, key=lambda row: (-float(row["mean_importance"]), int(row["feature_index"])))
    for rank, row in enumerate(by_mean, start=1):
        row["rank_by_mean"] = rank
    by_abs = sorted(importance_rows, key=lambda row: (-float(row["absolute_mean_importance"]), int(row["feature_index"])))
    for rank, row in enumerate(by_abs, start=1):
        row["rank_by_absolute_mean"] = rank
        row["is_largest_absolute_mean_delta"] = rank == 1

    heldout_summary = {
        "heldout_split": policy["heldout_split"],
        "heldout_row_count": int(heldout_mask.sum()),
        "heldout_snapshot_ids": list(frame.loc[heldout_mask, "snapshot_id"]),
        "baseline_score": rounded(baseline_score),
        "baseline_log_loss": rounded(baseline_log_loss),
        "target_positive_count": int(holdout_target.sum()),
        "target_negative_count": int((1 - holdout_target).sum()),
    }
    return sorted(importance_rows, key=lambda row: int(row["feature_index"])), repeat_rows, heldout_summary


def summarize_top_features(importance_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not importance_rows:
        return {
            "top_mean_importance_feature": None,
            "largest_absolute_mean_delta_feature": None,
            "positive_mean_feature_count": 0,
            "positive_with_two_std_margin_feature_count": 0,
        }
    by_mean = sorted(importance_rows, key=lambda row: (int(row["rank_by_mean"]), int(row["feature_index"])))
    by_abs = sorted(importance_rows, key=lambda row: (int(row["rank_by_absolute_mean"]), int(row["feature_index"])))
    return {
        "top_mean_importance_feature": by_mean[0]["feature_name"],
        "top_mean_importance_value": by_mean[0]["mean_importance"],
        "largest_absolute_mean_delta_feature": by_abs[0]["feature_name"],
        "largest_absolute_mean_delta_value": by_abs[0]["mean_importance"],
        "positive_mean_feature_count": sum(float(row["mean_importance"]) > 0 for row in importance_rows),
        "positive_with_two_std_margin_feature_count": sum(row["positive_importance_with_two_std_margin"] for row in importance_rows),
    }


def warning_ledger_rows(
    *,
    policy: dict[str, Any],
    importance_rows: list[dict[str, Any]],
    high_cardinality: set[str],
    correlated_pairs: list[dict[str, Any]],
    heldout_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    warning_policy = policy.get("warning_policy", {})
    min_heldout_rows = int(warning_policy.get("min_heldout_rows_for_stable_importance", 0))
    max_log_loss = float(warning_policy.get("max_baseline_log_loss_for_strong_claim", 1.0))
    positive_with_margin = [row for row in importance_rows if row["positive_importance_with_two_std_margin"]]

    for feature in sorted(high_cardinality):
        rows.append(
            {
                "warning_id": "high_cardinality_features_flagged_for_permutation_importance",
                "severity": "warning",
                "feature_name": feature,
                "observed": feature,
                "expected": "high-cardinality features interpreted with repeat variance and caution",
                "reason": "Sparse or high-cardinality categories can make permutation deltas noisy on small heldout slices.",
                "blocks_readiness": False,
            }
        )

    for pair in correlated_pairs:
        rows.append(
            {
                "warning_id": "correlated_features_can_mask_permutation_importance",
                "severity": "warning",
                "feature_name": f"{pair['left_feature']}|{pair['right_feature']}",
                "observed": pair["abs_correlation"],
                "expected": f"abs correlation < {warning_policy.get('correlation_threshold')}",
                "reason": "When two features carry similar signal, shuffling one column can leave the model a proxy in the other column.",
                "blocks_readiness": False,
            }
        )

    if int(heldout_summary.get("heldout_row_count", 0)) < min_heldout_rows:
        rows.append(
            {
                "warning_id": "tiny_heldout_sample_makes_permutation_importance_unstable",
                "severity": "warning",
                "feature_name": "",
                "observed": heldout_summary.get("heldout_row_count"),
                "expected": f">= {min_heldout_rows}",
                "reason": "Permutation importance on three validation rows is a protocol check, not a production interpretation.",
                "blocks_readiness": False,
            }
        )

    if float(heldout_summary.get("baseline_log_loss", 0.0)) >= max_log_loss:
        rows.append(
            {
                "warning_id": "poor_or_flat_model_score_limits_permutation_importance",
                "severity": "warning",
                "feature_name": "",
                "observed": heldout_summary.get("baseline_log_loss"),
                "expected": f"< {max_log_loss}",
                "reason": "Permutation importance is most useful after the model has learned enough signal on the heldout metric.",
                "blocks_readiness": False,
            }
        )

    if warning_policy.get("require_positive_mean_minus_two_std_for_strong_claim") and not positive_with_margin:
        rows.append(
            {
                "warning_id": "no_positive_permutation_signal_with_uncertainty_margin",
                "severity": "warning",
                "feature_name": "",
                "observed": 0,
                "expected": ">= 1 feature with mean - 2*std > 0",
                "reason": "No feature has a positive permutation delta that clears the two-standard-deviation caution band.",
                "blocks_readiness": False,
            }
        )

    return rows


def warning_checks(warning_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for warning_id in [
        "high_cardinality_features_flagged_for_permutation_importance",
        "correlated_features_can_mask_permutation_importance",
        "tiny_heldout_sample_makes_permutation_importance_unstable",
        "poor_or_flat_model_score_limits_permutation_importance",
        "no_positive_permutation_signal_with_uncertainty_margin",
    ]:
        rows = [row for row in warning_rows if row["warning_id"] == warning_id]
        if rows:
            checks.append(failed(warning_id, len(rows), "0 warnings", rows[:5], severity="warning"))
        else:
            checks.append(passed(warning_id, 0))
    return checks


def failure_report(error_id: str, message: str) -> dict[str, Any]:
    check = failed(error_id, message, "loadable permutation importance inputs")
    return {
        "valid": False,
        "permutation_importance_audit_id": None,
        "problem_id": None,
        "summary": {
            "blocking_errors": [error_id],
            "warnings": [],
            "readiness_status": "blocked_by_permutation_importance_policy",
            "generated_at": GENERATED_AT,
        },
        "checks": [check],
        "importance": [],
        "repeats": [],
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
    features_path: Path = DEFAULT_FEATURES_PATH,
    labels_path: Path = DEFAULT_LABELS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    input_paths = {
        "permutation_importance_policy": policy_path,
        "catboost_model_spec": catboost_spec_path,
        "early_stopping_report": early_stopping_report_path,
        "early_stopping_serialized_spec": early_stopping_spec_path,
        "categorical_report": categorical_report_path,
        "built_in_importance_report": built_in_report_path,
        "built_in_importance_serialized_spec": built_in_spec_path,
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
            )
        )
        checks.extend(validate_permutation_policy(policy, expected_features))
        checks.extend(validate_heldout_rows(frame, policy))

        importance_rows: list[dict[str, Any]] = []
        repeat_rows: list[dict[str, Any]] = []
        warning_rows: list[dict[str, Any]] = []
        correlated_pairs: list[dict[str, Any]] = []
        high_cardinality = high_cardinality_features(categorical_report)
        heldout_summary: dict[str, Any] = {}

        if not blocking_errors(checks):
            matrix = prepare_features(
                frame,
                numeric_features,
                categorical_features,
                catboost_spec.get("feature_contract", {}).get("missing_category_token", "__MISSING__"),
            )
            model = train_model(frame=frame, matrix=matrix, early_spec=early_spec)
            if list(model.feature_names_) != expected_features:
                checks.append(
                    failed(
                        "feature_names_match_training_pool_order",
                        list(model.feature_names_),
                        expected_features,
                    )
                )
            else:
                checks.append(passed("feature_names_match_training_pool_order", {"feature_count": len(expected_features), "features": expected_features}))
            if not blocking_errors(checks):
                importance_rows, repeat_rows, heldout_summary = compute_permutation_rows(
                    policy=policy,
                    model=model,
                    matrix=matrix,
                    frame=frame,
                    expected_features=expected_features,
                    categorical_features=categorical_features,
                )
                checks.append(
                    passed(
                        "permutation_rows_cover_all_features_and_repeats",
                        {
                            "feature_count": len(expected_features),
                            "repeat_count": policy["permutation"]["n_repeats"],
                            "importance_row_count": len(importance_rows),
                            "repeat_row_count": len(repeat_rows),
                        },
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
                    importance_rows=importance_rows,
                    high_cardinality=high_cardinality,
                    correlated_pairs=correlated_pairs,
                    heldout_summary=heldout_summary,
                )
                checks.extend(warning_checks(warning_rows))

        blocking = blocking_errors(checks)
        warnings = warning_ids(checks)
        valid = not blocking
        top_summary = summarize_top_features(importance_rows)
        serialized_spec = {
            "permutation_importance_audit_id": policy.get("permutation_importance_audit_id"),
            "problem_id": policy.get("problem_id"),
            "catboost_baseline_id": policy.get("catboost_baseline_id"),
            "source_catboost_model_id": policy.get("source_catboost_model_id"),
            "early_stopping_model_id": policy.get("early_stopping_model_id"),
            "early_stopping_audit_id": policy.get("early_stopping_audit_id"),
            "categorical_audit_id": policy.get("categorical_audit_id"),
            "built_in_importance_audit_id": policy.get("built_in_importance_audit_id"),
            "catboost_version": catboost.__version__,
            "sklearn_version": sklearn.__version__,
            "feature_order": expected_features,
            "heldout_summary": heldout_summary,
            "scoring": policy.get("scoring", {}),
            "permutation": policy.get("permutation", {}),
            "interpretation_policy": policy.get("interpretation_policy", {}),
            "top_summary": top_summary,
            "warning_summary": {
                "warning_count": len(warning_rows),
                "warning_ids": warnings,
                "high_cardinality_features": sorted(high_cardinality),
                "correlated_pair_count": len(correlated_pairs),
            },
            "upstream_handoff": {
                "built_in_importance_report": portable_path(built_in_report_path),
                "built_in_readiness_status": built_in_report.get("summary", {}).get("readiness_status"),
                "early_stopping_report": portable_path(early_stopping_report_path),
                "early_stopping_model_id": early_spec.get("early_stopping_model_id"),
                "categorical_report": portable_path(categorical_report_path),
                "categorical_audit_id": categorical_report.get("summary", {}).get("categorical_audit_id"),
            },
            "output": policy.get("output", {}),
        }
        summary = {
            "permutation_importance_audit_id": policy.get("permutation_importance_audit_id"),
            "problem_id": policy.get("problem_id"),
            "source_catboost_model_id": policy.get("source_catboost_model_id"),
            "early_stopping_model_id": policy.get("early_stopping_model_id"),
            "built_in_importance_audit_id": policy.get("built_in_importance_audit_id"),
            "heldout_split": policy.get("heldout_split"),
            "heldout_row_count": heldout_summary.get("heldout_row_count"),
            "baseline_log_loss": heldout_summary.get("baseline_log_loss"),
            "scoring": policy.get("scoring", {}).get("name"),
            "repeat_count": policy.get("permutation", {}).get("n_repeats"),
            "feature_count": len(expected_features),
            "importance_row_count": len(importance_rows),
            "repeat_row_count": len(repeat_rows),
            "largest_absolute_mean_delta_feature": top_summary.get("largest_absolute_mean_delta_feature"),
            "largest_absolute_mean_delta_value": top_summary.get("largest_absolute_mean_delta_value"),
            "positive_mean_feature_count": top_summary.get("positive_mean_feature_count"),
            "positive_with_two_std_margin_feature_count": top_summary.get("positive_with_two_std_margin_feature_count"),
            "warning_ledger_row_count": len(warning_rows),
            "blocking_errors": blocking,
            "warnings": warnings,
            "readiness_status": "ready_for_shap_lesson" if valid else "blocked_by_permutation_importance_policy",
            "generated_at": GENERATED_AT,
        }
        return {
            "valid": valid,
            "permutation_importance_audit_id": policy.get("permutation_importance_audit_id"),
            "problem_id": policy.get("problem_id"),
            "summary": summary,
            "checks": checks,
            "importance": importance_rows,
            "repeats": repeat_rows,
            "warning_ledger": warning_rows,
            "serialized_spec": serialized_spec if valid else {},
        }
    except (PermutationImportanceError, OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return failure_report("permutation_importance_runtime_error", str(exc))


IMPORTANCE_FIELDS = [
    "feature_index",
    "feature_name",
    "feature_role",
    "scoring_name",
    "importance_unit",
    "heldout_split",
    "repeat_count",
    "mean_importance",
    "std_importance",
    "two_std_lower",
    "two_std_upper",
    "positive_importance_with_two_std_margin",
    "absolute_mean_importance",
    "nonzero_repeat_count",
    "positive_repeat_count",
    "negative_repeat_count",
    "direction",
    "rank_by_mean",
    "rank_by_absolute_mean",
    "is_largest_absolute_mean_delta",
]

REPEAT_FIELDS = [
    "feature_index",
    "feature_name",
    "feature_role",
    "repeat_index",
    "heldout_split",
    "random_state",
    "baseline_score",
    "baseline_log_loss",
    "importance_delta",
    "permuted_score",
    "permuted_log_loss",
    "direction",
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
    write_csv(output_dir / output_spec["importance_file"], result["importance"], IMPORTANCE_FIELDS)
    write_csv(output_dir / output_spec["repeat_file"], result["repeats"], REPEAT_FIELDS)
    write_csv(output_dir / output_spec["warning_ledger_file"], result["warning_ledger"], WARNING_FIELDS)
    write_json(output_dir / output_spec["serialized_spec_file"], result["serialized_spec"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate model-agnostic permutation importance on a declared heldout split.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--catboost-spec", type=Path, default=DEFAULT_CATBOOST_SPEC_PATH)
    parser.add_argument("--early-stopping-report", type=Path, default=DEFAULT_EARLY_STOPPING_REPORT_PATH)
    parser.add_argument("--early-stopping-spec", type=Path, default=DEFAULT_EARLY_STOPPING_SPEC_PATH)
    parser.add_argument("--categorical-report", type=Path, default=DEFAULT_CATEGORICAL_REPORT_PATH)
    parser.add_argument("--built-in-report", type=Path, default=DEFAULT_BUILT_IN_REPORT_PATH)
    parser.add_argument("--built-in-spec", type=Path, default=DEFAULT_BUILT_IN_SPEC_PATH)
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
                "permutation_importance_audit_id": summary.get("permutation_importance_audit_id"),
                "early_stopping_model_id": summary.get("early_stopping_model_id"),
                "heldout_split": summary.get("heldout_split"),
                "baseline_log_loss": summary.get("baseline_log_loss"),
                "repeat_count": summary.get("repeat_count"),
                "feature_count": summary.get("feature_count"),
                "importance_row_count": summary.get("importance_row_count"),
                "repeat_row_count": summary.get("repeat_row_count"),
                "largest_absolute_mean_delta_feature": summary.get("largest_absolute_mean_delta_feature"),
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
