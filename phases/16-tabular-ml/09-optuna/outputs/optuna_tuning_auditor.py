from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import catboost
import optuna
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import log_loss


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
DATA_ROOT = PHASE_16_ROOT / "data" / "tiny"

DEFAULT_POLICY_PATH = DATA_ROOT / "optuna_tuning_policy_spec.json"
DEFAULT_CATBOOST_SPEC_PATH = DATA_ROOT / "catboost_model_spec.json"
DEFAULT_EARLY_STOPPING_REPORT_PATH = (
    PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_report.json"
)
DEFAULT_EARLY_STOPPING_SPEC_PATH = (
    PHASE_16_ROOT / "03-early-stopping" / "outputs" / "early_stopping_serialized_spec.json"
)
DEFAULT_COST_REPORT_PATH = (
    PHASE_16_ROOT
    / "08-cost-sensitive-decisions"
    / "outputs"
    / "cost_sensitive_decision_report.json"
)
DEFAULT_COST_SPEC_PATH = (
    PHASE_16_ROOT
    / "08-cost-sensitive-decisions"
    / "outputs"
    / "cost_sensitive_decision_serialized_spec.json"
)
DEFAULT_FEATURES_PATH = UPSTREAM_DATA_ROOT / "ml_raw_features.csv"
DEFAULT_LABELS_PATH = UPSTREAM_DATA_ROOT / "ml_labels.csv"
DEFAULT_MANIFEST_PATH = UPSTREAM_DATA_ROOT / "ml_split_manifest.csv"

GENERATED_AT = "2026-07-06T11:30:00+03:00"


class OptunaTuningAuditError(ValueError):
    """Raised when Optuna tuning audit inputs cannot be parsed."""


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
    return value


def csv_ready(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return str(rounded(value))
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(json_ready(value), ensure_ascii=False, sort_keys=True)
    return str(value)


def rounded(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


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
    raise OptunaTuningAuditError(f"Cannot parse boolean label: {value!r}")


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
    cost_report: dict[str, Any],
    cost_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    required = {
        "optuna_tuning_audit_id",
        "problem_id",
        "baseline_package_id",
        "source_candidate_model_id",
        "tuned_candidate_model_id",
        "catboost_baseline_id",
        "early_stopping_audit_id",
        "cost_sensitive_decision_audit_id",
        "fit_split",
        "objective_split",
        "final_holdout_split",
        "study",
        "search_space",
        "fixed_catboost_params",
        "feature_contract",
        "objective_policy",
        "cost_policy",
        "decision_policy",
        "warning_policy",
        "output",
    }
    missing = sorted(required - set(policy))
    if missing:
        checks.append(failed("optuna_policy_has_required_fields", missing, "no missing fields"))
    else:
        checks.append(passed("optuna_policy_has_required_fields", sorted(required), "required policy fields"))

    handoff_errors: list[dict[str, Any]] = []
    expected_identity = {
        "problem_id": catboost_spec.get("problem_id"),
        "baseline_package_id": catboost_spec.get("baseline_package_id"),
        "catboost_baseline_id": catboost_spec.get("catboost_baseline_id"),
        "source_candidate_model_id": early_spec.get("early_stopping_model_id"),
        "early_stopping_audit_id": early_spec.get("early_stopping_audit_id"),
        "cost_sensitive_decision_audit_id": cost_spec.get("cost_sensitive_decision_audit_id"),
        "fit_split": early_spec.get("fit_summary", {}).get("fit_split"),
        "objective_split": early_spec.get("fit_summary", {}).get("eval_split"),
        "final_holdout_split": early_spec.get("fit_summary", {}).get("final_holdout_split"),
    }
    for field, expected in expected_identity.items():
        if policy.get(field) != expected:
            handoff_errors.append({"field": field, "observed": policy.get(field), "expected": expected})

    if early_report.get("valid") is not True:
        handoff_errors.append({"field": "early_report.valid", "observed": early_report.get("valid"), "expected": True})
    if early_report.get("summary", {}).get("readiness_status") != "ready_for_feature_importance_lesson":
        handoff_errors.append(
            {
                "field": "early_report.summary.readiness_status",
                "observed": early_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_feature_importance_lesson",
            }
        )
    if cost_report.get("valid") is not True:
        handoff_errors.append({"field": "cost_report.valid", "observed": cost_report.get("valid"), "expected": True})
    if cost_report.get("summary", {}).get("readiness_status") != "ready_for_optuna_lesson":
        handoff_errors.append(
            {
                "field": "cost_report.summary.readiness_status",
                "observed": cost_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_optuna_lesson",
            }
        )
    if handoff_errors:
        checks.append(failed("optuna_policy_matches_upstream_handoff", handoff_errors, "same CatBoost, cost decision and split handoffs"))
    else:
        checks.append(
            passed(
                "optuna_policy_matches_upstream_handoff",
                {
                    "optuna_tuning_audit_id": policy["optuna_tuning_audit_id"],
                    "source_candidate_model_id": policy["source_candidate_model_id"],
                    "objective_split": policy["objective_split"],
                },
                "same CatBoost, cost decision and split handoffs",
            )
        )

    objective_errors: list[dict[str, Any]] = []
    objective_policy = policy.get("objective_policy", {})
    if policy.get("fit_split") != objective_policy.get("fit_data"):
        objective_errors.append({"field": "objective_policy.fit_data", "observed": objective_policy.get("fit_data"), "expected": policy.get("fit_split")})
    if policy.get("objective_split") != objective_policy.get("selection_data"):
        objective_errors.append(
            {
                "field": "objective_policy.selection_data",
                "observed": objective_policy.get("selection_data"),
                "expected": policy.get("objective_split"),
            }
        )
    if objective_policy.get("forbid_objective_on_test") is not True:
        objective_errors.append(
            {
                "field": "objective_policy.forbid_objective_on_test",
                "observed": objective_policy.get("forbid_objective_on_test"),
                "expected": True,
            }
        )
    if policy.get("objective_split") == policy.get("final_holdout_split"):
        objective_errors.append(
            {
                "field": "objective_split",
                "observed": policy.get("objective_split"),
                "expected": f"not {policy.get('final_holdout_split')}",
            }
        )
    if objective_errors:
        checks.append(failed("objective_uses_validation_and_excludes_test", objective_errors, "train fit, validation objective, test invisible"))
    else:
        checks.append(
            passed(
                "objective_uses_validation_and_excludes_test",
                {
                    "fit_split": policy["fit_split"],
                    "objective_split": policy["objective_split"],
                    "final_holdout_split": policy["final_holdout_split"],
                },
                "train fit, validation objective, test invisible",
            )
        )

    study_errors: list[dict[str, Any]] = []
    study = policy.get("study", {})
    if study.get("direction") != "minimize":
        study_errors.append({"field": "study.direction", "observed": study.get("direction"), "expected": "minimize"})
    if study.get("objective_metric") != "validation_logloss":
        study_errors.append({"field": "study.objective_metric", "observed": study.get("objective_metric"), "expected": "validation_logloss"})
    if int(study.get("n_trials", 0)) <= 0 or int(study.get("n_trials", 0)) > int(study.get("max_trials_allowed", 0)):
        study_errors.append(
            {
                "field": "study.n_trials",
                "observed": study.get("n_trials"),
                "expected": f"1..{study.get('max_trials_allowed')}",
            }
        )
    if study.get("sampler", {}).get("name") != "GridSampler":
        study_errors.append({"field": "study.sampler.name", "observed": study.get("sampler", {}).get("name"), "expected": "GridSampler"})
    if not isinstance(study.get("sampler", {}).get("seed"), int):
        study_errors.append({"field": "study.sampler.seed", "observed": study.get("sampler", {}).get("seed"), "expected": "integer seed"})
    if policy.get("fixed_catboost_params", {}).get("random_seed") != study.get("sampler", {}).get("seed"):
        study_errors.append(
            {
                "field": "fixed_catboost_params.random_seed",
                "observed": policy.get("fixed_catboost_params", {}).get("random_seed"),
                "expected": study.get("sampler", {}).get("seed"),
            }
        )
    grid_size = search_space_grid_size(policy.get("search_space", {}))
    if grid_size != study.get("n_trials"):
        study_errors.append({"field": "search_space.grid_size", "observed": grid_size, "expected": study.get("n_trials")})
    if study_errors:
        checks.append(failed("study_declares_fixed_budget_seed_and_grid", study_errors, "fixed budget, reproducible seed and fully covered grid"))
    else:
        checks.append(
            passed(
                "study_declares_fixed_budget_seed_and_grid",
                {
                    "n_trials": study["n_trials"],
                    "sampler": study["sampler"]["name"],
                    "seed": study["sampler"]["seed"],
                    "grid_size": grid_size,
                },
                "fixed budget, reproducible seed and fully covered grid",
            )
        )

    feature_errors: list[dict[str, Any]] = []
    contract = catboost_spec.get("feature_contract", {})
    policy_contract = policy.get("feature_contract", {})
    for field in ("numeric_features", "categorical_features", "missing_category_token"):
        if policy_contract.get(field) != contract.get(field):
            feature_errors.append({"field": f"feature_contract.{field}", "observed": policy_contract.get(field), "expected": contract.get(field)})
    if feature_errors:
        checks.append(failed("feature_contract_matches_catboost_spec", feature_errors, "same feature order and categorical policy"))
    else:
        checks.append(passed("feature_contract_matches_catboost_spec", policy_contract, "same feature order and categorical policy"))

    output = policy.get("output", {})
    missing_outputs = [
        field
        for field in (
            "report_file",
            "trial_ledger_file",
            "best_trial_trace_file",
            "prediction_file",
            "search_space_audit_file",
            "objective_audit_file",
            "serialized_spec_file",
        )
        if not output.get(field)
    ]
    if missing_outputs:
        checks.append(failed("output_contract_names_all_artifacts", missing_outputs, "all output filenames are declared"))
    else:
        checks.append(passed("output_contract_names_all_artifacts", sorted(output), "all output filenames are declared"))
    return checks


def search_space_grid_size(search_space: dict[str, Any]) -> int:
    if not search_space:
        return 0
    size = 1
    for spec in search_space.values():
        values = spec.get("values") if isinstance(spec, dict) else None
        if not isinstance(values, list) or not values:
            return 0
        size *= len(values)
    return size


def joined_frame(features_path: Path, labels_path: Path, manifest_path: Path) -> pd.DataFrame:
    features = pd.read_csv(features_path)
    labels = pd.read_csv(labels_path)
    manifest = pd.read_csv(manifest_path)
    for frame_name, frame in {"features": features, "labels": labels, "manifest": manifest}.items():
        if "snapshot_id" not in frame.columns:
            raise OptunaTuningAuditError(f"{frame_name} table misses snapshot_id")
        if frame["snapshot_id"].duplicated().any():
            raise OptunaTuningAuditError(f"{frame_name} table contains duplicate snapshot_id")
    frame = features.merge(labels[["snapshot_id", "churned_14d"]], on="snapshot_id", how="left")
    frame = frame.merge(manifest[["snapshot_id", "split", "split_order"]], on="snapshot_id", how="inner")
    frame["target"] = frame["churned_14d"].map(bool_label)
    return frame.sort_values(["split_order", "snapshot_id"]).reset_index(drop=True)


def prepare_features(frame: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    contract = policy["feature_contract"]
    numeric_features = list(contract["numeric_features"])
    categorical_features = list(contract["categorical_features"])
    missing_category_token = contract.get("missing_category_token", "__MISSING__")
    matrix = frame[numeric_features + categorical_features].copy()
    for column in numeric_features:
        matrix[column] = pd.to_numeric(matrix[column], errors="coerce")
    for column in categorical_features:
        matrix[column] = matrix[column].fillna(missing_category_token).replace("", missing_category_token).astype(str)
    return matrix


def split_ids(frame: pd.DataFrame, split: str) -> list[str]:
    return frame.loc[frame["split"] == split, "snapshot_id"].tolist()


def selection_metrics(
    *,
    snapshot_ids: list[str],
    scores: list[float],
    actual: list[int],
    max_actions: int,
    false_positive_cost: float,
    false_negative_cost: float,
    threshold: float | None = None,
) -> dict[str, Any]:
    rows = [
        {"snapshot_id": snapshot_id, "score": float(score), "actual": int(label)}
        for snapshot_id, score, label in zip(snapshot_ids, scores, actual, strict=True)
    ]
    rows = sorted(rows, key=lambda row: (-row["score"], row["snapshot_id"]))
    if threshold is None:
        selected_ids = {row["snapshot_id"] for row in rows[:max_actions]}
    else:
        selected_ids = {row["snapshot_id"] for row in rows if row["score"] >= threshold}
    selected_ordered = [row["snapshot_id"] for row in rows if row["snapshot_id"] in selected_ids]
    fp = sum(1 for row in rows if row["snapshot_id"] in selected_ids and row["actual"] == 0)
    fn = sum(1 for row in rows if row["snapshot_id"] not in selected_ids and row["actual"] == 1)
    tp = sum(1 for row in rows if row["snapshot_id"] in selected_ids and row["actual"] == 1)
    total_cost = rounded(fp * false_positive_cost + fn * false_negative_cost)
    return {
        "action_count": len(selected_ordered),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "total_error_cost": total_cost,
        "selected_ids": ",".join(selected_ordered),
        "false_positive_ids": ",".join(row["snapshot_id"] for row in rows if row["snapshot_id"] in selected_ids and row["actual"] == 0),
        "false_negative_ids": ",".join(row["snapshot_id"] for row in rows if row["snapshot_id"] not in selected_ids and row["actual"] == 1),
    }


def catboost_params_for_trial(policy: dict[str, Any], trial: optuna.trial.Trial) -> dict[str, Any]:
    params = dict(policy["fixed_catboost_params"])
    for name, spec in policy["search_space"].items():
        if spec["type"] != "categorical":
            raise OptunaTuningAuditError(f"Unsupported search-space type for {name}: {spec['type']}")
        params[name] = trial.suggest_categorical(name, spec["values"])
    return params


def fit_model(
    *,
    policy: dict[str, Any],
    frame: pd.DataFrame,
    matrix: pd.DataFrame,
    params: dict[str, Any],
) -> CatBoostClassifier:
    categorical_features = list(policy["feature_contract"]["categorical_features"])
    fit_mask = frame["split"] == policy["fit_split"]
    objective_mask = frame["split"] == policy["objective_split"]
    model = CatBoostClassifier(**params)
    model.fit(
        Pool(matrix.loc[fit_mask], label=frame.loc[fit_mask, "target"].astype(int), cat_features=categorical_features),
        eval_set=Pool(
            matrix.loc[objective_mask],
            label=frame.loc[objective_mask, "target"].astype(int),
            cat_features=categorical_features,
        ),
    )
    return model


def run_study(*, policy: dict[str, Any], frame: pd.DataFrame, matrix: pd.DataFrame) -> tuple[optuna.study.Study, list[dict[str, Any]]]:
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    search_space = {name: spec["values"] for name, spec in policy["search_space"].items()}
    sampler = optuna.samplers.GridSampler(search_space, seed=int(policy["study"]["sampler"]["seed"]))
    pruner = optuna.pruners.NopPruner()
    study = optuna.create_study(
        study_name=policy["study"]["study_name"],
        direction=policy["study"]["direction"],
        sampler=sampler,
        pruner=pruner,
    )
    cost_policy = policy["cost_policy"]
    objective_mask = frame["split"] == policy["objective_split"]
    objective_ids = frame.loc[objective_mask, "snapshot_id"].tolist()
    objective_actual = frame.loc[objective_mask, "target"].astype(int).tolist()

    def objective(trial: optuna.trial.Trial) -> float:
        params = catboost_params_for_trial(policy, trial)
        model = fit_model(policy=policy, frame=frame, matrix=matrix, params=params)
        probabilities = model.predict_proba(
            Pool(matrix.loc[objective_mask], cat_features=policy["feature_contract"]["categorical_features"])
        )[:, 1]
        objective_value = float(log_loss(objective_actual, probabilities, labels=[0, 1]))
        top_k = selection_metrics(
            snapshot_ids=objective_ids,
            scores=probabilities.tolist(),
            actual=objective_actual,
            max_actions=int(cost_policy["max_actions"]),
            false_positive_cost=float(cost_policy["false_positive_cost"]),
            false_negative_cost=float(cost_policy["false_negative_cost"]),
        )
        fixed_threshold = selection_metrics(
            snapshot_ids=objective_ids,
            scores=probabilities.tolist(),
            actual=objective_actual,
            max_actions=int(cost_policy["max_actions"]),
            false_positive_cost=float(cost_policy["false_positive_cost"]),
            false_negative_cost=float(cost_policy["false_negative_cost"]),
            threshold=0.5,
        )
        trial.set_user_attr("fit_split", policy["fit_split"])
        trial.set_user_attr("objective_split", policy["objective_split"])
        trial.set_user_attr("final_holdout_used_for_objective", False)
        trial.set_user_attr("validation_top_k_total_error_cost", top_k["total_error_cost"])
        trial.set_user_attr("validation_top_k_selected_ids", top_k["selected_ids"])
        trial.set_user_attr("validation_top_k_false_negative_ids", top_k["false_negative_ids"])
        trial.set_user_attr("validation_fixed_threshold_0_5_total_error_cost", fixed_threshold["total_error_cost"])
        trial.set_user_attr("tree_count", int(model.tree_count_))
        trial.set_user_attr("best_iteration", model.get_best_iteration())
        return objective_value

    study.optimize(objective, n_trials=int(policy["study"]["n_trials"]))
    return study, trial_ledger(policy=policy, study=study)


def trial_ledger(*, policy: dict[str, Any], study: optuna.study.Study) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in sorted(study.trials, key=lambda item: item.number):
        row = {
            "study_name": policy["study"]["study_name"],
            "trial_number": trial.number,
            "state": trial.state.name,
            "objective_metric": policy["study"]["objective_metric"],
            "objective_value": rounded(trial.value),
            "direction": policy["study"]["direction"],
            "fit_split": trial.user_attrs.get("fit_split"),
            "objective_split": trial.user_attrs.get("objective_split"),
            "final_holdout_used_for_objective": trial.user_attrs.get("final_holdout_used_for_objective"),
            "validation_top_k_total_error_cost": trial.user_attrs.get("validation_top_k_total_error_cost"),
            "validation_top_k_selected_ids": trial.user_attrs.get("validation_top_k_selected_ids"),
            "validation_top_k_false_negative_ids": trial.user_attrs.get("validation_top_k_false_negative_ids"),
            "validation_fixed_threshold_0_5_total_error_cost": trial.user_attrs.get("validation_fixed_threshold_0_5_total_error_cost"),
            "tree_count": trial.user_attrs.get("tree_count"),
            "best_iteration": trial.user_attrs.get("best_iteration"),
            "generated_at": GENERATED_AT,
        }
        for name in policy["search_space"]:
            row[name] = trial.params.get(name)
        rows.append(row)
    best_number = study.best_trial.number
    for row in rows:
        row["is_best_trial"] = row["trial_number"] == best_number
    return rows


def build_predictions(
    *,
    policy: dict[str, Any],
    frame: pd.DataFrame,
    matrix: pd.DataFrame,
    best_params: dict[str, Any],
) -> list[dict[str, Any]]:
    model = fit_model(policy=policy, frame=frame, matrix=matrix, params=best_params)
    probabilities = model.predict_proba(Pool(matrix, cat_features=policy["feature_contract"]["categorical_features"]))[:, 1]
    rows: list[dict[str, Any]] = []
    for row, score in zip(frame.to_dict("records"), probabilities, strict=True):
        split = row["split"]
        rows.append(
            {
                "model_id": policy["tuned_candidate_model_id"],
                "split": split,
                "snapshot_id": row["snapshot_id"],
                "score": rounded(float(score)),
                "actual_label": int(row["target"]),
                "used_for_fit": split == policy["fit_split"],
                "used_for_objective": split == policy["objective_split"],
                "used_for_final_holdout_reporting": split == policy["final_holdout_split"],
                "test_used_for_best_trial_selection": False,
                "generated_at": GENERATED_AT,
            }
        )
    return rows


def build_search_space_audit(policy: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, spec in policy["search_space"].items():
        rows.append(
            {
                "parameter": name,
                "type": spec["type"],
                "values": spec["values"],
                "value_count": len(spec["values"]),
                "declared_before_study": True,
                "hidden_search": False,
            }
        )
    rows.append(
        {
            "parameter": "__grid__",
            "type": "cartesian_product",
            "values": list(policy["search_space"]),
            "value_count": search_space_grid_size(policy["search_space"]),
            "declared_before_study": True,
            "hidden_search": False,
        }
    )
    return rows


def build_objective_audit(policy: dict[str, Any], frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("train", "validation", "test"):
        ids = split_ids(frame, split)
        rows.append(
            {
                "split": split,
                "snapshot_ids": ",".join(ids),
                "row_count": len(ids),
                "used_for_fit": split == policy["fit_split"],
                "used_for_objective": split == policy["objective_split"],
                "used_for_best_trial_selection": split == policy["objective_split"],
                "used_after_selection_for_reporting": split == policy["final_holdout_split"],
                "allowed_role": "fit" if split == policy["fit_split"] else ("objective" if split == policy["objective_split"] else "final_holdout_after_selection"),
            }
        )
    return rows


def build_best_trial_trace(
    *,
    policy: dict[str, Any],
    ledger: list[dict[str, Any]],
    early_report: dict[str, Any],
    cost_report: dict[str, Any],
) -> list[dict[str, Any]]:
    best = next(row for row in ledger if row["is_best_trial"])
    cost_summary = cost_report["summary"]
    return [
        {
            "trace_role": "source_early_stopped_catboost",
            "model_id": policy["source_candidate_model_id"],
            "trial_number": "",
            "validation_logloss": early_report["summary"]["best_validation_logloss"],
            "validation_top_k_total_error_cost": cost_summary["catboost_top_k_total_error_cost"],
            "validation_top_k_selected_ids": cost_summary["catboost_top_k_selected_ids"],
            "depth": 2,
            "learning_rate": 0.2,
            "objective_split": policy["objective_split"],
            "test_used_for_selection": False,
        },
        {
            "trace_role": "best_optuna_trial",
            "model_id": policy["tuned_candidate_model_id"],
            "trial_number": best["trial_number"],
            "validation_logloss": best["objective_value"],
            "validation_top_k_total_error_cost": best["validation_top_k_total_error_cost"],
            "validation_top_k_selected_ids": best["validation_top_k_selected_ids"],
            "depth": best["depth"],
            "learning_rate": best["learning_rate"],
            "objective_split": policy["objective_split"],
            "test_used_for_selection": False,
        },
        {
            "trace_role": "calibrated_phase15_baseline_cost_gate",
            "model_id": policy["baseline_package_id"],
            "trial_number": "",
            "validation_logloss": "",
            "validation_top_k_total_error_cost": cost_summary["baseline_top_k_total_error_cost"],
            "validation_top_k_selected_ids": cost_summary["baseline_top_k_selected_ids"],
            "depth": "",
            "learning_rate": "",
            "objective_split": policy["objective_split"],
            "test_used_for_selection": False,
        },
    ]


def add_result_checks(
    *,
    checks: list[dict[str, Any]],
    policy: dict[str, Any],
    ledger: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    best_trial_trace: list[dict[str, Any]],
    cost_report: dict[str, Any],
) -> None:
    expected_trials = int(policy["study"]["n_trials"])
    complete_count = len([row for row in ledger if row["state"] == "COMPLETE"])
    if len(ledger) == expected_trials and complete_count == expected_trials and len([row for row in ledger if row["is_best_trial"]]) == 1:
        checks.append(passed("trial_ledger_contains_all_trials", {"row_count": len(ledger), "complete_count": complete_count}, {"row_count": expected_trials, "complete_count": expected_trials}))
    else:
        checks.append(failed("trial_ledger_contains_all_trials", {"row_count": len(ledger), "complete_count": complete_count}, {"row_count": expected_trials, "complete_count": expected_trials}))

    if not any(row["final_holdout_used_for_objective"] for row in ledger):
        checks.append(passed("final_holdout_not_used_for_objective", False, False))
    else:
        checks.append(failed("final_holdout_not_used_for_objective", True, False))

    best = next(row for row in ledger if row["is_best_trial"])
    minimum = min(float(row["objective_value"]) for row in ledger)
    if float(best["objective_value"]) == minimum:
        checks.append(passed("best_trial_matches_min_validation_objective", {"best_trial": best["trial_number"], "best_value": best["objective_value"]}, "minimum objective value"))
    else:
        checks.append(failed("best_trial_matches_min_validation_objective", {"best_trial": best["trial_number"], "best_value": best["objective_value"], "minimum": minimum}, "minimum objective value"))

    test_prediction_rows = [row for row in predictions if row["split"] == policy["final_holdout_split"]]
    if test_prediction_rows and not any(row["used_for_objective"] or row["test_used_for_best_trial_selection"] for row in test_prediction_rows):
        checks.append(passed("test_predictions_are_after_selection_only", len(test_prediction_rows), "test rows scored but not used for objective"))
    else:
        checks.append(failed("test_predictions_are_after_selection_only", test_prediction_rows, "test rows scored but not used for objective"))

    if float(best_trial_trace[1]["validation_logloss"]) < float(best_trial_trace[0]["validation_logloss"]):
        checks.append(passed("best_trial_improves_validation_logloss", {"source": best_trial_trace[0]["validation_logloss"], "best": best_trial_trace[1]["validation_logloss"]}, "best Optuna value < source value"))
    else:
        checks.append(failed("best_trial_improves_validation_logloss", {"source": best_trial_trace[0]["validation_logloss"], "best": best_trial_trace[1]["validation_logloss"]}, "best Optuna value < source value", severity="warning"))

    if policy["warning_policy"]["warn_on_tiny_trial_budget"]:
        checks.append(
            failed(
                "tiny_fixed_budget_study_expected",
                {"n_trials": expected_trials, "grid_size": search_space_grid_size(policy["search_space"])},
                "production tuning would use a larger predeclared budget",
                severity="warning",
            )
        )
    if policy["warning_policy"]["warn_if_upstream_candidate_not_promoted"] and cost_report["summary"]["decision_status"] != "promote_catboost_candidate_for_review":
        checks.append(
            failed(
                "upstream_candidate_not_promoted_before_tuning",
                cost_report["summary"]["decision_status"],
                "upstream candidate promoted before tuning",
                severity="warning",
            )
        )
    best_cost = float(best["validation_top_k_total_error_cost"])
    baseline_cost = float(cost_report["summary"]["baseline_top_k_total_error_cost"])
    if policy["warning_policy"]["warn_if_best_trial_cost_not_better_than_baseline_cost"] and best_cost > baseline_cost:
        checks.append(
            failed(
                "best_trial_logloss_improves_but_cost_gate_still_fails",
                {
                    "best_trial_validation_top_k_cost": best_cost,
                    "baseline_validation_top_k_cost": baseline_cost,
                },
                "best trial cost <= baseline cost",
                severity="warning",
            )
        )
    if policy["warning_policy"]["require_no_test_objective_boundary"]:
        checks.append(
            failed(
                "no_test_objective_boundary_visible",
                "objective split is validation; final holdout is scored only after best trial selection",
                "report must not optimize on test",
                severity="warning",
            )
        )


def build_serialized_spec(
    *,
    policy: dict[str, Any],
    ledger: list[dict[str, Any]],
    best_trial_trace: list[dict[str, Any]],
    early_report: dict[str, Any],
    cost_report: dict[str, Any],
) -> dict[str, Any]:
    best = next(row for row in ledger if row["is_best_trial"])
    return {
        "optuna_tuning_audit_id": policy["optuna_tuning_audit_id"],
        "problem_id": policy["problem_id"],
        "source_candidate_model_id": policy["source_candidate_model_id"],
        "tuned_candidate_model_id": policy["tuned_candidate_model_id"],
        "fit_split": policy["fit_split"],
        "objective_split": policy["objective_split"],
        "final_holdout_split": policy["final_holdout_split"],
        "study": policy["study"],
        "search_space": policy["search_space"],
        "fixed_catboost_params": policy["fixed_catboost_params"],
        "best_trial": {
            "trial_number": best["trial_number"],
            "objective_value": best["objective_value"],
            "depth": best["depth"],
            "learning_rate": best["learning_rate"],
            "validation_top_k_total_error_cost": best["validation_top_k_total_error_cost"],
            "validation_top_k_selected_ids": best["validation_top_k_selected_ids"],
        },
        "best_trial_trace": best_trial_trace,
        "upstream_handoff": {
            "early_stopping_audit_id": early_report["summary"]["early_stopping_audit_id"],
            "early_stopping_readiness_status": early_report["summary"]["readiness_status"],
            "cost_sensitive_decision_audit_id": cost_report["summary"]["cost_sensitive_decision_audit_id"],
            "cost_sensitive_readiness_status": cost_report["summary"]["readiness_status"],
            "cost_sensitive_decision_status": cost_report["summary"]["decision_status"],
        },
        "generated_at": GENERATED_AT,
    }


def build_summary(
    *,
    policy: dict[str, Any],
    ledger: list[dict[str, Any]],
    best_trial_trace: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    cost_report: dict[str, Any],
) -> dict[str, Any]:
    best = next(row for row in ledger if row["is_best_trial"])
    errors = blocking_errors(checks)
    return {
        "optuna_tuning_audit_id": policy["optuna_tuning_audit_id"],
        "problem_id": policy["problem_id"],
        "optuna_version": optuna.__version__,
        "catboost_version": catboost.__version__,
        "study_name": policy["study"]["study_name"],
        "sampler": policy["study"]["sampler"]["name"],
        "sampler_seed": policy["study"]["sampler"]["seed"],
        "n_trials": policy["study"]["n_trials"],
        "complete_trial_count": len([row for row in ledger if row["state"] == "COMPLETE"]),
        "fit_split": policy["fit_split"],
        "objective_split": policy["objective_split"],
        "final_holdout_split": policy["final_holdout_split"],
        "test_used_for_objective": any(row["final_holdout_used_for_objective"] for row in ledger),
        "source_validation_logloss": best_trial_trace[0]["validation_logloss"],
        "best_trial_number": best["trial_number"],
        "best_validation_logloss": best["objective_value"],
        "best_depth": best["depth"],
        "best_learning_rate": best["learning_rate"],
        "source_catboost_validation_top_k_cost": cost_report["summary"]["catboost_top_k_total_error_cost"],
        "best_trial_validation_top_k_cost": best["validation_top_k_total_error_cost"],
        "baseline_validation_top_k_cost": cost_report["summary"]["baseline_top_k_total_error_cost"],
        "best_trial_validation_top_k_selected_ids": best["validation_top_k_selected_ids"],
        "objective_improved_vs_source": float(best["objective_value"]) < float(best_trial_trace[0]["validation_logloss"]),
        "cost_gate_still_fails_vs_baseline": float(best["validation_top_k_total_error_cost"]) > float(cost_report["summary"]["baseline_top_k_total_error_cost"]),
        "decision_status": policy["decision_policy"]["outcome_if_valid"] if not errors else "blocked_before_optuna_tuning",
        "blocking_errors": errors,
        "warnings": warning_ids(checks),
        "readiness_status": "blocked_before_optuna_tuning" if errors else policy["decision_policy"]["next_lesson_readiness"],
    }


def empty_invalid_report(file_check: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": False,
        "problem_id": None,
        "summary": {
            "optuna_tuning_audit_id": None,
            "blocking_errors": blocking_errors([file_check]),
            "warnings": [],
            "readiness_status": "blocked_before_optuna_tuning",
        },
        "trial_ledger": [],
        "best_trial_trace": [],
        "predictions": [],
        "search_space_audit": [],
        "objective_audit": [],
        "checks": [file_check],
        "serialized_spec": {},
    }


def run(
    *,
    policy_path: Path = DEFAULT_POLICY_PATH,
    catboost_spec_path: Path = DEFAULT_CATBOOST_SPEC_PATH,
    early_stopping_report_path: Path = DEFAULT_EARLY_STOPPING_REPORT_PATH,
    early_stopping_spec_path: Path = DEFAULT_EARLY_STOPPING_SPEC_PATH,
    cost_report_path: Path = DEFAULT_COST_REPORT_PATH,
    cost_spec_path: Path = DEFAULT_COST_SPEC_PATH,
    features_path: Path = DEFAULT_FEATURES_PATH,
    labels_path: Path = DEFAULT_LABELS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    paths = {
        "policy": policy_path,
        "catboost_spec": catboost_spec_path,
        "early_stopping_report": early_stopping_report_path,
        "early_stopping_spec": early_stopping_spec_path,
        "cost_report": cost_report_path,
        "cost_spec": cost_spec_path,
        "features": features_path,
        "labels": labels_path,
        "manifest": manifest_path,
    }
    file_check = validate_required_files(paths)
    if not file_check["valid"]:
        return empty_invalid_report(file_check)

    policy = read_json(policy_path)
    catboost_spec = read_json(catboost_spec_path)
    early_report = read_json(early_stopping_report_path)
    early_spec = read_json(early_stopping_spec_path)
    cost_report = read_json(cost_report_path)
    cost_spec = read_json(cost_spec_path)
    checks = [file_check]
    checks.extend(
        validate_policy(
            policy=policy,
            catboost_spec=catboost_spec,
            early_report=early_report,
            early_spec=early_spec,
            cost_report=cost_report,
            cost_spec=cost_spec,
        )
    )
    if blocking_errors(checks):
        return {
            "valid": False,
            "problem_id": policy.get("problem_id"),
            "summary": {
                "optuna_tuning_audit_id": policy.get("optuna_tuning_audit_id"),
                "blocking_errors": blocking_errors(checks),
                "warnings": warning_ids(checks),
                "readiness_status": "blocked_before_optuna_tuning",
            },
            "trial_ledger": [],
            "best_trial_trace": [],
            "predictions": [],
            "search_space_audit": build_search_space_audit(policy) if "search_space" in policy else [],
            "objective_audit": [],
            "checks": checks,
            "serialized_spec": {},
        }

    frame = joined_frame(features_path, labels_path, manifest_path)
    matrix = prepare_features(frame, policy)
    study, ledger = run_study(policy=policy, frame=frame, matrix=matrix)
    best_params = dict(policy["fixed_catboost_params"])
    best_params.update(study.best_trial.params)
    predictions = build_predictions(policy=policy, frame=frame, matrix=matrix, best_params=best_params)
    search_space_audit = build_search_space_audit(policy)
    objective_audit = build_objective_audit(policy, frame)
    best_trial_trace = build_best_trial_trace(
        policy=policy,
        ledger=ledger,
        early_report=early_report,
        cost_report=cost_report,
    )
    add_result_checks(
        checks=checks,
        policy=policy,
        ledger=ledger,
        predictions=predictions,
        best_trial_trace=best_trial_trace,
        cost_report=cost_report,
    )
    serialized_spec = build_serialized_spec(
        policy=policy,
        ledger=ledger,
        best_trial_trace=best_trial_trace,
        early_report=early_report,
        cost_report=cost_report,
    )
    summary = build_summary(
        policy=policy,
        ledger=ledger,
        best_trial_trace=best_trial_trace,
        checks=checks,
        cost_report=cost_report,
    )
    return {
        "valid": not blocking_errors(checks),
        "problem_id": policy["problem_id"],
        "summary": summary,
        "trial_ledger": ledger,
        "best_trial_trace": best_trial_trace,
        "predictions": predictions,
        "search_space_audit": search_space_audit,
        "objective_audit": objective_audit,
        "checks": checks,
        "serialized_spec": serialized_spec,
    }


def write_outputs(result: dict[str, Any], output_root: Path, output_spec: dict[str, str]) -> None:
    write_json(output_root / output_spec["report_file"], {key: value for key, value in result.items() if key != "serialized_spec"})
    write_json(output_root / output_spec["serialized_spec_file"], result["serialized_spec"])
    write_csv(
        output_root / output_spec["trial_ledger_file"],
        result["trial_ledger"],
        [
            "study_name",
            "trial_number",
            "state",
            "is_best_trial",
            "objective_metric",
            "objective_value",
            "direction",
            "depth",
            "learning_rate",
            "fit_split",
            "objective_split",
            "final_holdout_used_for_objective",
            "validation_top_k_total_error_cost",
            "validation_top_k_selected_ids",
            "validation_top_k_false_negative_ids",
            "validation_fixed_threshold_0_5_total_error_cost",
            "tree_count",
            "best_iteration",
            "generated_at",
        ],
    )
    write_csv(
        output_root / output_spec["best_trial_trace_file"],
        result["best_trial_trace"],
        [
            "trace_role",
            "model_id",
            "trial_number",
            "validation_logloss",
            "validation_top_k_total_error_cost",
            "validation_top_k_selected_ids",
            "depth",
            "learning_rate",
            "objective_split",
            "test_used_for_selection",
        ],
    )
    write_csv(
        output_root / output_spec["prediction_file"],
        result["predictions"],
        [
            "model_id",
            "split",
            "snapshot_id",
            "score",
            "actual_label",
            "used_for_fit",
            "used_for_objective",
            "used_for_final_holdout_reporting",
            "test_used_for_best_trial_selection",
            "generated_at",
        ],
    )
    write_csv(
        output_root / output_spec["search_space_audit_file"],
        result["search_space_audit"],
        ["parameter", "type", "values", "value_count", "declared_before_study", "hidden_search"],
    )
    write_csv(
        output_root / output_spec["objective_audit_file"],
        result["objective_audit"],
        [
            "split",
            "snapshot_ids",
            "row_count",
            "used_for_fit",
            "used_for_objective",
            "used_for_best_trial_selection",
            "used_after_selection_for_reporting",
            "allowed_role",
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and audit a fixed-budget Optuna study for the CatBoost candidate.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--catboost-spec", type=Path, default=DEFAULT_CATBOOST_SPEC_PATH)
    parser.add_argument("--early-stopping-report", type=Path, default=DEFAULT_EARLY_STOPPING_REPORT_PATH)
    parser.add_argument("--early-stopping-spec", type=Path, default=DEFAULT_EARLY_STOPPING_SPEC_PATH)
    parser.add_argument("--cost-report", type=Path, default=DEFAULT_COST_REPORT_PATH)
    parser.add_argument("--cost-spec", type=Path, default=DEFAULT_COST_SPEC_PATH)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES_PATH)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output-root", type=Path, default=LESSON_ROOT / "outputs")
    args = parser.parse_args()

    result = run(
        policy_path=args.policy,
        catboost_spec_path=args.catboost_spec,
        early_stopping_report_path=args.early_stopping_report,
        early_stopping_spec_path=args.early_stopping_spec,
        cost_report_path=args.cost_report,
        cost_spec_path=args.cost_spec,
        features_path=args.features,
        labels_path=args.labels,
        manifest_path=args.manifest,
    )
    output_spec = read_json(args.policy)["output"] if args.policy.is_file() else {
        "report_file": "optuna_tuning_report.json",
        "trial_ledger_file": "optuna_trial_ledger.csv",
        "best_trial_trace_file": "optuna_best_trial_trace.csv",
        "prediction_file": "optuna_tuned_predictions.csv",
        "search_space_audit_file": "optuna_search_space_audit.csv",
        "objective_audit_file": "optuna_objective_audit.csv",
        "serialized_spec_file": "optuna_tuning_serialized_spec.json",
    }
    write_outputs(result, args.output_root, output_spec)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
