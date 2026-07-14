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
from catboost import CatBoostClassifier, Pool


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
DATA_ROOT = PHASE_16_ROOT / "data" / "tiny"

DEFAULT_POLICY_PATH = DATA_ROOT / "built_in_importance_policy_spec.json"
DEFAULT_CATBOOST_SPEC_PATH = DATA_ROOT / "catboost_model_spec.json"
DEFAULT_CATEGORICAL_REPORT_PATH = (
    PHASE_16_ROOT / "02-categorical-features" / "outputs" / "categorical_feature_report.json"
)
DEFAULT_EARLY_STOPPING_REPORT_PATH = PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_report.json"
DEFAULT_EARLY_STOPPING_SPEC_PATH = (
    PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_serialized_spec.json"
)
DEFAULT_FEATURES_PATH = UPSTREAM_DATA_ROOT / "ml_raw_features.csv"
DEFAULT_LABELS_PATH = UPSTREAM_DATA_ROOT / "ml_labels.csv"
DEFAULT_MANIFEST_PATH = UPSTREAM_DATA_ROOT / "ml_split_manifest.csv"

GENERATED_AT = "2026-07-04T12:00:00+03:00"


def portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


class BuiltInImportanceError(ValueError):
    """Raised when built-in importance inputs cannot be parsed."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


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
    raise BuiltInImportanceError(f"Cannot parse boolean label: {value!r}")


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
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    required = {
        "built_in_importance_audit_id",
        "problem_id",
        "catboost_baseline_id",
        "source_catboost_model_id",
        "early_stopping_model_id",
        "early_stopping_audit_id",
        "categorical_audit_id",
        "fit_split",
        "eval_split",
        "final_holdout_split",
        "importance_methods",
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
        "eval_split": early_spec.get("fit_summary", {}).get("eval_split"),
        "final_holdout_split": early_spec.get("fit_summary", {}).get("final_holdout_split"),
    }
    for field, expected in expected_identity.items():
        if policy.get(field) != expected:
            errors.append({"field": field, "observed": policy.get(field), "expected": expected})

    if early_report.get("valid") is not True:
        errors.append({"field": "early_stopping_report.valid", "observed": early_report.get("valid"), "expected": True})
    if early_report.get("summary", {}).get("readiness_status") != "ready_for_feature_importance_lesson":
        errors.append(
            {
                "field": "early_stopping_report.summary.readiness_status",
                "observed": early_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_feature_importance_lesson",
            }
        )
    if categorical_report.get("valid") is not True:
        errors.append({"field": "categorical_report.valid", "observed": categorical_report.get("valid"), "expected": True})
    if categorical_report.get("summary", {}).get("categorical_audit_id") != policy.get("categorical_audit_id"):
        errors.append(
            {
                "field": "categorical_audit_id",
                "observed": policy.get("categorical_audit_id"),
                "expected": categorical_report.get("summary", {}).get("categorical_audit_id"),
            }
        )
    if expected_feature_order(catboost_spec) != early_spec.get("numeric_features", []) + early_spec.get("cat_features", []):
        errors.append(
            {
                "field": "feature_order",
                "observed": expected_feature_order(catboost_spec),
                "expected": early_spec.get("numeric_features", []) + early_spec.get("cat_features", []),
            }
        )

    if errors:
        return [
            failed(
                "built_in_importance_policy_matches_early_stopping_handoff",
                errors,
                "same CatBoost model, early-stopping run and categorical audit",
            )
        ]
    return [
        passed(
            "built_in_importance_policy_matches_early_stopping_handoff",
            {
                "built_in_importance_audit_id": policy["built_in_importance_audit_id"],
                "early_stopping_model_id": policy["early_stopping_model_id"],
                "early_stopping_audit_id": policy["early_stopping_audit_id"],
            },
        )
    ]


def validate_importance_policy(policy: dict[str, Any], expected_features: list[str]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    methods = policy.get("importance_methods") if isinstance(policy.get("importance_methods"), list) else []
    method_names = [item.get("method") for item in methods if isinstance(item, dict)]
    expected_methods = ["PredictionValuesChange", "LossFunctionChange"]
    if method_names != expected_methods:
        errors.append({"field": "importance_methods", "observed": method_names, "expected": expected_methods})
    for item in methods:
        if not item.get("method_label") or "diagnostic" not in item.get("interpretation_scope", ""):
            errors.append({"field": f"importance_methods.{item.get('method')}", "expected": "method label and diagnostic scope"})
        if item.get("method") == "LossFunctionChange" and (not item.get("requires_eval_data") or item.get("data_split") != policy.get("eval_split")):
            errors.append(
                {
                    "field": "LossFunctionChange.data_split",
                    "observed": item.get("data_split"),
                    "expected": policy.get("eval_split"),
                }
            )

    observed_order = policy.get("feature_name_policy", {}).get("expected_feature_order")
    if observed_order != expected_features:
        errors.append({"field": "feature_name_policy.expected_feature_order", "observed": observed_order, "expected": expected_features})

    claim = str(policy.get("interpretation_policy", {}).get("claim", "")).lower()
    forbidden = [term for term in policy.get("interpretation_policy", {}).get("forbidden_positive_claim_terms", []) if term in claim]
    if forbidden:
        errors.append({"field": "interpretation_policy.claim", "forbidden_terms": sorted(forbidden)})

    if errors:
        return [
            failed(
                "importance_policy_declares_methods_feature_names_and_noncausal_scope",
                errors,
                "two labeled CatBoost built-in methods, exact feature order and no positive causal claim",
            )
        ]
    return [
        passed(
            "importance_policy_declares_methods_feature_names_and_noncausal_scope",
            {"methods": method_names, "feature_count": len(expected_features), "claim": policy["interpretation_policy"]["claim"]},
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
            raise BuiltInImportanceError(f"{frame_name} table misses snapshot_id")
        if frame["snapshot_id"].duplicated().any():
            raise BuiltInImportanceError(f"{frame_name} table contains duplicate snapshot_id")

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


def feature_name_audit_rows(
    *,
    expected_features: list[str],
    model_features: list[str],
    numeric_features: list[str],
    categorical_features: list[str],
    high_cardinality: set[str],
    correlated_features: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, feature in enumerate(expected_features):
        rows.append(
            {
                "feature_index": index,
                "feature_name": feature,
                "expected_feature_name": feature,
                "model_feature_name": model_features[index] if index < len(model_features) else "",
                "name_matches": index < len(model_features) and model_features[index] == feature,
                "feature_role": "categorical" if feature in categorical_features else "numeric",
                "is_categorical": feature in categorical_features,
                "is_numeric": feature in numeric_features,
                "high_cardinality_feature": feature in high_cardinality,
                "correlated_feature": feature in correlated_features,
            }
        )
    return rows


def validate_feature_name_audit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mismatches = [row for row in rows if not row["name_matches"]]
    if mismatches:
        return [
            failed(
                "feature_names_match_training_pool_order",
                mismatches,
                "CatBoost model feature names exactly match policy order",
            )
        ]
    return [
        passed(
            "feature_names_match_training_pool_order",
            {"feature_count": len(rows), "features": [row["feature_name"] for row in rows]},
        )
    ]


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


def compute_importance_rows(
    *,
    policy: dict[str, Any],
    model: CatBoostClassifier,
    matrix: pd.DataFrame,
    frame: pd.DataFrame,
    expected_features: list[str],
    categorical_features: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    eval_mask = frame["split"] == policy["eval_split"]
    eval_pool = Pool(matrix.loc[eval_mask], frame.loc[eval_mask, "target"], cat_features=categorical_features)

    for method_spec in policy["importance_methods"]:
        method = method_spec["method"]
        if method_spec.get("requires_eval_data"):
            values = model.get_feature_importance(data=eval_pool, type=method)
        else:
            values = model.get_feature_importance(type=method)
        abs_total = float(np.sum(np.abs(values)))
        method_rows = []
        for index, (feature, value) in enumerate(zip(expected_features, values, strict=True)):
            raw = float(value)
            method_rows.append(
                {
                    "method": method,
                    "method_label": method_spec["method_label"],
                    "interpretation_scope": method_spec["interpretation_scope"],
                    "data_split": method_spec["data_split"],
                    "requires_eval_data": bool(method_spec["requires_eval_data"]),
                    "feature_index": index,
                    "feature_name": feature,
                    "feature_role": "categorical" if feature in categorical_features else "numeric",
                    "raw_importance": rounded(raw),
                    "absolute_importance": rounded(abs(raw)),
                    "normalized_absolute_importance": rounded(abs(raw) / abs_total) if abs_total else 0.0,
                    "direction": "positive" if raw > 0 else "negative" if raw < 0 else "zero",
                    "is_top_feature_for_method": False,
                    "rank_within_method": None,
                }
            )
        ranked = sorted(method_rows, key=lambda row: (-float(row["absolute_importance"]), int(row["feature_index"])))
        for rank, row in enumerate(ranked, start=1):
            row["rank_within_method"] = rank
            row["is_top_feature_for_method"] = rank == 1
        rows.extend(sorted(method_rows, key=lambda row: int(row["feature_index"])))
    return rows


def top_feature_by_method(importance_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for method in sorted({row["method"] for row in importance_rows}):
        top = next(row for row in importance_rows if row["method"] == method and row["is_top_feature_for_method"])
        result[method] = {
            "feature_name": top["feature_name"],
            "raw_importance": top["raw_importance"],
            "normalized_absolute_importance": top["normalized_absolute_importance"],
            "feature_role": top["feature_role"],
        }
    return result


def warning_ledger_rows(
    *,
    policy: dict[str, Any],
    importance_rows: list[dict[str, Any]],
    high_cardinality: set[str],
    correlated_pairs: list[dict[str, Any]],
    tree_count: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    warning_policy = policy.get("warning_policy", {})
    pvc_top = top_feature_by_method(importance_rows).get("PredictionValuesChange", {})
    pvc_top_value = float(pvc_top.get("raw_importance", 0.0) or 0.0)
    dominant_threshold = float(warning_policy.get("dominant_prediction_values_change_threshold", 100.0))

    for feature in sorted(high_cardinality):
        rows.append(
            {
                "warning_id": "high_cardinality_features_flagged_for_built_in_importance",
                "severity": "warning",
                "feature_name": feature,
                "method": "all_builtin_methods",
                "observed": feature,
                "expected": "high-cardinality features are interpreted with caution",
                "reason": "Built-in importance can be unstable or biased for sparse/high-cardinality categories.",
                "blocks_readiness": False,
            }
        )

    for pair in correlated_pairs:
        rows.append(
            {
                "warning_id": "correlated_features_can_split_builtin_importance",
                "severity": "warning",
                "feature_name": f"{pair['left_feature']}|{pair['right_feature']}",
                "method": "all_builtin_methods",
                "observed": pair["abs_correlation"],
                "expected": f"abs correlation < {warning_policy.get('correlation_threshold')}",
                "reason": "Built-in importance can be shared or hidden among correlated features.",
                "blocks_readiness": False,
            }
        )

    min_tree_count = int(warning_policy.get("min_tree_count_for_stable_importance", 0))
    if tree_count < min_tree_count:
        rows.append(
            {
                "warning_id": "tiny_tree_count_makes_importance_unstable",
                "severity": "warning",
                "feature_name": "",
                "method": "all_builtin_methods",
                "observed": tree_count,
                "expected": f">= {min_tree_count}",
                "reason": "A one-tree tiny model is useful for testing the protocol, not for strong interpretation claims.",
                "blocks_readiness": False,
            }
        )

    if pvc_top_value >= dominant_threshold:
        rows.append(
            {
                "warning_id": "single_feature_dominates_prediction_values_change",
                "severity": "warning",
                "feature_name": pvc_top.get("feature_name", ""),
                "method": "PredictionValuesChange",
                "observed": rounded(pvc_top_value),
                "expected": f"< {dominant_threshold}",
                "reason": "Dominant built-in importance on a tiny model can be an artifact of one split.",
                "blocks_readiness": False,
            }
        )
    return rows


def warning_checks(warning_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for warning_id in [
        "high_cardinality_features_flagged_for_built_in_importance",
        "correlated_features_can_split_builtin_importance",
        "tiny_tree_count_makes_importance_unstable",
        "single_feature_dominates_prediction_values_change",
    ]:
        rows = [row for row in warning_rows if row["warning_id"] == warning_id]
        if rows:
            checks.append(failed(warning_id, len(rows), "0 warnings", rows[:5], severity="warning"))
        else:
            checks.append(passed(warning_id, 0))
    return checks


def failure_report(error_id: str, message: str) -> dict[str, Any]:
    check = failed(error_id, message, "loadable built-in importance inputs")
    return {
        "valid": False,
        "built_in_importance_audit_id": None,
        "problem_id": None,
        "summary": {
            "blocking_errors": [error_id],
            "warnings": [],
            "readiness_status": "blocked_by_built_in_importance_policy",
            "generated_at": GENERATED_AT,
        },
        "checks": [check],
        "importance": [],
        "feature_name_audit": [],
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
    features_path: Path = DEFAULT_FEATURES_PATH,
    labels_path: Path = DEFAULT_LABELS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    input_paths = {
        "built_in_importance_policy": policy_path,
        "catboost_model_spec": catboost_spec_path,
        "early_stopping_report": early_stopping_report_path,
        "early_stopping_serialized_spec": early_stopping_spec_path,
        "categorical_report": categorical_report_path,
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
            )
        )
        checks.extend(validate_importance_policy(policy, expected_features))

        importance_rows: list[dict[str, Any]] = []
        feature_audit: list[dict[str, Any]] = []
        warning_rows: list[dict[str, Any]] = []
        correlated_pairs: list[dict[str, Any]] = []
        high_cardinality = high_cardinality_features(categorical_report)
        model: CatBoostClassifier | None = None

        if not blocking_errors(checks):
            matrix = prepare_features(
                frame,
                numeric_features,
                categorical_features,
                catboost_spec.get("feature_contract", {}).get("missing_category_token", "__MISSING__"),
            )
            model = train_model(frame=frame, matrix=matrix, early_spec=early_spec)
            correlated_pairs = correlated_numeric_pairs(
                frame,
                numeric_features,
                policy["fit_split"],
                float(policy.get("warning_policy", {}).get("correlation_threshold", 1.0)),
            )
            correlated = {pair["left_feature"] for pair in correlated_pairs} | {pair["right_feature"] for pair in correlated_pairs}
            feature_audit = feature_name_audit_rows(
                expected_features=expected_features,
                model_features=list(model.feature_names_),
                numeric_features=numeric_features,
                categorical_features=categorical_features,
                high_cardinality=high_cardinality,
                correlated_features=correlated,
            )
            checks.extend(validate_feature_name_audit(feature_audit))
            if not blocking_errors(checks):
                importance_rows = compute_importance_rows(
                    policy=policy,
                    model=model,
                    matrix=matrix,
                    frame=frame,
                    expected_features=expected_features,
                    categorical_features=categorical_features,
                )
                checks.append(
                    passed(
                        "built_in_importance_rows_cover_all_methods_and_features",
                        {
                            "method_count": len(policy["importance_methods"]),
                            "feature_count": len(expected_features),
                            "row_count": len(importance_rows),
                        },
                    )
                )
                warning_rows = warning_ledger_rows(
                    policy=policy,
                    importance_rows=importance_rows,
                    high_cardinality=high_cardinality,
                    correlated_pairs=correlated_pairs,
                    tree_count=int(early_spec.get("tree_count_summary", {}).get("tree_count", 0)),
                )
                checks.extend(warning_checks(warning_rows))

        blocking = blocking_errors(checks)
        warnings = warning_ids(checks)
        valid = not blocking
        top_by_method = top_feature_by_method(importance_rows) if importance_rows else {}
        serialized_spec = {
            "built_in_importance_audit_id": policy.get("built_in_importance_audit_id"),
            "problem_id": policy.get("problem_id"),
            "catboost_baseline_id": policy.get("catboost_baseline_id"),
            "source_catboost_model_id": policy.get("source_catboost_model_id"),
            "early_stopping_model_id": policy.get("early_stopping_model_id"),
            "early_stopping_audit_id": policy.get("early_stopping_audit_id"),
            "categorical_audit_id": policy.get("categorical_audit_id"),
            "catboost_version": catboost.__version__,
            "feature_order": expected_features,
            "importance_methods": policy.get("importance_methods", []),
            "interpretation_policy": policy.get("interpretation_policy", {}),
            "tree_count_summary": early_spec.get("tree_count_summary", {}),
            "top_features_by_method": top_by_method,
            "warning_summary": {
                "warning_count": len(warning_rows),
                "high_cardinality_features": sorted(high_cardinality),
                "correlated_pair_count": len(correlated_pairs),
            },
            "upstream_handoff": {
                "early_stopping_report": portable_path(early_stopping_report_path),
                "early_stopping_readiness_status": early_report.get("summary", {}).get("readiness_status"),
                "categorical_report": portable_path(categorical_report_path),
                "categorical_audit_id": categorical_report.get("summary", {}).get("categorical_audit_id"),
            },
            "output": policy.get("output", {}),
        }
        summary = {
            "built_in_importance_audit_id": policy.get("built_in_importance_audit_id"),
            "problem_id": policy.get("problem_id"),
            "source_catboost_model_id": policy.get("source_catboost_model_id"),
            "early_stopping_model_id": policy.get("early_stopping_model_id"),
            "method_count": len(policy.get("importance_methods", [])),
            "feature_count": len(expected_features),
            "importance_row_count": len(importance_rows),
            "feature_name_audit_row_count": len(feature_audit),
            "warning_ledger_row_count": len(warning_rows),
            "top_prediction_values_change_feature": top_by_method.get("PredictionValuesChange", {}).get("feature_name"),
            "top_loss_function_change_feature": top_by_method.get("LossFunctionChange", {}).get("feature_name"),
            "tree_count": early_spec.get("tree_count_summary", {}).get("tree_count"),
            "blocking_errors": blocking,
            "warnings": warnings,
            "readiness_status": "ready_for_permutation_importance_lesson" if valid else "blocked_by_built_in_importance_policy",
            "generated_at": GENERATED_AT,
        }
        return {
            "valid": valid,
            "built_in_importance_audit_id": policy.get("built_in_importance_audit_id"),
            "problem_id": policy.get("problem_id"),
            "summary": summary,
            "checks": checks,
            "importance": importance_rows,
            "feature_name_audit": feature_audit if valid else [],
            "warning_ledger": warning_rows,
            "serialized_spec": serialized_spec if valid else {},
        }
    except (BuiltInImportanceError, OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return failure_report("built_in_importance_runtime_error", str(exc))


IMPORTANCE_FIELDS = [
    "method",
    "method_label",
    "interpretation_scope",
    "data_split",
    "requires_eval_data",
    "feature_index",
    "feature_name",
    "feature_role",
    "raw_importance",
    "absolute_importance",
    "normalized_absolute_importance",
    "direction",
    "is_top_feature_for_method",
    "rank_within_method",
]

FEATURE_AUDIT_FIELDS = [
    "feature_index",
    "feature_name",
    "expected_feature_name",
    "model_feature_name",
    "name_matches",
    "feature_role",
    "is_categorical",
    "is_numeric",
    "high_cardinality_feature",
    "correlated_feature",
]

WARNING_FIELDS = [
    "warning_id",
    "severity",
    "feature_name",
    "method",
    "observed",
    "expected",
    "reason",
    "blocks_readiness",
]


def write_outputs(result: dict[str, Any], output_dir: Path, output_spec: dict[str, str]) -> None:
    write_json(output_dir / output_spec["report_file"], {k: v for k, v in result.items() if k != "serialized_spec"})
    write_csv(output_dir / output_spec["importance_file"], result["importance"], IMPORTANCE_FIELDS)
    write_csv(output_dir / output_spec["feature_name_audit_file"], result["feature_name_audit"], FEATURE_AUDIT_FIELDS)
    write_csv(output_dir / output_spec["warning_ledger_file"], result["warning_ledger"], WARNING_FIELDS)
    write_json(output_dir / output_spec["serialized_spec_file"], result["serialized_spec"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report CatBoost built-in feature importance with interpretation warnings.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--catboost-spec", type=Path, default=DEFAULT_CATBOOST_SPEC_PATH)
    parser.add_argument("--early-stopping-report", type=Path, default=DEFAULT_EARLY_STOPPING_REPORT_PATH)
    parser.add_argument("--early-stopping-spec", type=Path, default=DEFAULT_EARLY_STOPPING_SPEC_PATH)
    parser.add_argument("--categorical-report", type=Path, default=DEFAULT_CATEGORICAL_REPORT_PATH)
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
                "built_in_importance_audit_id": summary.get("built_in_importance_audit_id"),
                "early_stopping_model_id": summary.get("early_stopping_model_id"),
                "method_count": summary.get("method_count"),
                "feature_count": summary.get("feature_count"),
                "importance_row_count": summary.get("importance_row_count"),
                "top_prediction_values_change_feature": summary.get("top_prediction_values_change_feature"),
                "top_loss_function_change_feature": summary.get("top_loss_function_change_feature"),
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
