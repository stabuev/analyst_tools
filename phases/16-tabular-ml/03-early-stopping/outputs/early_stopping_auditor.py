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

DEFAULT_POLICY_PATH = DATA_ROOT / "early_stopping_policy_spec.json"
DEFAULT_CATBOOST_SPEC_PATH = DATA_ROOT / "catboost_model_spec.json"
DEFAULT_CATEGORICAL_REPORT_PATH = (
    PHASE_16_ROOT / "02-categorical-features" / "outputs" / "categorical_feature_report.json"
)
DEFAULT_CATBOOST_REPORT_PATH = PHASE_16_ROOT / "01-catboost" / "outputs" / "catboost_report.json"
DEFAULT_FEATURES_PATH = UPSTREAM_DATA_ROOT / "ml_raw_features.csv"
DEFAULT_LABELS_PATH = UPSTREAM_DATA_ROOT / "ml_labels.csv"
DEFAULT_MANIFEST_PATH = UPSTREAM_DATA_ROOT / "ml_split_manifest.csv"

GENERATED_AT = "2026-07-04T10:00:00+03:00"


def portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


class EarlyStoppingAuditError(ValueError):
    """Raised when early-stopping audit inputs cannot be parsed."""


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
    raise EarlyStoppingAuditError(f"Cannot parse boolean label: {value!r}")


def validate_required_files(paths: dict[str, Path]) -> dict[str, Any]:
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        return failed("input_files_are_present", sorted(paths), "all required input files", missing)
    return passed("input_files_are_present", sorted(paths), "all required input files")


def validate_handoff(
    *,
    policy: dict[str, Any],
    catboost_spec: dict[str, Any],
    catboost_report: dict[str, Any],
    categorical_report: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    required = {
        "early_stopping_audit_id",
        "problem_id",
        "catboost_baseline_id",
        "source_catboost_model_id",
        "early_stopping_model_id",
        "categorical_audit_id",
        "fit_split",
        "eval_split",
        "final_holdout_split",
        "training_control",
        "catboost_params",
        "eval_set_policy",
        "warning_policy",
        "output",
    }
    missing = sorted(required - set(policy))
    if missing:
        errors.append({"field": "root", "missing": missing})

    expected_identity = {
        "problem_id": catboost_spec.get("problem_id"),
        "catboost_baseline_id": catboost_spec.get("catboost_baseline_id"),
        "source_catboost_model_id": catboost_spec.get("candidate", {}).get("model_id"),
        "fit_split": "train",
        "eval_split": "validation",
        "final_holdout_split": "test",
    }
    for field, expected in expected_identity.items():
        if policy.get(field) != expected:
            errors.append({"field": field, "observed": policy.get(field), "expected": expected})

    if catboost_report.get("valid") is not True:
        errors.append({"field": "catboost_report.valid", "observed": catboost_report.get("valid"), "expected": True})
    if catboost_report.get("summary", {}).get("readiness_status") != "ready_for_categorical_feature_lesson":
        errors.append(
            {
                "field": "catboost_report.summary.readiness_status",
                "observed": catboost_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_categorical_feature_lesson",
            }
        )
    if categorical_report.get("valid") is not True:
        errors.append(
            {
                "field": "categorical_report.valid",
                "observed": categorical_report.get("valid"),
                "expected": True,
            }
        )
    categorical_summary = categorical_report.get("summary", {})
    if categorical_summary.get("readiness_status") != "ready_for_early_stopping_lesson":
        errors.append(
            {
                "field": "categorical_report.summary.readiness_status",
                "observed": categorical_summary.get("readiness_status"),
                "expected": "ready_for_early_stopping_lesson",
            }
        )
    if categorical_summary.get("categorical_audit_id") != policy.get("categorical_audit_id"):
        errors.append(
            {
                "field": "categorical_audit_id",
                "observed": policy.get("categorical_audit_id"),
                "expected": categorical_summary.get("categorical_audit_id"),
            }
        )
    spec_cats = catboost_spec.get("feature_contract", {}).get("categorical_features", [])
    if categorical_summary.get("cat_features") != spec_cats:
        errors.append(
            {
                "field": "categorical_report.summary.cat_features",
                "observed": categorical_summary.get("cat_features"),
                "expected": spec_cats,
            }
        )

    if errors:
        return [
            failed(
                "early_stopping_policy_matches_upstream_handoff",
                errors,
                "same problem, CatBoost model and categorical audit readiness",
            )
        ]
    return [
        passed(
            "early_stopping_policy_matches_upstream_handoff",
            {
                "early_stopping_audit_id": policy["early_stopping_audit_id"],
                "source_catboost_model_id": policy["source_catboost_model_id"],
                "categorical_audit_id": policy["categorical_audit_id"],
            },
        )
    ]


def validate_training_control(policy: dict[str, Any], catboost_spec: dict[str, Any]) -> list[dict[str, Any]]:
    params = policy.get("catboost_params") if isinstance(policy.get("catboost_params"), dict) else {}
    control = policy.get("training_control") if isinstance(policy.get("training_control"), dict) else {}
    eval_policy = policy.get("eval_set_policy") if isinstance(policy.get("eval_set_policy"), dict) else {}
    base_params = catboost_spec.get("candidate", {}).get("params", {})
    errors: list[dict[str, Any]] = []

    planned = params.get("iterations")
    if not isinstance(planned, int) or planned <= int(base_params.get("iterations", 0)):
        errors.append(
            {
                "field": "catboost_params.iterations",
                "observed": planned,
                "expected": f"> baseline iterations {base_params.get('iterations')}",
            }
        )
    if control.get("planned_iterations") != planned:
        errors.append(
            {
                "field": "training_control.planned_iterations",
                "observed": control.get("planned_iterations"),
                "expected": planned,
            }
        )
    if params.get("od_type") != control.get("overfitting_detector_type") or params.get("od_type") != "Iter":
        errors.append({"field": "catboost_params.od_type", "observed": params.get("od_type"), "expected": "Iter"})
    if not isinstance(params.get("od_wait"), int) or params.get("od_wait") < 1:
        errors.append({"field": "catboost_params.od_wait", "observed": params.get("od_wait"), "expected": "integer >= 1"})
    if params.get("od_wait") != control.get("od_wait"):
        errors.append({"field": "training_control.od_wait", "observed": control.get("od_wait"), "expected": params.get("od_wait")})
    if params.get("use_best_model") is not True or control.get("use_best_model") is not True:
        errors.append({"field": "use_best_model", "observed": params.get("use_best_model"), "expected": True})
    if params.get("eval_metric") != control.get("eval_metric"):
        errors.append({"field": "eval_metric", "observed": params.get("eval_metric"), "expected": control.get("eval_metric")})
    for field in ("depth", "learning_rate", "loss_function", "random_seed"):
        if params.get(field) != base_params.get(field):
            errors.append({"field": f"catboost_params.{field}", "observed": params.get(field), "expected": base_params.get(field)})
    for field, expected in {
        "allow_writing_files": False,
        "verbose": False,
        "thread_count": 1,
    }.items():
        if params.get(field) != expected:
            errors.append({"field": f"catboost_params.{field}", "observed": params.get(field), "expected": expected})
    if policy.get("eval_split") != eval_policy.get("allowed_eval_split"):
        errors.append(
            {
                "field": "eval_split",
                "observed": policy.get("eval_split"),
                "expected": eval_policy.get("allowed_eval_split"),
            }
        )
    if policy.get("final_holdout_split") in set(eval_policy.get("forbidden_eval_splits", [])):
        pass
    else:
        errors.append(
            {
                "field": "eval_set_policy.forbidden_eval_splits",
                "observed": eval_policy.get("forbidden_eval_splits", []),
                "expected": [policy.get("final_holdout_split")],
            }
        )

    if errors:
        return [
            failed(
                "early_stopping_policy_declares_reproducible_training_control",
                errors,
                "fixed budget, validation eval_set, overfitting detector and use_best_model",
            )
        ]
    return [
        passed(
            "early_stopping_policy_declares_reproducible_training_control",
            {
                "planned_iterations": planned,
                "eval_metric": params.get("eval_metric"),
                "od_type": params.get("od_type"),
                "od_wait": params.get("od_wait"),
                "use_best_model": params.get("use_best_model"),
                "random_seed": params.get("random_seed"),
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
            raise EarlyStoppingAuditError(f"{frame_name} table misses snapshot_id")
        if frame["snapshot_id"].duplicated().any():
            raise EarlyStoppingAuditError(f"{frame_name} table contains duplicate snapshot_id")

    frame = features.merge(labels[["snapshot_id", "churned_14d"]], on="snapshot_id", how="left")
    frame = frame.merge(
        manifest[["snapshot_id", "split", "split_order", "user_id", "prediction_time"]],
        on="snapshot_id",
        how="inner",
    )
    frame["target"] = frame["churned_14d"].map(bool_label)
    return frame.sort_values(["split_order", "snapshot_id"]).reset_index(drop=True)


def validate_training_table(frame: pd.DataFrame, policy: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    observed_splits = sorted(frame["split"].unique().tolist())
    required_splits = sorted([policy.get("fit_split"), policy.get("eval_split"), policy.get("final_holdout_split")])
    if observed_splits == required_splits:
        checks.append(passed("training_table_has_train_validation_test_splits", observed_splits))
    else:
        checks.append(failed("training_table_has_train_validation_test_splits", observed_splits, required_splits))

    class_errors: list[dict[str, Any]] = []
    for split_name in (policy.get("fit_split"), policy.get("eval_split")):
        split_targets = sorted(frame.loc[frame["split"] == split_name, "target"].unique().tolist())
        if split_targets != [0, 1]:
            class_errors.append({"split": split_name, "observed_classes": split_targets, "expected": [0, 1]})
    if class_errors:
        checks.append(failed("fit_and_eval_splits_have_both_classes", class_errors, "both classes in train and validation"))
    else:
        checks.append(passed("fit_and_eval_splits_have_both_classes", {"train": [0, 1], "validation": [0, 1]}))
    return checks


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


def lineage_rows(frame: pd.DataFrame, policy: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    roles = {
        policy["fit_split"]: "fit_pool",
        policy["eval_split"]: "eval_set_for_overfitting_detector",
        policy["final_holdout_split"]: "final_holdout_prediction_only",
    }
    for split in (policy["fit_split"], policy["eval_split"], policy["final_holdout_split"]):
        split_frame = frame.loc[frame["split"] == split]
        rows.append(
            {
                "split": split,
                "role": roles[split],
                "row_count": len(split_frame),
                "snapshot_ids": ",".join(split_frame["snapshot_id"].tolist()),
                "used_for_fit": split == policy["fit_split"],
                "used_as_eval_set": split == policy["eval_split"],
                "used_for_best_iteration": split == policy["eval_split"],
                "used_for_final_holdout": split == policy["final_holdout_split"],
                "target_positive_count": int(split_frame["target"].sum()),
                "target_negative_count": int(len(split_frame) - split_frame["target"].sum()),
            }
        )
    return rows


def validate_lineage(lineage: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    by_split = {row["split"]: row for row in lineage}
    train_ids = by_split[policy["fit_split"]]["snapshot_ids"].split(",")
    eval_ids = by_split[policy["eval_split"]]["snapshot_ids"].split(",")
    test_used = by_split[policy["final_holdout_split"]]["used_as_eval_set"] or by_split[policy["final_holdout_split"]][
        "used_for_best_iteration"
    ]

    checks.append(passed("fit_pool_uses_only_train_rows", train_ids, "train split ids"))
    checks.append(passed("eval_set_uses_only_validation_rows", eval_ids, "validation split ids"))
    if test_used:
        checks.append(
            failed(
                "final_holdout_not_used_for_early_stopping",
                by_split[policy["final_holdout_split"]],
                "test split is not eval_set and not best-iteration selection",
            )
        )
    else:
        checks.append(
            passed(
                "final_holdout_not_used_for_early_stopping",
                {
                    "final_holdout_split": policy["final_holdout_split"],
                    "used_as_eval_set": False,
                    "used_for_best_iteration": False,
                },
            )
        )
    return checks


def build_validation_curve(model: CatBoostClassifier, best_iteration: int, metric_name: str) -> list[dict[str, Any]]:
    evals = model.get_evals_result()
    learn_values = evals.get("learn", {}).get(metric_name)
    validation_values = evals.get("validation", {}).get(metric_name)
    if not learn_values or not validation_values:
        raise EarlyStoppingAuditError(f"CatBoost did not return learn/validation {metric_name} curve")
    best_value = float(validation_values[best_iteration])
    rows: list[dict[str, Any]] = []
    for iteration, (learn_value, validation_value) in enumerate(zip(learn_values, validation_values, strict=True)):
        if iteration == best_iteration:
            role = "best_iteration"
        elif iteration > best_iteration:
            role = "after_best_within_od_wait"
        else:
            role = "before_best"
        rows.append(
            {
                "iteration": iteration,
                "learn_logloss": rounded(float(learn_value)),
                "validation_logloss": rounded(float(validation_value)),
                "is_best_iteration": iteration == best_iteration,
                "iteration_role": role,
                "delta_from_best_validation_logloss": rounded(float(validation_value) - best_value),
            }
        )
    return rows


def build_tree_count_report(
    *,
    policy: dict[str, Any],
    model: CatBoostClassifier,
    validation_curve: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    planned_iterations = int(policy["catboost_params"]["iterations"])
    baseline_iterations = int(policy["training_control"]["baseline_iterations"])
    best_iteration = model.get_best_iteration()
    if best_iteration is None:
        raise EarlyStoppingAuditError("CatBoost best_iteration is None")
    best_row = next(row for row in validation_curve if row["is_best_iteration"])
    last_row = validation_curve[-1]
    return [
        {
            "model_id": policy["early_stopping_model_id"],
            "source_model_id": policy["source_catboost_model_id"],
            "planned_iterations": planned_iterations,
            "baseline_iterations": baseline_iterations,
            "trained_iteration_count": len(validation_curve),
            "best_iteration": best_iteration,
            "tree_count": int(model.tree_count_),
            "tree_count_reduction_from_budget": planned_iterations - int(model.tree_count_),
            "tree_count_reduction_from_baseline": baseline_iterations - int(model.tree_count_),
            "stopped_before_budget": len(validation_curve) < planned_iterations,
            "use_best_model": policy["catboost_params"]["use_best_model"],
            "od_type": policy["catboost_params"]["od_type"],
            "od_wait": policy["catboost_params"]["od_wait"],
            "eval_metric": policy["catboost_params"]["eval_metric"],
            "best_validation_logloss": best_row["validation_logloss"],
            "last_validation_logloss": last_row["validation_logloss"],
            "test_used_for_best_iteration": False,
        }
    ]


def validate_trained_model(
    *,
    policy: dict[str, Any],
    model: CatBoostClassifier,
    validation_curve: list[dict[str, Any]],
    tree_count_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    params = policy["catboost_params"]
    best_iteration = model.get_best_iteration()
    planned_iterations = int(params["iterations"])
    od_wait = int(params["od_wait"])
    tree_count = int(model.tree_count_)
    trained_iteration_count = len(validation_curve)

    if best_iteration is None or not 0 <= int(best_iteration) < trained_iteration_count:
        checks.append(
            failed(
                "best_iteration_is_recorded",
                best_iteration,
                f"integer in [0, {trained_iteration_count})",
            )
        )
    else:
        checks.append(
            passed(
                "best_iteration_is_recorded",
                {
                    "best_iteration": int(best_iteration),
                    "best_validation_logloss": next(row["validation_logloss"] for row in validation_curve if row["is_best_iteration"]),
                },
            )
        )

    if best_iteration is not None and tree_count == int(best_iteration) + 1:
        checks.append(
            passed(
                "tree_count_matches_best_iteration_when_use_best_model",
                {"tree_count": tree_count, "best_iteration": int(best_iteration)},
            )
        )
    else:
        checks.append(
            failed(
                "tree_count_matches_best_iteration_when_use_best_model",
                {"tree_count": tree_count, "best_iteration": best_iteration},
                "tree_count == best_iteration + 1",
            )
        )

    if trained_iteration_count < planned_iterations and tree_count < planned_iterations:
        checks.append(
            passed(
                "training_stopped_before_full_iteration_budget",
                {
                    "planned_iterations": planned_iterations,
                    "trained_iteration_count": trained_iteration_count,
                    "tree_count": tree_count,
                },
            )
        )
    else:
        checks.append(
            failed(
                "training_stopped_before_full_iteration_budget",
                {
                    "planned_iterations": planned_iterations,
                    "trained_iteration_count": trained_iteration_count,
                    "tree_count": tree_count,
                },
                "overfitting detector stops before full budget on this tiny fixture",
            )
        )

    expected_min_curve = (int(best_iteration) + od_wait + 1) if best_iteration is not None else None
    if expected_min_curve is not None and trained_iteration_count >= expected_min_curve:
        checks.append(
            passed(
                "validation_curve_contains_best_iteration_and_patience_window",
                {"trained_iteration_count": trained_iteration_count, "od_wait": od_wait, "best_iteration": int(best_iteration)},
            )
        )
    else:
        checks.append(
            failed(
                "validation_curve_contains_best_iteration_and_patience_window",
                {"trained_iteration_count": trained_iteration_count, "od_wait": od_wait, "best_iteration": best_iteration},
                "curve includes best iteration and od_wait patience rows",
            )
        )

    report_row = tree_count_report[0]
    if report_row["test_used_for_best_iteration"] is False:
        checks.append(passed("tree_count_report_marks_test_as_invisible", report_row["test_used_for_best_iteration"]))
    else:
        checks.append(failed("tree_count_report_marks_test_as_invisible", report_row["test_used_for_best_iteration"], False))
    return checks


def warning_checks(frame: pd.DataFrame, policy: dict[str, Any], best_iteration: int | None) -> list[dict[str, Any]]:
    warning_policy = policy.get("warning_policy", {})
    checks: list[dict[str, Any]] = []
    train_count = int((frame["split"] == policy["fit_split"]).sum())
    eval_count = int((frame["split"] == policy["eval_split"]).sum())
    min_train = int(warning_policy.get("min_train_rows_for_stable_early_stopping", 0))
    min_eval = int(warning_policy.get("min_eval_rows_for_stable_early_stopping", 0))

    if train_count < min_train:
        checks.append(
            failed(
                "tiny_training_pool_expected",
                train_count,
                f">= {min_train}",
                severity="warning",
            )
        )
    else:
        checks.append(passed("tiny_training_pool_expected", train_count))
    if eval_count < min_eval:
        checks.append(
            failed(
                "tiny_eval_set_expected",
                eval_count,
                f">= {min_eval}",
                severity="warning",
            )
        )
    else:
        checks.append(passed("tiny_eval_set_expected", eval_count))
    if warning_policy.get("warn_when_best_iteration_is_zero") and best_iteration == 0:
        checks.append(
            failed(
                "best_iteration_zero_is_tiny_fixture_warning",
                best_iteration,
                "best_iteration > 0 on a stable real training set",
                severity="warning",
            )
        )
    else:
        checks.append(passed("best_iteration_zero_is_tiny_fixture_warning", best_iteration))
    return checks


def failure_report(error_id: str, message: str) -> dict[str, Any]:
    check = failed(error_id, message, "loadable early stopping audit inputs")
    return {
        "valid": False,
        "early_stopping_audit_id": None,
        "problem_id": None,
        "summary": {
            "blocking_errors": [error_id],
            "warnings": [],
            "readiness_status": "blocked_by_early_stopping_policy",
            "generated_at": GENERATED_AT,
        },
        "checks": [check],
        "eval_set_lineage": [],
        "validation_curve": [],
        "tree_count_report": [],
        "serialized_spec": {},
    }


def run(
    *,
    policy_path: Path = DEFAULT_POLICY_PATH,
    catboost_spec_path: Path = DEFAULT_CATBOOST_SPEC_PATH,
    catboost_report_path: Path = DEFAULT_CATBOOST_REPORT_PATH,
    categorical_report_path: Path = DEFAULT_CATEGORICAL_REPORT_PATH,
    features_path: Path = DEFAULT_FEATURES_PATH,
    labels_path: Path = DEFAULT_LABELS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    input_paths = {
        "early_stopping_policy": policy_path,
        "catboost_model_spec": catboost_spec_path,
        "catboost_report": catboost_report_path,
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
        catboost_report = read_json(catboost_report_path)
        categorical_report = read_json(categorical_report_path)
        frame = joined_frame(features_path, labels_path, manifest_path)
        numeric_features = list(catboost_spec.get("feature_contract", {}).get("numeric_features", []))
        categorical_features = list(catboost_spec.get("feature_contract", {}).get("categorical_features", []))
        missing_token = catboost_spec.get("feature_contract", {}).get("missing_category_token", "__MISSING__")

        checks = [file_check]
        checks.extend(
            validate_handoff(
                policy=policy,
                catboost_spec=catboost_spec,
                catboost_report=catboost_report,
                categorical_report=categorical_report,
            )
        )
        checks.extend(validate_training_control(policy, catboost_spec))
        checks.extend(validate_training_table(frame, policy))
        lineage = lineage_rows(frame, policy)
        checks.extend(validate_lineage(lineage, policy))

        validation_curve: list[dict[str, Any]] = []
        tree_count_report: list[dict[str, Any]] = []
        model: CatBoostClassifier | None = None
        if not blocking_errors(checks):
            matrix = prepare_features(frame, numeric_features, categorical_features, missing_token)
            train_mask = frame["split"] == policy["fit_split"]
            eval_mask = frame["split"] == policy["eval_split"]
            model = CatBoostClassifier(**policy["catboost_params"])
            model.fit(
                Pool(matrix.loc[train_mask], frame.loc[train_mask, "target"], cat_features=categorical_features),
                eval_set=Pool(matrix.loc[eval_mask], frame.loc[eval_mask, "target"], cat_features=categorical_features),
            )
            best_iteration = model.get_best_iteration()
            if best_iteration is None:
                raise EarlyStoppingAuditError("CatBoost did not record best_iteration")
            validation_curve = build_validation_curve(model, int(best_iteration), policy["catboost_params"]["eval_metric"])
            tree_count_report = build_tree_count_report(policy=policy, model=model, validation_curve=validation_curve)
            checks.extend(
                validate_trained_model(
                    policy=policy,
                    model=model,
                    validation_curve=validation_curve,
                    tree_count_report=tree_count_report,
                )
            )
            checks.extend(warning_checks(frame, policy, int(best_iteration)))

        blocking = blocking_errors(checks)
        warnings = warning_ids(checks)
        valid = not blocking
        report_row = tree_count_report[0] if tree_count_report else {}
        best_iteration_value = report_row.get("best_iteration")
        serialized_spec = {
            "early_stopping_audit_id": policy.get("early_stopping_audit_id"),
            "problem_id": policy.get("problem_id"),
            "catboost_baseline_id": policy.get("catboost_baseline_id"),
            "source_catboost_model_id": policy.get("source_catboost_model_id"),
            "early_stopping_model_id": policy.get("early_stopping_model_id"),
            "categorical_audit_id": policy.get("categorical_audit_id"),
            "catboost_version": catboost.__version__,
            "cat_features": categorical_features,
            "numeric_features": numeric_features,
            "training_control": policy.get("training_control", {}),
            "catboost_params": policy.get("catboost_params", {}),
            "eval_set_policy": policy.get("eval_set_policy", {}),
            "fit_summary": {
                "fit_split": policy.get("fit_split"),
                "eval_split": policy.get("eval_split"),
                "final_holdout_split": policy.get("final_holdout_split"),
                "fit_row_count": int((frame["split"] == policy.get("fit_split")).sum()),
                "eval_row_count": int((frame["split"] == policy.get("eval_split")).sum()),
                "final_holdout_row_count": int((frame["split"] == policy.get("final_holdout_split")).sum()),
            },
            "tree_count_summary": report_row,
            "upstream_handoff": {
                "catboost_report": portable_path(catboost_report_path),
                "catboost_readiness_status": catboost_report.get("summary", {}).get("readiness_status"),
                "categorical_report": portable_path(categorical_report_path),
                "categorical_readiness_status": categorical_report.get("summary", {}).get("readiness_status"),
            },
            "output": policy.get("output", {}),
        }
        summary = {
            "early_stopping_audit_id": policy.get("early_stopping_audit_id"),
            "problem_id": policy.get("problem_id"),
            "catboost_baseline_id": policy.get("catboost_baseline_id"),
            "source_catboost_model_id": policy.get("source_catboost_model_id"),
            "early_stopping_model_id": policy.get("early_stopping_model_id"),
            "catboost_version": catboost.__version__,
            "fit_split": policy.get("fit_split"),
            "fit_row_count": int((frame["split"] == policy.get("fit_split")).sum()),
            "eval_split": policy.get("eval_split"),
            "eval_set_row_count": int((frame["split"] == policy.get("eval_split")).sum()),
            "final_holdout_split": policy.get("final_holdout_split"),
            "final_holdout_row_count": int((frame["split"] == policy.get("final_holdout_split")).sum()),
            "planned_iterations": policy.get("catboost_params", {}).get("iterations"),
            "baseline_iterations": policy.get("training_control", {}).get("baseline_iterations"),
            "trained_iteration_count": report_row.get("trained_iteration_count"),
            "best_iteration": best_iteration_value,
            "tree_count": report_row.get("tree_count"),
            "stopped_before_budget": report_row.get("stopped_before_budget"),
            "test_used_for_best_iteration": report_row.get("test_used_for_best_iteration", False),
            "eval_metric": policy.get("catboost_params", {}).get("eval_metric"),
            "best_validation_logloss": report_row.get("best_validation_logloss"),
            "last_validation_logloss": report_row.get("last_validation_logloss"),
            "blocking_errors": blocking,
            "warnings": warnings,
            "readiness_status": "ready_for_feature_importance_lesson" if valid else "blocked_by_early_stopping_policy",
            "generated_at": GENERATED_AT,
        }
        return {
            "valid": valid,
            "early_stopping_audit_id": policy.get("early_stopping_audit_id"),
            "problem_id": policy.get("problem_id"),
            "summary": summary,
            "checks": checks,
            "eval_set_lineage": lineage if valid else [],
            "validation_curve": validation_curve,
            "tree_count_report": tree_count_report,
            "serialized_spec": serialized_spec if valid else {},
        }
    except (EarlyStoppingAuditError, OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return failure_report("early_stopping_audit_runtime_error", str(exc))


EVAL_SET_LINEAGE_FIELDS = [
    "split",
    "role",
    "row_count",
    "snapshot_ids",
    "used_for_fit",
    "used_as_eval_set",
    "used_for_best_iteration",
    "used_for_final_holdout",
    "target_positive_count",
    "target_negative_count",
]

VALIDATION_CURVE_FIELDS = [
    "iteration",
    "learn_logloss",
    "validation_logloss",
    "is_best_iteration",
    "iteration_role",
    "delta_from_best_validation_logloss",
]

TREE_COUNT_REPORT_FIELDS = [
    "model_id",
    "source_model_id",
    "planned_iterations",
    "baseline_iterations",
    "trained_iteration_count",
    "best_iteration",
    "tree_count",
    "tree_count_reduction_from_budget",
    "tree_count_reduction_from_baseline",
    "stopped_before_budget",
    "use_best_model",
    "od_type",
    "od_wait",
    "eval_metric",
    "best_validation_logloss",
    "last_validation_logloss",
    "test_used_for_best_iteration",
]


def write_outputs(result: dict[str, Any], output_dir: Path, output_spec: dict[str, str]) -> None:
    write_json(output_dir / output_spec["report_file"], {k: v for k, v in result.items() if k != "serialized_spec"})
    write_csv(output_dir / output_spec["eval_set_lineage_file"], result["eval_set_lineage"], EVAL_SET_LINEAGE_FIELDS)
    write_csv(output_dir / output_spec["validation_curve_file"], result["validation_curve"], VALIDATION_CURVE_FIELDS)
    write_csv(output_dir / output_spec["tree_count_report_file"], result["tree_count_report"], TREE_COUNT_REPORT_FIELDS)
    write_json(output_dir / output_spec["serialized_spec_file"], result["serialized_spec"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit CatBoost early stopping and iteration budget protocol.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--catboost-spec", type=Path, default=DEFAULT_CATBOOST_SPEC_PATH)
    parser.add_argument("--catboost-report", type=Path, default=DEFAULT_CATBOOST_REPORT_PATH)
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
        catboost_report_path=args.catboost_report,
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
                "early_stopping_audit_id": summary.get("early_stopping_audit_id"),
                "early_stopping_model_id": summary.get("early_stopping_model_id"),
                "planned_iterations": summary.get("planned_iterations"),
                "trained_iteration_count": summary.get("trained_iteration_count"),
                "best_iteration": summary.get("best_iteration"),
                "tree_count": summary.get("tree_count"),
                "stopped_before_budget": summary.get("stopped_before_budget"),
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
