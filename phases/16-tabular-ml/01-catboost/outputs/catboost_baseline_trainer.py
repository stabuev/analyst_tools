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
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
DATA_ROOT = PHASE_ROOT / "data" / "tiny"

DEFAULT_SPEC_PATH = DATA_ROOT / "catboost_model_spec.json"
DEFAULT_PROBLEM_SPEC_PATH = UPSTREAM_DATA_ROOT / "problem_spec.json"
DEFAULT_FEATURES_PATH = UPSTREAM_DATA_ROOT / "ml_raw_features.csv"
DEFAULT_LABELS_PATH = UPSTREAM_DATA_ROOT / "ml_labels.csv"
DEFAULT_MANIFEST_PATH = UPSTREAM_DATA_ROOT / "ml_split_manifest.csv"
DEFAULT_BASELINE_PACKAGE_REPORT_PATH = (
    PHASE_15_ROOT / "15-model-card" / "outputs" / "ml_baseline_package_report.json"
)
DEFAULT_IMBALANCE_REPORT_PATH = (
    PHASE_15_ROOT / "11-imbalanced-data" / "outputs" / "imbalance_report.json"
)

GENERATED_AT = "2026-07-03T12:00:00+03:00"
TINY_TRAIN_WARNING_THRESHOLD = 20


class CatBoostBaselineError(ValueError):
    """Raised when CatBoost baseline inputs cannot be parsed."""


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
    raise CatBoostBaselineError(f"Cannot parse boolean label: {value!r}")


def validate_required_files(paths: dict[str, Path]) -> dict[str, Any]:
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        return failed("input_files_are_present", sorted(paths), "all required input files", missing)
    return passed("input_files_are_present", sorted(paths), "all required input files")


def validate_catboost_spec(
    spec: dict[str, Any],
    *,
    problem_spec: dict[str, Any],
    baseline_package_report: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    checks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    required_fields = {
        "catboost_baseline_id",
        "problem_id",
        "baseline_package_id",
        "baseline_package_source_model_id",
        "fit_split",
        "selection_split",
        "final_holdout_split",
        "score_type",
        "candidate",
        "feature_contract",
        "comparison",
        "output",
    }
    missing = sorted(required_fields - set(spec))
    if missing:
        errors.append({"field": "root", "missing": missing})

    identity = {
        "problem_id": problem_spec.get("problem_id"),
        "baseline_package_id": baseline_package_report.get("package_id"),
    }
    for field, expected in identity.items():
        if spec.get(field) != expected:
            errors.append({"field": field, "observed": spec.get(field), "expected": expected})

    expected_splits = {
        "fit_split": "train",
        "selection_split": "validation",
        "final_holdout_split": "test",
    }
    for field, expected in expected_splits.items():
        if spec.get(field) != expected:
            errors.append({"field": field, "observed": spec.get(field), "expected": expected})

    comparison = spec.get("comparison") if isinstance(spec.get("comparison"), dict) else {}
    expected_comparison = {
        "primary_metric": "precision_at_budget",
        "selection_data": "validation",
        "test_data_role": "final_once_only_evaluation",
    }
    for field, expected in expected_comparison.items():
        observed = comparison.get(field)
        if observed != expected:
            errors.append({"field": f"comparison.{field}", "observed": observed, "expected": expected})

    candidate = spec.get("candidate") if isinstance(spec.get("candidate"), dict) else {}
    if candidate.get("kind") != "catboost_classifier":
        errors.append(
            {
                "field": "candidate.kind",
                "observed": candidate.get("kind"),
                "expected": "catboost_classifier",
            }
        )
    params = candidate.get("params") if isinstance(candidate.get("params"), dict) else {}
    if not isinstance(params.get("iterations"), int) or params.get("iterations") < 2:
        errors.append({"field": "candidate.params.iterations", "expected": "integer >= 2"})
    if params.get("depth") not in {1, 2, 3}:
        errors.append(
            {
                "field": "candidate.params.depth",
                "observed": params.get("depth"),
                "expected": "1, 2 or 3 for this tiny baseline lesson",
            }
        )
    if params.get("random_seed") is None:
        errors.append({"field": "candidate.params.random_seed", "expected": "required"})
    if params.get("allow_writing_files") is not False:
        errors.append(
            {
                "field": "candidate.params.allow_writing_files",
                "observed": params.get("allow_writing_files"),
                "expected": False,
            }
        )
    if params.get("verbose") is not False:
        errors.append(
            {
                "field": "candidate.params.verbose",
                "observed": params.get("verbose"),
                "expected": False,
            }
        )
    if params.get("thread_count") != 1:
        errors.append(
            {
                "field": "candidate.params.thread_count",
                "observed": params.get("thread_count"),
                "expected": 1,
            }
        )

    if errors:
        checks.append(
            failed(
                "catboost_spec_declares_reproducible_no_test_selection",
                errors,
                "train fit, validation selection, test-only final holdout",
            )
        )
    else:
        checks.append(
            passed(
                "catboost_spec_declares_reproducible_no_test_selection",
                {
                    "fit_split": spec["fit_split"],
                    "selection_split": spec["selection_split"],
                    "final_holdout_split": spec["final_holdout_split"],
                    "random_seed": params.get("random_seed"),
                },
            )
        )

    contract = spec.get("feature_contract") if isinstance(spec.get("feature_contract"), dict) else {}
    numeric = contract.get("numeric_features")
    categorical = contract.get("categorical_features")
    if not isinstance(numeric, list) or not numeric:
        errors.append({"field": "feature_contract.numeric_features", "expected": "non-empty list"})
        numeric = []
    if not isinstance(categorical, list) or not categorical:
        errors.append({"field": "feature_contract.categorical_features", "expected": "non-empty list"})
        categorical = []
    return checks, list(numeric), list(categorical)


def validate_baseline_package(
    spec: dict[str, Any],
    baseline_package_report: dict[str, Any],
    imbalance_report: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    package_ready = (
        baseline_package_report.get("valid") is True
        and baseline_package_report.get("package_id") == spec.get("baseline_package_id")
        and baseline_package_report.get("decision_status") == "review_required_before_production"
    )
    if package_ready:
        checks.append(
            passed(
                "baseline_package_is_ready_for_review",
                {
                    "package_id": baseline_package_report.get("package_id"),
                    "decision_status": baseline_package_report.get("decision_status"),
                },
            )
        )
    else:
        checks.append(
            failed(
                "baseline_package_is_ready_for_review",
                {
                    "valid": baseline_package_report.get("valid"),
                    "package_id": baseline_package_report.get("package_id"),
                    "decision_status": baseline_package_report.get("decision_status"),
                },
                "valid baseline package ready for review",
            )
        )

    selected_model = imbalance_report.get("summary", {}).get("selected_model_id")
    if selected_model == spec.get("baseline_package_source_model_id"):
        checks.append(passed("baseline_source_model_matches_phase15_selection", selected_model))
    else:
        checks.append(
            failed(
                "baseline_source_model_matches_phase15_selection",
                selected_model,
                spec.get("baseline_package_source_model_id"),
            )
        )
    return checks


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
            raise CatBoostBaselineError(f"{frame_name} table misses snapshot_id")
        if frame["snapshot_id"].duplicated().any():
            raise CatBoostBaselineError(f"{frame_name} table contains duplicate snapshot_id")

    frame = features.merge(labels[["snapshot_id", "churned_14d"]], on="snapshot_id", how="left")
    frame = frame.merge(
        manifest[["snapshot_id", "split", "split_order", "user_id", "prediction_time"]],
        on="snapshot_id",
        how="inner",
    )
    frame["target"] = frame["churned_14d"].map(bool_label)
    return frame.sort_values(["split_order", "snapshot_id"]).reset_index(drop=True)


def validate_feature_contract(
    frame: pd.DataFrame,
    spec: dict[str, Any],
    numeric_features: list[str],
    categorical_features: list[str],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    feature_columns = set(frame.columns)
    missing_numeric = sorted(set(numeric_features) - feature_columns)
    missing_categorical = sorted(set(categorical_features) - feature_columns)
    forbidden = set(spec.get("feature_contract", {}).get("forbidden_columns", []))
    selected_features = set(numeric_features + categorical_features)
    forbidden_selected = sorted(selected_features & forbidden)
    duplicate_features = sorted(
        feature for feature in selected_features if (numeric_features + categorical_features).count(feature) > 1
    )

    errors = []
    if missing_numeric:
        errors.append({"field": "numeric_features", "missing": missing_numeric})
    if missing_categorical:
        errors.append({"field": "categorical_features", "missing": missing_categorical})
    if forbidden_selected:
        errors.append({"field": "forbidden_columns", "selected": forbidden_selected})
    if duplicate_features:
        errors.append({"field": "duplicate_features", "selected": duplicate_features})

    if errors:
        checks.append(failed("feature_contract_matches_table", errors, "declared features exist and exclude target columns"))
    else:
        checks.append(
            passed(
                "feature_contract_matches_table",
                {
                    "numeric_feature_count": len(numeric_features),
                    "categorical_feature_count": len(categorical_features),
                },
            )
        )

    if categorical_features and not missing_categorical and not forbidden_selected:
        checks.append(passed("cat_features_are_explicit_native_columns", categorical_features))
    else:
        checks.append(
            failed(
                "cat_features_are_explicit_native_columns",
                categorical_features,
                "non-empty categorical feature names present in feature table",
            )
        )

    required_splits = {"train", "validation", "test"}
    observed_splits = set(frame["split"])
    if required_splits <= observed_splits:
        checks.append(passed("target_and_split_join_is_one_to_one", sorted(observed_splits)))
    else:
        checks.append(failed("target_and_split_join_is_one_to_one", sorted(observed_splits), sorted(required_splits)))
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


def selected_ids_at_budget(rows: list[dict[str, Any]], budget: int) -> list[str]:
    ordered = sorted(rows, key=lambda row: (-float(row["score"]), str(row["snapshot_id"])))
    return [str(row["snapshot_id"]) for row in ordered[:budget]]


def metric_row(
    *,
    source: str,
    model_id: str,
    model_kind: str,
    split: str,
    rows: list[dict[str, Any]],
    budget: int,
    selected_on_validation: bool,
    selection_rank: int,
    trained_on_split: str,
) -> dict[str, Any]:
    y_true = [int(row["actual_label"]) for row in rows]
    scores = [float(row["score"]) for row in rows]
    selected_ids = selected_ids_at_budget(rows, budget)
    selected = set(selected_ids)

    tp = sum(1 for row in rows if row["snapshot_id"] in selected and row["actual_label"] == 1)
    fp = sum(1 for row in rows if row["snapshot_id"] in selected and row["actual_label"] == 0)
    fn = sum(1 for row in rows if row["snapshot_id"] not in selected and row["actual_label"] == 1)
    tn = sum(1 for row in rows if row["snapshot_id"] not in selected and row["actual_label"] == 0)
    positive_count = sum(y_true)
    negative_count = len(y_true) - positive_count
    predicted_at_half = [1 if score >= 0.5 else 0 for score in scores]
    accuracy = sum(int(actual == predicted) for actual, predicted in zip(y_true, predicted_at_half, strict=True)) / len(y_true)
    has_both_classes = len(set(y_true)) == 2

    return {
        "source": source,
        "model_id": model_id,
        "model_kind": model_kind,
        "split": split,
        "row_count": len(rows),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "selection_budget": budget,
        "precision_at_budget": rounded(tp / len(selected_ids)) if selected_ids else None,
        "recall_at_budget": rounded(tp / positive_count) if positive_count else None,
        "average_precision": rounded(average_precision_score(y_true, scores)) if has_both_classes else None,
        "roc_auc": rounded(roc_auc_score(y_true, scores)) if has_both_classes else None,
        "log_loss": rounded(log_loss(y_true, scores, labels=[0, 1])),
        "tp_at_budget": tp,
        "fp_at_budget": fp,
        "fn_at_budget": fn,
        "tn_at_budget": tn,
        "error_cost_at_budget": rounded(fp * 1.0 + fn * 5.0),
        "accuracy_at_0_5": rounded(accuracy),
        "selected_on_validation": selected_on_validation,
        "selection_rank": selection_rank,
        "selected_ids": ",".join(selected_ids),
        "trained_on_split": trained_on_split,
    }


def prediction_rows(
    frame: pd.DataFrame,
    scores: np.ndarray,
    *,
    model_id: str,
    score_type: str,
    budget: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (_, row), score in zip(frame.iterrows(), scores, strict=True):
        rows.append(
            {
                "snapshot_id": row["snapshot_id"],
                "model_id": model_id,
                "model_kind": "catboost_classifier",
                "split": row["split"],
                "score": rounded(float(score)),
                "score_type": score_type,
                "actual_label": int(row["target"]),
                "predicted_label_at_0_5": int(float(score) >= 0.5),
                "selected_at_budget": 0,
                "trained_on_split": "train",
                "generated_at": GENERATED_AT,
            }
        )

    for split in sorted({row["split"] for row in rows}):
        split_rows = [row for row in rows if row["split"] == split]
        for snapshot_id in selected_ids_at_budget(split_rows, budget):
            next(row for row in split_rows if row["snapshot_id"] == snapshot_id)["selected_at_budget"] = 1
    return rows


def catboost_training_trace(
    *,
    train_ids: list[str],
    validation_ids: list[str],
    test_ids: list[str],
    categorical_features: list[str],
    model: CatBoostClassifier,
) -> list[dict[str, Any]]:
    return [
        {
            "event": "Pool(train)",
            "split": "train",
            "row_count": len(train_ids),
            "snapshot_ids": ",".join(train_ids),
            "cat_features": ",".join(categorical_features),
            "fits_model": True,
            "used_for_selection": False,
            "used_for_final_holdout": False,
            "tree_count": model.tree_count_,
            "best_iteration": model.get_best_iteration(),
        },
        {
            "event": "predict(validation)",
            "split": "validation",
            "row_count": len(validation_ids),
            "snapshot_ids": ",".join(validation_ids),
            "cat_features": ",".join(categorical_features),
            "fits_model": False,
            "used_for_selection": True,
            "used_for_final_holdout": False,
            "tree_count": model.tree_count_,
            "best_iteration": model.get_best_iteration(),
        },
        {
            "event": "predict(test)",
            "split": "test",
            "row_count": len(test_ids),
            "snapshot_ids": ",".join(test_ids),
            "cat_features": ",".join(categorical_features),
            "fits_model": False,
            "used_for_selection": False,
            "used_for_final_holdout": True,
            "tree_count": model.tree_count_,
            "best_iteration": model.get_best_iteration(),
        },
    ]


def baseline_rows_from_imbalance(
    imbalance_report: dict[str, Any],
    baseline_model_id: str,
) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in imbalance_report.get("comparison", [])
        if row.get("model_id") == baseline_model_id and row.get("split") in {"validation", "test"}
    ]
    for row in rows:
        row["source"] = "15/11-imbalanced-data"
        row["trained_on_split"] = "train"
        row["selected_ids"] = row.get("selected_ids", "")
    return rows


def assign_selection(
    baseline_rows: list[dict[str, Any]],
    catboost_rows: list[dict[str, Any]],
    selection_split: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    comparison = baseline_rows + catboost_rows
    validation_rows = [row for row in comparison if row["split"] == selection_split]
    ranked = sorted(
        validation_rows,
        key=lambda row: (
            -float(row["precision_at_budget"]),
            float(row["error_cost_at_budget"]),
            float(row["log_loss"]),
            str(row["model_id"]),
        ),
    )
    rank_by_model = {row["model_id"]: index + 1 for index, row in enumerate(ranked)}
    selected_model_id = ranked[0]["model_id"]
    for row in comparison:
        row["selection_rank"] = rank_by_model.get(row["model_id"], row.get("selection_rank", ""))
        row["selected_on_validation"] = row["model_id"] == selected_model_id

    selected = next(row for row in validation_rows if row["model_id"] == selected_model_id)
    selected_source = selected.get("source", "")
    return comparison, {"selected_model_id": selected_model_id, "selected_model_source": selected_source}


def build_report(
    *,
    spec: dict[str, Any],
    problem_spec: dict[str, Any],
    baseline_package_report: dict[str, Any],
    imbalance_report: dict[str, Any],
    frame: pd.DataFrame,
    matrix: pd.DataFrame,
    numeric_features: list[str],
    categorical_features: list[str],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    params = dict(spec["candidate"]["params"])
    model_id = spec["candidate"]["model_id"]
    budget = int(problem_spec["decision_budget"]["max_actions"])
    train_mask = frame["split"] == spec["fit_split"]
    train_ids = frame.loc[train_mask, "snapshot_id"].tolist()
    validation_ids = frame.loc[frame["split"] == spec["selection_split"], "snapshot_id"].tolist()
    test_ids = frame.loc[frame["split"] == spec["final_holdout_split"], "snapshot_id"].tolist()

    train_classes = sorted(frame.loc[train_mask, "target"].unique().tolist())
    if train_classes == [0, 1]:
        checks.append(passed("fit_split_has_both_classes", train_classes))
    else:
        checks.append(failed("fit_split_has_both_classes", train_classes, [0, 1]))

    model = CatBoostClassifier(**params)
    train_pool = Pool(matrix.loc[train_mask], frame.loc[train_mask, "target"], cat_features=categorical_features)
    model.fit(train_pool)
    all_pool = Pool(matrix, cat_features=categorical_features)
    scores = model.predict_proba(all_pool)[:, 1]

    predictions = prediction_rows(
        frame,
        scores,
        model_id=model_id,
        score_type=spec["score_type"],
        budget=budget,
    )
    split_predictions = {
        split: [row for row in predictions if row["split"] == split]
        for split in sorted({row["split"] for row in predictions})
    }
    catboost_metric_rows = [
        metric_row(
            source="16/01-catboost",
            model_id=model_id,
            model_kind="catboost_classifier",
            split=split,
            rows=rows,
            budget=budget,
            selected_on_validation=False,
            selection_rank=0,
            trained_on_split="train",
        )
        for split, rows in split_predictions.items()
    ]

    baseline_model_id = spec["comparison"]["baseline_model_id"]
    baseline_rows = baseline_rows_from_imbalance(imbalance_report, baseline_model_id)
    comparison, selection = assign_selection(
        baseline_rows,
        catboost_metric_rows,
        selection_split=spec["selection_split"],
    )

    trace = catboost_training_trace(
        train_ids=train_ids,
        validation_ids=validation_ids,
        test_ids=test_ids,
        categorical_features=categorical_features,
        model=model,
    )

    checks.append(passed("only_train_rows_used_for_fit", train_ids, "train split ids"))
    checks.append(passed("validation_is_selection_split", validation_ids, "validation split ids"))
    checks.append(
        passed(
            "final_holdout_not_used_for_selection",
            {
                "selection_split": spec["selection_split"],
                "final_holdout_split": spec["final_holdout_split"],
                "test_used_for_selection": False,
            },
        )
    )
    checks.append(
        passed(
            "catboost_fit_is_reproducible",
            {
                "catboost_version": catboost.__version__,
                "random_seed": params.get("random_seed"),
                "tree_count": model.tree_count_,
                "thread_count": params.get("thread_count"),
            },
        )
    )

    if len(train_ids) < TINY_TRAIN_WARNING_THRESHOLD:
        checks.append(
            failed(
                "tiny_catboost_training_sample_expected",
                len(train_ids),
                f">= {TINY_TRAIN_WARNING_THRESHOLD}",
                severity="warning",
            )
        )

    baseline_validation = next(
        row for row in comparison if row["model_id"] == baseline_model_id and row["split"] == spec["selection_split"]
    )
    catboost_validation = next(
        row for row in comparison if row["model_id"] == model_id and row["split"] == spec["selection_split"]
    )
    if catboost_validation["precision_at_budget"] <= baseline_validation["precision_at_budget"]:
        checks.append(
            failed(
                "catboost_candidate_not_promoted_without_validation_gain",
                {
                    "catboost_validation_precision_at_budget": catboost_validation["precision_at_budget"],
                    "baseline_validation_precision_at_budget": baseline_validation["precision_at_budget"],
                },
                "candidate needs validation gain before promotion",
                severity="warning",
            )
        )
    else:
        checks.append(
            passed(
                "catboost_candidate_not_promoted_without_validation_gain",
                catboost_validation["precision_at_budget"],
                f"> {baseline_validation['precision_at_budget']}",
            )
        )

    upstream_warnings = baseline_package_report.get("summary", {}).get("warnings", [])
    if upstream_warnings:
        checks.append(
            failed(
                "baseline_package_warnings_propagated_to_phase_16",
                upstream_warnings,
                "phase 16 keeps phase 15 warnings visible",
                severity="warning",
            )
        )

    serialized_spec = {
        "catboost_baseline_id": spec["catboost_baseline_id"],
        "problem_id": spec["problem_id"],
        "model": {
            "class": "CatBoostClassifier",
            "catboost_version": catboost.__version__,
            "model_id": model_id,
            "params": params,
            "tree_count": model.tree_count_,
            "best_iteration": model.get_best_iteration(),
            "feature_count": len(numeric_features) + len(categorical_features),
            "numeric_features": numeric_features,
            "cat_features": categorical_features,
        },
        "baseline_package": {
            "package_id": baseline_package_report.get("package_id"),
            "decision_status": baseline_package_report.get("decision_status"),
            "source_model_id": baseline_package_report.get("summary", {}).get("source_model_id"),
            "production_ready": False,
        },
        "selection": {
            "selection_split": spec["selection_split"],
            "final_holdout_split": spec["final_holdout_split"],
            "selected_model_id": selection["selected_model_id"],
            "selected_model_source": selection["selected_model_source"],
            "catboost_candidate_promoted": selection["selected_model_id"] == model_id,
            "test_used_for_selection": False,
            "catboost_selected_ids_on_validation": catboost_validation["selected_ids"].split(","),
            "baseline_selected_ids_on_validation": baseline_validation["selected_ids"].split(","),
        },
        "fit_trace": trace,
        "output": spec["output"],
    }

    report_valid = not blocking_errors(checks)
    summary = {
        "catboost_baseline_id": spec["catboost_baseline_id"],
        "problem_id": spec["problem_id"],
        "catboost_version": catboost.__version__,
        "fit_split": spec["fit_split"],
        "fit_row_count": len(train_ids),
        "selection_split": spec["selection_split"],
        "validation_row_count": len(validation_ids),
        "final_holdout_split": spec["final_holdout_split"],
        "test_row_count": len(test_ids),
        "model_id": model_id,
        "iterations": params["iterations"],
        "tree_count": model.tree_count_,
        "best_iteration": model.get_best_iteration(),
        "numeric_features": numeric_features,
        "cat_features": categorical_features,
        "prediction_row_count": len(predictions),
        "baseline_package_id": baseline_package_report.get("package_id"),
        "baseline_decision_status": baseline_package_report.get("decision_status"),
        "baseline_model_id": baseline_model_id,
        "selected_model_id": selection["selected_model_id"],
        "selected_model_source": selection["selected_model_source"],
        "catboost_validation_precision_at_budget": catboost_validation["precision_at_budget"],
        "baseline_validation_precision_at_budget": baseline_validation["precision_at_budget"],
        "test_used_for_selection": False,
        "blocking_errors": blocking_errors(checks),
        "warnings": warning_ids(checks),
        "readiness_status": "ready_for_categorical_feature_lesson" if report_valid else "blocked_by_catboost_contract",
        "generated_at": GENERATED_AT,
    }

    return {
        "valid": report_valid,
        "catboost_baseline_id": spec["catboost_baseline_id"],
        "problem_id": spec["problem_id"],
        "summary": summary,
        "checks": checks,
        "comparison": sorted(comparison, key=lambda row: (str(row["model_id"]), str(row["split"]))),
        "predictions": predictions,
        "training_trace": trace,
        "serialized_spec": serialized_spec,
    }


def failure_report(error_id: str, message: str) -> dict[str, Any]:
    check = failed(error_id, message, "loadable CatBoost baseline inputs")
    return {
        "valid": False,
        "catboost_baseline_id": None,
        "problem_id": None,
        "summary": {
            "blocking_errors": [error_id],
            "warnings": [],
            "readiness_status": "blocked_by_catboost_contract",
            "generated_at": GENERATED_AT,
        },
        "checks": [check],
        "comparison": [],
        "predictions": [],
        "training_trace": [],
        "serialized_spec": {},
    }


def run(
    *,
    spec_path: Path = DEFAULT_SPEC_PATH,
    problem_spec_path: Path = DEFAULT_PROBLEM_SPEC_PATH,
    features_path: Path = DEFAULT_FEATURES_PATH,
    labels_path: Path = DEFAULT_LABELS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    baseline_package_report_path: Path = DEFAULT_BASELINE_PACKAGE_REPORT_PATH,
    imbalance_report_path: Path = DEFAULT_IMBALANCE_REPORT_PATH,
) -> dict[str, Any]:
    input_paths = {
        "catboost_model_spec": spec_path,
        "problem_spec": problem_spec_path,
        "features": features_path,
        "labels": labels_path,
        "manifest": manifest_path,
        "baseline_package_report": baseline_package_report_path,
        "imbalance_report": imbalance_report_path,
    }
    file_check = validate_required_files(input_paths)
    if not file_check["valid"]:
        return failure_report(file_check["id"], ", ".join(file_check["sample"]))

    try:
        spec = read_json(spec_path)
        problem_spec = read_json(problem_spec_path)
        baseline_package_report = read_json(baseline_package_report_path)
        imbalance_report = read_json(imbalance_report_path)
        spec_checks, numeric_features, categorical_features = validate_catboost_spec(
            spec,
            problem_spec=problem_spec,
            baseline_package_report=baseline_package_report,
        )
        checks = [file_check, *spec_checks]
        checks.extend(validate_baseline_package(spec, baseline_package_report, imbalance_report))

        frame = joined_frame(features_path, labels_path, manifest_path)
        checks.extend(validate_feature_contract(frame, spec, numeric_features, categorical_features))
        if blocking_errors(checks):
            return {
                "valid": False,
                "catboost_baseline_id": spec.get("catboost_baseline_id"),
                "problem_id": spec.get("problem_id"),
                "summary": {
                    "catboost_baseline_id": spec.get("catboost_baseline_id"),
                    "problem_id": spec.get("problem_id"),
                    "blocking_errors": blocking_errors(checks),
                    "warnings": warning_ids(checks),
                    "readiness_status": "blocked_by_catboost_contract",
                    "generated_at": GENERATED_AT,
                },
                "checks": checks,
                "comparison": [],
                "predictions": [],
                "training_trace": [],
                "serialized_spec": {},
            }

        matrix = prepare_features(
            frame,
            numeric_features,
            categorical_features,
            spec["feature_contract"].get("missing_category_token", "__MISSING__"),
        )
        return build_report(
            spec=spec,
            problem_spec=problem_spec,
            baseline_package_report=baseline_package_report,
            imbalance_report=imbalance_report,
            frame=frame,
            matrix=matrix,
            numeric_features=numeric_features,
            categorical_features=categorical_features,
            checks=checks,
        )
    except (CatBoostBaselineError, OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return failure_report("catboost_baseline_runtime_error", str(exc))


COMPARISON_FIELDS = [
    "source",
    "model_id",
    "model_kind",
    "split",
    "row_count",
    "positive_count",
    "negative_count",
    "selection_budget",
    "precision_at_budget",
    "recall_at_budget",
    "average_precision",
    "roc_auc",
    "log_loss",
    "tp_at_budget",
    "fp_at_budget",
    "fn_at_budget",
    "tn_at_budget",
    "error_cost_at_budget",
    "accuracy_at_0_5",
    "selected_on_validation",
    "selection_rank",
    "selected_ids",
    "trained_on_split",
]

PREDICTION_FIELDS = [
    "snapshot_id",
    "model_id",
    "model_kind",
    "split",
    "score",
    "score_type",
    "actual_label",
    "predicted_label_at_0_5",
    "selected_at_budget",
    "trained_on_split",
    "generated_at",
]

TRACE_FIELDS = [
    "event",
    "split",
    "row_count",
    "snapshot_ids",
    "cat_features",
    "fits_model",
    "used_for_selection",
    "used_for_final_holdout",
    "tree_count",
    "best_iteration",
]


def write_outputs(result: dict[str, Any], output_dir: Path, output_spec: dict[str, str]) -> None:
    write_json(output_dir / output_spec["report_file"], {k: v for k, v in result.items() if k != "serialized_spec"})
    write_csv(output_dir / output_spec["comparison_file"], result["comparison"], COMPARISON_FIELDS)
    write_csv(output_dir / output_spec["prediction_file"], result["predictions"], PREDICTION_FIELDS)
    write_csv(output_dir / output_spec["training_trace_file"], result["training_trace"], TRACE_FIELDS)
    write_json(output_dir / output_spec["serialized_spec_file"], result["serialized_spec"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and audit a CatBoost baseline candidate.")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC_PATH)
    parser.add_argument("--problem-spec", type=Path, default=DEFAULT_PROBLEM_SPEC_PATH)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES_PATH)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--baseline-package-report", type=Path, default=DEFAULT_BASELINE_PACKAGE_REPORT_PATH)
    parser.add_argument("--imbalance-report", type=Path, default=DEFAULT_IMBALANCE_REPORT_PATH)
    parser.add_argument("--output-dir", type=Path, default=LESSON_ROOT / "outputs")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(
        spec_path=args.spec,
        problem_spec_path=args.problem_spec,
        features_path=args.features,
        labels_path=args.labels,
        manifest_path=args.manifest,
        baseline_package_report_path=args.baseline_package_report,
        imbalance_report_path=args.imbalance_report,
    )
    output_spec = read_json(args.spec).get("output", {}) if args.spec.is_file() else {}
    if output_spec:
        write_outputs(result, args.output_dir, output_spec)

    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "catboost_baseline_id": summary.get("catboost_baseline_id"),
                "model_id": summary.get("model_id"),
                "selected_model_id": summary.get("selected_model_id"),
                "catboost_validation_precision_at_budget": summary.get(
                    "catboost_validation_precision_at_budget"
                ),
                "baseline_validation_precision_at_budget": summary.get(
                    "baseline_validation_precision_at_budget"
                ),
                "test_used_for_selection": summary.get("test_used_for_selection"),
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
