from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OPTUNA_OUTPUT_ROOT = PHASE_ROOT / "09-optuna" / "outputs"

DEFAULT_POLICY_PATH = DATA_ROOT / "mlflow_tracking_policy_spec.json"
DEFAULT_OPTUNA_REPORT_PATH = OPTUNA_OUTPUT_ROOT / "optuna_tuning_report.json"
DEFAULT_OPTUNA_SPEC_PATH = OPTUNA_OUTPUT_ROOT / "optuna_tuning_serialized_spec.json"
DEFAULT_OPTUNA_LEDGER_PATH = OPTUNA_OUTPUT_ROOT / "optuna_trial_ledger.csv"
DEFAULT_OPTUNA_TRACE_PATH = OPTUNA_OUTPUT_ROOT / "optuna_best_trial_trace.csv"
DEFAULT_OPTUNA_PREDICTIONS_PATH = OPTUNA_OUTPUT_ROOT / "optuna_tuned_predictions.csv"

GENERATED_AT = "2026-07-06T12:15:00+03:00"


class MLflowLedgerExportError(ValueError):
    """Raised when the MLflow ledger inputs cannot be parsed."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def write_json(path: Path, value: Any) -> None:
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def validate_policy(policy: dict[str, Any], optuna_report: dict[str, Any], optuna_spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    required = {
        "mlflow_tracking_audit_id",
        "problem_id",
        "baseline_package_id",
        "source_optuna_tuning_audit_id",
        "experiment",
        "tracking_scope",
        "required_common_tags",
        "run_plan",
        "required_params",
        "required_metrics",
        "required_artifacts",
        "warning_policy",
        "decision_policy",
        "output",
    }
    missing = sorted(required - set(policy))
    if missing:
        checks.append(failed("mlflow_policy_has_required_fields", missing, "no missing fields"))
    else:
        checks.append(passed("mlflow_policy_has_required_fields", sorted(required), "required policy fields"))

    handoff_errors: list[dict[str, Any]] = []
    if policy.get("problem_id") != optuna_spec.get("problem_id"):
        handoff_errors.append({"field": "problem_id", "observed": policy.get("problem_id"), "expected": optuna_spec.get("problem_id")})
    if policy.get("source_optuna_tuning_audit_id") != optuna_spec.get("optuna_tuning_audit_id"):
        handoff_errors.append(
            {
                "field": "source_optuna_tuning_audit_id",
                "observed": policy.get("source_optuna_tuning_audit_id"),
                "expected": optuna_spec.get("optuna_tuning_audit_id"),
            }
        )
    if policy.get("baseline_package_id") != optuna_report.get("summary", {}).get("problem_id") and policy.get("baseline_package_id") != "trial-churn-ml-baseline-package-v0":
        handoff_errors.append({"field": "baseline_package_id", "observed": policy.get("baseline_package_id"), "expected": "trial-churn-ml-baseline-package-v0"})
    if optuna_report.get("valid") is not True:
        handoff_errors.append({"field": "optuna_report.valid", "observed": optuna_report.get("valid"), "expected": True})
    if optuna_report.get("summary", {}).get("readiness_status") != "ready_for_mlflow_lesson":
        handoff_errors.append(
            {
                "field": "optuna_report.summary.readiness_status",
                "observed": optuna_report.get("summary", {}).get("readiness_status"),
                "expected": "ready_for_mlflow_lesson",
            }
        )
    if handoff_errors:
        checks.append(failed("mlflow_policy_matches_optuna_handoff", handoff_errors, "valid Optuna handoff ready for MLflow"))
    else:
        checks.append(
            passed(
                "mlflow_policy_matches_optuna_handoff",
                {
                    "mlflow_tracking_audit_id": policy["mlflow_tracking_audit_id"],
                    "optuna_tuning_audit_id": policy["source_optuna_tuning_audit_id"],
                    "readiness": optuna_report["summary"]["readiness_status"],
                },
                "valid Optuna handoff ready for MLflow",
            )
        )

    experiment = policy.get("experiment", {})
    if experiment.get("tracking_backend") == "local_file_store" and experiment.get("tracking_package") == "mlflow-skinny":
        checks.append(passed("tracking_backend_is_local_mlflow_file_store", experiment, "local mlflow-skinny tracking store"))
    else:
        checks.append(failed("tracking_backend_is_local_mlflow_file_store", experiment, "local mlflow-skinny tracking store"))

    scope = policy.get("tracking_scope", {})
    forbidden_enabled = [name for name in ("registry", "remote_tracking_server", "serving") if scope.get(name) is not False]
    if forbidden_enabled:
        checks.append(failed("tracking_scope_excludes_registry_and_serving", forbidden_enabled, "registry, remote tracking and serving are false"))
    else:
        checks.append(passed("tracking_scope_excludes_registry_and_serving", scope, "registry, remote tracking and serving are false"))

    run_aliases = [run.get("run_alias") for run in policy.get("run_plan", [])]
    required_aliases = ["source_early_stopped_catboost", "best_optuna_trial", "phase15_baseline_cost_gate"]
    if run_aliases == required_aliases:
        checks.append(passed("run_plan_declares_expected_tracking_units", run_aliases, required_aliases))
    else:
        checks.append(failed("run_plan_declares_expected_tracking_units", run_aliases, required_aliases))

    output = policy.get("output", {})
    output_fields = {
        "report_file",
        "run_table_file",
        "artifact_inventory_file",
        "metric_history_file",
        "reproducibility_checks_file",
        "model_metadata_file",
        "serialized_spec_file",
    }
    missing_outputs = sorted(field for field in output_fields if not output.get(field))
    if missing_outputs:
        checks.append(failed("output_contract_names_all_artifacts", missing_outputs, "all output filenames are declared"))
    else:
        checks.append(passed("output_contract_names_all_artifacts", sorted(output), "all output filenames are declared"))
    return checks


def run_definitions(policy: dict[str, Any], optuna_report: dict[str, Any], optuna_spec: dict[str, Any]) -> list[dict[str, Any]]:
    summary = optuna_report["summary"]
    best = optuna_spec["best_trial"]
    fixed = optuna_spec["fixed_catboost_params"]
    common_tags = {
        "mlflow_tracking_audit_id": policy["mlflow_tracking_audit_id"],
        "problem_id": policy["problem_id"],
        "source_package_id": policy["baseline_package_id"],
        "optuna_tuning_audit_id": policy["source_optuna_tuning_audit_id"],
        "decision_status": summary["decision_status"],
        "readiness_status": policy["decision_policy"]["next_lesson_readiness"],
        "generated_at": GENERATED_AT,
    }
    return [
        {
            "run_alias": "source_early_stopped_catboost",
            "run_name": "01_source_early_stopped_catboost",
            "run_role": "source_candidate",
            "model_id": optuna_spec["source_candidate_model_id"],
            "candidate_role": "source_before_tuning",
            "params": {
                "model_id": optuna_spec["source_candidate_model_id"],
                "model_family": "catboost",
                "depth": 2,
                "learning_rate": 0.2,
                "random_seed": fixed["random_seed"],
            },
            "metrics": {
                "validation_logloss": summary["source_validation_logloss"],
                "validation_top_k_total_error_cost": summary["source_catboost_validation_top_k_cost"],
                "baseline_validation_top_k_cost": summary["baseline_validation_top_k_cost"],
                "test_used_for_selection": 0.0,
            },
            "tags": common_tags | {"candidate_role": "source_before_tuning"},
            "artifact_sources": [
                {"source_path": DEFAULT_OPTUNA_TRACE_PATH, "artifact_path": "upstream"},
            ],
        },
        {
            "run_alias": "best_optuna_trial",
            "run_name": "02_best_optuna_trial",
            "run_role": "tuned_candidate",
            "model_id": optuna_spec["tuned_candidate_model_id"],
            "candidate_role": "best_validation_objective_trial",
            "params": {
                "model_id": optuna_spec["tuned_candidate_model_id"],
                "model_family": "catboost",
                "depth": best["depth"],
                "learning_rate": best["learning_rate"],
                "random_seed": fixed["random_seed"],
                "optuna_trial_number": best["trial_number"],
            },
            "metrics": {
                "validation_logloss": best["objective_value"],
                "validation_top_k_total_error_cost": best["validation_top_k_total_error_cost"],
                "baseline_validation_top_k_cost": summary["baseline_validation_top_k_cost"],
                "objective_improved_vs_source": 1.0 if summary["objective_improved_vs_source"] else 0.0,
                "cost_gate_still_fails_vs_baseline": 1.0 if summary["cost_gate_still_fails_vs_baseline"] else 0.0,
                "test_used_for_selection": 0.0,
            },
            "tags": common_tags | {"candidate_role": "best_validation_objective_trial"},
            "artifact_sources": [
                {"source_path": DEFAULT_OPTUNA_SPEC_PATH, "artifact_path": "upstream"},
                {"source_path": DEFAULT_OPTUNA_LEDGER_PATH, "artifact_path": "upstream"},
                {"source_path": DEFAULT_OPTUNA_PREDICTIONS_PATH, "artifact_path": "upstream"},
            ],
        },
        {
            "run_alias": "phase15_baseline_cost_gate",
            "run_name": "03_phase15_baseline_cost_gate",
            "run_role": "baseline_gate",
            "model_id": policy["baseline_package_id"],
            "candidate_role": "calibrated_baseline_gate",
            "params": {
                "model_id": policy["baseline_package_id"],
                "model_family": "sklearn_pipeline_package",
                "baseline_package_id": policy["baseline_package_id"],
            },
            "metrics": {
                "validation_top_k_total_error_cost": summary["baseline_validation_top_k_cost"],
                "test_used_for_selection": 0.0,
            },
            "tags": common_tags | {"candidate_role": "calibrated_baseline_gate"},
            "artifact_sources": [
                {"source_path": DEFAULT_OPTUNA_TRACE_PATH, "artifact_path": "upstream"},
            ],
        },
    ]


def model_metadata_for_run(run_def: dict[str, Any], optuna_report: dict[str, Any]) -> dict[str, Any]:
    summary = optuna_report["summary"]
    return {
        "run_alias": run_def["run_alias"],
        "run_role": run_def["run_role"],
        "model_id": run_def["model_id"],
        "candidate_role": run_def["candidate_role"],
        "params": run_def["params"],
        "metrics": run_def["metrics"],
        "source_package_id": run_def["tags"]["source_package_id"],
        "upstream_optuna_tuning_audit_id": summary["optuna_tuning_audit_id"],
        "decision_status": summary["decision_status"],
        "known_warnings": summary["warnings"],
        "generated_at": GENERATED_AT,
    }


def log_runs_to_mlflow(
    *,
    policy: dict[str, Any],
    optuna_report: dict[str, Any],
    optuna_spec: dict[str, Any],
    tracking_root: Path,
    metadata_root: Path,
) -> tuple[MlflowClient, str, list[dict[str, Any]], list[dict[str, Any]]]:
    tracking_root.mkdir(parents=True, exist_ok=True)
    metadata_root.mkdir(parents=True, exist_ok=True)
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    tracking_uri = tracking_root.resolve().as_uri()
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment_id = client.create_experiment(policy["experiment"]["name"])
    definitions = run_definitions(policy, optuna_report, optuna_spec)
    model_metadata_rows: list[dict[str, Any]] = []
    logged_runs: list[dict[str, Any]] = []

    for run_def in definitions:
        model_metadata = model_metadata_for_run(run_def, optuna_report)
        metadata_path = metadata_root / f"{run_def['run_alias']}_model_metadata.json"
        write_json(metadata_path, model_metadata)
        artifact_sources = list(run_def["artifact_sources"])
        artifact_sources.append({"source_path": metadata_path, "artifact_path": "model_metadata"})
        with mlflow.start_run(experiment_id=experiment_id, run_name=run_def["run_name"]) as active_run:
            mlflow.set_tags(run_def["tags"])
            mlflow.log_params({key: str(value) for key, value in run_def["params"].items()})
            mlflow.log_metrics({key: float(value) for key, value in run_def["metrics"].items()})
            for artifact in artifact_sources:
                mlflow.log_artifact(str(artifact["source_path"]), artifact_path=artifact["artifact_path"])
        logged_runs.append(
            {
                "run_alias": run_def["run_alias"],
                "run_name": run_def["run_name"],
                "run_role": run_def["run_role"],
                "model_id": run_def["model_id"],
                "candidate_role": run_def["candidate_role"],
                "run_id": active_run.info.run_id,
                "experiment_id": experiment_id,
                "params": run_def["params"],
                "metrics": run_def["metrics"],
                "tags": run_def["tags"],
                "artifact_sources": artifact_sources,
            }
        )
        model_metadata_rows.append(model_metadata)
    return client, experiment_id, logged_runs, model_metadata_rows


def list_artifacts_recursive(client: MlflowClient, run_id: str, path: str | None = None) -> list[str]:
    paths: list[str] = []
    for item in client.list_artifacts(run_id, path):
        if item.is_dir:
            paths.extend(list_artifacts_recursive(client, run_id, item.path))
        else:
            paths.append(item.path)
    return sorted(paths)


def build_run_table(client: MlflowClient, experiment_id: str, logged_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_run_id = {run.info.run_id: run for run in client.search_runs([experiment_id], order_by=["attributes.start_time ASC"])}
    for logged in logged_runs:
        run = by_run_id[logged["run_id"]]
        metrics = run.data.metrics
        params = run.data.params
        tags = run.data.tags
        rows.append(
            {
                "experiment_name": tags.get("mlflow.runName", logged["run_name"]),
                "run_alias": logged["run_alias"],
                "run_name": logged["run_name"],
                "run_role": logged["run_role"],
                "candidate_role": logged["candidate_role"],
                "model_id": logged["model_id"],
                "run_id_present": bool(run.info.run_id),
                "run_id_length": len(run.info.run_id),
                "raw_run_id_exported": False,
                "source_package_id": tags.get("source_package_id"),
                "optuna_tuning_audit_id": tags.get("optuna_tuning_audit_id"),
                "decision_status": tags.get("decision_status"),
                "readiness_status": tags.get("readiness_status"),
                "depth": params.get("depth"),
                "learning_rate": params.get("learning_rate"),
                "optuna_trial_number": params.get("optuna_trial_number"),
                "validation_logloss": rounded(metrics.get("validation_logloss")) if "validation_logloss" in metrics else None,
                "validation_top_k_total_error_cost": rounded(metrics.get("validation_top_k_total_error_cost")) if "validation_top_k_total_error_cost" in metrics else None,
                "baseline_validation_top_k_cost": rounded(metrics.get("baseline_validation_top_k_cost")) if "baseline_validation_top_k_cost" in metrics else None,
                "objective_improved_vs_source": rounded(metrics.get("objective_improved_vs_source")) if "objective_improved_vs_source" in metrics else None,
                "cost_gate_still_fails_vs_baseline": rounded(metrics.get("cost_gate_still_fails_vs_baseline")) if "cost_gate_still_fails_vs_baseline" in metrics else None,
                "artifact_count": len(list_artifacts_recursive(client, run.info.run_id)),
                "generated_at": GENERATED_AT,
            }
        )
    return rows


def artifact_inventory(client: MlflowClient, logged_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for logged in logged_runs:
        logged_paths = set(list_artifacts_recursive(client, logged["run_id"]))
        for artifact in logged["artifact_sources"]:
            source_path = Path(artifact["source_path"])
            artifact_path = f"{artifact['artifact_path']}/{source_path.name}"
            rows.append(
                {
                    "run_alias": logged["run_alias"],
                    "run_role": logged["run_role"],
                    "artifact_path": artifact_path,
                    "logged_to_mlflow": artifact_path in logged_paths,
                    "source_file": str(source_path.relative_to(REPO_ROOT)) if source_path.is_relative_to(REPO_ROOT) else source_path.name,
                    "source_file_exists": source_path.is_file(),
                    "source_size_bytes": source_path.stat().st_size if source_path.is_file() else None,
                    "source_sha256": sha256_file(source_path) if source_path.is_file() else "",
                    "generated_at": GENERATED_AT,
                }
            )
    return rows


def metric_history(client: MlflowClient, logged_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for logged in logged_runs:
        run = client.get_run(logged["run_id"])
        for metric_name in sorted(run.data.metrics):
            history = client.get_metric_history(logged["run_id"], metric_name)
            for point in history:
                rows.append(
                    {
                        "run_alias": logged["run_alias"],
                        "metric_name": metric_name,
                        "metric_value": rounded(point.value),
                        "metric_step": point.step,
                        "logged_once": len(history) == 1,
                        "generated_at": GENERATED_AT,
                    }
                )
    return sorted(rows, key=lambda row: (row["run_alias"], row["metric_name"], row["metric_step"]))


def add_mlflow_result_checks(
    *,
    checks: list[dict[str, Any]],
    policy: dict[str, Any],
    run_table: list[dict[str, Any]],
    artifact_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    logged_runs: list[dict[str, Any]],
) -> None:
    aliases = [row["run_alias"] for row in run_table]
    expected_aliases = [run["run_alias"] for run in policy["run_plan"]]
    if aliases == expected_aliases:
        checks.append(passed("required_mlflow_runs_exported", aliases, expected_aliases))
    else:
        checks.append(failed("required_mlflow_runs_exported", aliases, expected_aliases))

    if all(row["run_id_present"] and not row["raw_run_id_exported"] for row in run_table):
        checks.append(passed("run_table_omits_raw_run_ids", {"run_count": len(run_table)}, "run ids exist in MLflow but are not exported"))
    else:
        checks.append(failed("run_table_omits_raw_run_ids", run_table, "run ids exist in MLflow but are not exported"))

    missing_tags: list[dict[str, Any]] = []
    for logged in logged_runs:
        tag_keys = set(logged["tags"])
        for tag in policy["required_common_tags"]:
            if tag not in tag_keys:
                missing_tags.append({"run_alias": logged["run_alias"], "tag": tag})
    if missing_tags:
        checks.append(failed("required_tags_logged", missing_tags, "all required common tags"))
    else:
        checks.append(passed("required_tags_logged", policy["required_common_tags"], "all required common tags"))

    missing_params: list[dict[str, Any]] = []
    for logged in logged_runs:
        param_keys = set(logged["params"])
        for param in policy["required_params"][logged["run_alias"]]:
            if param not in param_keys:
                missing_params.append({"run_alias": logged["run_alias"], "param": param})
    if missing_params:
        checks.append(failed("required_params_logged", missing_params, "all required params by run role"))
    else:
        checks.append(passed("required_params_logged", sorted(policy["required_params"]), "all required params by run role"))

    missing_metrics: list[dict[str, Any]] = []
    metric_pairs = {(row["run_alias"], row["metric_name"]) for row in metric_rows}
    for run_alias, metrics in policy["required_metrics"].items():
        for metric in metrics:
            if (run_alias, metric) not in metric_pairs:
                missing_metrics.append({"run_alias": run_alias, "metric": metric})
    if missing_metrics:
        checks.append(failed("required_metrics_logged", missing_metrics, "all required metrics by run role"))
    else:
        checks.append(passed("required_metrics_logged", sorted(policy["required_metrics"]), "all required metrics by run role"))

    missing_artifacts: list[dict[str, Any]] = []
    artifact_pairs = {(row["run_alias"], row["artifact_path"]) for row in artifact_rows if row["logged_to_mlflow"]}
    for run_alias, paths in policy["required_artifacts"].items():
        for path in paths:
            if (run_alias, path) not in artifact_pairs:
                missing_artifacts.append({"run_alias": run_alias, "artifact_path": path})
    if missing_artifacts:
        checks.append(failed("required_artifacts_logged", missing_artifacts, "all required artifacts by run role"))
    else:
        checks.append(passed("required_artifacts_logged", sorted(policy["required_artifacts"]), "all required artifacts by run role"))

    if all(row["source_package_id"] == policy["baseline_package_id"] for row in run_table):
        checks.append(passed("source_package_lineage_logged", policy["baseline_package_id"], "baseline package id logged on every run"))
    else:
        checks.append(failed("source_package_lineage_logged", run_table, "baseline package id logged on every run"))

    if policy["warning_policy"]["warn_if_cost_gate_still_fails"]:
        best = next(row for row in run_table if row["run_alias"] == "best_optuna_trial")
        if best["cost_gate_still_fails_vs_baseline"] == 1.0:
            checks.append(
                failed(
                    "mlflow_ledger_tracks_candidate_with_failed_cost_gate",
                    {"best_trial_cost": best["validation_top_k_total_error_cost"], "baseline_cost": best["baseline_validation_top_k_cost"]},
                    "MLflow records limitation instead of promotion claim",
                    severity="warning",
                )
            )
    if policy["warning_policy"]["warn_if_tracking_is_local_only"]:
        checks.append(
            failed(
                "local_tracking_store_not_registry",
                policy["experiment"]["tracking_backend"],
                "local file store is a lesson boundary, not production registry",
                severity="warning",
            )
        )
    if policy["warning_policy"]["warn_if_full_mlflow_package_conflicts_with_pandas3"]:
        checks.append(
            failed(
                "mlflow_skinny_used_due_to_pandas3_boundary",
                {"package": policy["experiment"]["tracking_package"], "reason": "full mlflow currently pins pandas<3"},
                "tracking API is enough for this lesson",
                severity="warning",
            )
        )


def build_summary(policy: dict[str, Any], checks: list[dict[str, Any]], run_table: list[dict[str, Any]]) -> dict[str, Any]:
    errors = blocking_errors(checks)
    best = next((row for row in run_table if row["run_alias"] == "best_optuna_trial"), {})
    return {
        "mlflow_tracking_audit_id": policy.get("mlflow_tracking_audit_id"),
        "problem_id": policy.get("problem_id"),
        "mlflow_version": mlflow.__version__,
        "tracking_package": policy.get("experiment", {}).get("tracking_package"),
        "experiment_name": policy.get("experiment", {}).get("name"),
        "tracking_backend": policy.get("experiment", {}).get("tracking_backend"),
        "run_count": len(run_table),
        "raw_run_ids_exported": any(row.get("raw_run_id_exported") for row in run_table),
        "best_run_alias": best.get("run_alias"),
        "best_validation_logloss": best.get("validation_logloss"),
        "best_trial_validation_top_k_cost": best.get("validation_top_k_total_error_cost"),
        "baseline_validation_top_k_cost": best.get("baseline_validation_top_k_cost"),
        "source_package_id": policy.get("baseline_package_id"),
        "optuna_tuning_audit_id": policy.get("source_optuna_tuning_audit_id"),
        "decision_status": policy.get("decision_policy", {}).get("outcome_if_valid") if not errors else "blocked_before_mlflow_tracking",
        "blocking_errors": errors,
        "warnings": warning_ids(checks),
        "readiness_status": "blocked_before_mlflow_tracking" if errors else policy.get("decision_policy", {}).get("next_lesson_readiness"),
    }


def build_serialized_spec(
    policy: dict[str, Any],
    run_table: list[dict[str, Any]],
    artifact_rows: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "mlflow_tracking_audit_id": policy["mlflow_tracking_audit_id"],
        "problem_id": policy["problem_id"],
        "experiment": policy["experiment"],
        "tracking_scope": policy["tracking_scope"],
        "source_package_id": policy["baseline_package_id"],
        "optuna_tuning_audit_id": policy["source_optuna_tuning_audit_id"],
        "run_aliases": [row["run_alias"] for row in run_table],
        "run_table": run_table,
        "artifact_count": len(artifact_rows),
        "required_checks": [check for check in checks if check["severity"] == "error"],
        "decision_policy": policy["decision_policy"],
        "generated_at": GENERATED_AT,
    }


def empty_invalid_report(file_check: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": False,
        "problem_id": None,
        "summary": {
            "mlflow_tracking_audit_id": None,
            "blocking_errors": blocking_errors([file_check]),
            "warnings": [],
            "readiness_status": "blocked_before_mlflow_tracking",
        },
        "run_table": [],
        "artifact_inventory": [],
        "metric_history": [],
        "reproducibility_checks": [file_check],
        "model_metadata": [],
        "serialized_spec": {},
    }


def run(
    *,
    policy_path: Path = DEFAULT_POLICY_PATH,
    optuna_report_path: Path = DEFAULT_OPTUNA_REPORT_PATH,
    optuna_spec_path: Path = DEFAULT_OPTUNA_SPEC_PATH,
    optuna_ledger_path: Path = DEFAULT_OPTUNA_LEDGER_PATH,
    optuna_trace_path: Path = DEFAULT_OPTUNA_TRACE_PATH,
    optuna_predictions_path: Path = DEFAULT_OPTUNA_PREDICTIONS_PATH,
    tracking_root: Path | None = None,
) -> dict[str, Any]:
    paths = {
        "policy": policy_path,
        "optuna_report": optuna_report_path,
        "optuna_serialized_spec": optuna_spec_path,
        "optuna_trial_ledger": optuna_ledger_path,
        "optuna_best_trial_trace": optuna_trace_path,
        "optuna_tuned_predictions": optuna_predictions_path,
    }
    file_check = validate_required_files(paths)
    if not file_check["valid"]:
        return empty_invalid_report(file_check)

    policy = read_json(policy_path)
    optuna_report = read_json(optuna_report_path)
    optuna_spec = read_json(optuna_spec_path)
    checks = [file_check]
    checks.extend(validate_policy(policy, optuna_report, optuna_spec))
    if blocking_errors(checks):
        summary = build_summary(policy, checks, [])
        return {
            "valid": False,
            "problem_id": policy.get("problem_id"),
            "summary": summary,
            "run_table": [],
            "artifact_inventory": [],
            "metric_history": [],
            "reproducibility_checks": checks,
            "model_metadata": [],
            "serialized_spec": {},
        }

    if tracking_root is None:
        with tempfile.TemporaryDirectory(prefix="mlflow-lesson-") as directory:
            return run_with_tracking_root(
                policy=policy,
                optuna_report=optuna_report,
                optuna_spec=optuna_spec,
                checks=checks,
                tracking_root=Path(directory) / "mlruns",
                metadata_root=Path(directory) / "metadata",
            )
    return run_with_tracking_root(
        policy=policy,
        optuna_report=optuna_report,
        optuna_spec=optuna_spec,
        checks=checks,
        tracking_root=tracking_root,
        metadata_root=tracking_root / "_metadata_sources",
    )


def run_with_tracking_root(
    *,
    policy: dict[str, Any],
    optuna_report: dict[str, Any],
    optuna_spec: dict[str, Any],
    checks: list[dict[str, Any]],
    tracking_root: Path,
    metadata_root: Path,
) -> dict[str, Any]:
    client, experiment_id, logged_runs, model_metadata_rows = log_runs_to_mlflow(
        policy=policy,
        optuna_report=optuna_report,
        optuna_spec=optuna_spec,
        tracking_root=tracking_root,
        metadata_root=metadata_root,
    )
    run_table = build_run_table(client, experiment_id, logged_runs)
    artifact_rows = artifact_inventory(client, logged_runs)
    metric_rows = metric_history(client, logged_runs)
    add_mlflow_result_checks(
        checks=checks,
        policy=policy,
        run_table=run_table,
        artifact_rows=artifact_rows,
        metric_rows=metric_rows,
        logged_runs=logged_runs,
    )
    summary = build_summary(policy, checks, run_table)
    serialized_spec = build_serialized_spec(policy, run_table, artifact_rows, checks)
    return {
        "valid": not blocking_errors(checks),
        "problem_id": policy["problem_id"],
        "summary": summary,
        "run_table": run_table,
        "artifact_inventory": artifact_rows,
        "metric_history": metric_rows,
        "reproducibility_checks": checks,
        "model_metadata": model_metadata_rows,
        "serialized_spec": serialized_spec,
    }


def write_outputs(result: dict[str, Any], output_root: Path, output_spec: dict[str, str]) -> None:
    write_json(output_root / output_spec["report_file"], {key: value for key, value in result.items() if key != "serialized_spec"})
    write_json(output_root / output_spec["model_metadata_file"], result["model_metadata"])
    write_json(output_root / output_spec["serialized_spec_file"], result["serialized_spec"])
    write_csv(
        output_root / output_spec["run_table_file"],
        result["run_table"],
        [
            "experiment_name",
            "run_alias",
            "run_name",
            "run_role",
            "candidate_role",
            "model_id",
            "run_id_present",
            "run_id_length",
            "raw_run_id_exported",
            "source_package_id",
            "optuna_tuning_audit_id",
            "decision_status",
            "readiness_status",
            "depth",
            "learning_rate",
            "optuna_trial_number",
            "validation_logloss",
            "validation_top_k_total_error_cost",
            "baseline_validation_top_k_cost",
            "objective_improved_vs_source",
            "cost_gate_still_fails_vs_baseline",
            "artifact_count",
            "generated_at",
        ],
    )
    write_csv(
        output_root / output_spec["artifact_inventory_file"],
        result["artifact_inventory"],
        [
            "run_alias",
            "run_role",
            "artifact_path",
            "logged_to_mlflow",
            "source_file",
            "source_file_exists",
            "source_size_bytes",
            "source_sha256",
            "generated_at",
        ],
    )
    write_csv(
        output_root / output_spec["metric_history_file"],
        result["metric_history"],
        ["run_alias", "metric_name", "metric_value", "metric_step", "logged_once", "generated_at"],
    )
    write_csv(
        output_root / output_spec["reproducibility_checks_file"],
        result["reproducibility_checks"],
        ["id", "severity", "valid", "observed", "expected", "sample"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a deterministic ledger from local MLflow tracking runs.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--optuna-report", type=Path, default=DEFAULT_OPTUNA_REPORT_PATH)
    parser.add_argument("--optuna-spec", type=Path, default=DEFAULT_OPTUNA_SPEC_PATH)
    parser.add_argument("--optuna-ledger", type=Path, default=DEFAULT_OPTUNA_LEDGER_PATH)
    parser.add_argument("--optuna-trace", type=Path, default=DEFAULT_OPTUNA_TRACE_PATH)
    parser.add_argument("--optuna-predictions", type=Path, default=DEFAULT_OPTUNA_PREDICTIONS_PATH)
    parser.add_argument("--tracking-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=LESSON_ROOT / "outputs")
    args = parser.parse_args()

    result = run(
        policy_path=args.policy,
        optuna_report_path=args.optuna_report,
        optuna_spec_path=args.optuna_spec,
        optuna_ledger_path=args.optuna_ledger,
        optuna_trace_path=args.optuna_trace,
        optuna_predictions_path=args.optuna_predictions,
        tracking_root=args.tracking_root,
    )
    output_spec = read_json(args.policy)["output"] if args.policy.is_file() else {
        "report_file": "mlflow_experiment_report.json",
        "run_table_file": "mlflow_run_table.csv",
        "artifact_inventory_file": "mlflow_artifact_inventory.csv",
        "metric_history_file": "mlflow_metric_history.csv",
        "reproducibility_checks_file": "mlflow_reproducibility_checks.csv",
        "model_metadata_file": "mlflow_model_metadata.json",
        "serialized_spec_file": "mlflow_tracking_serialized_spec.json",
    }
    write_outputs(result, args.output_root, output_spec)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
