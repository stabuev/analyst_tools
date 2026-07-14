from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
DATA_ROOT = PHASE_16_ROOT / "data" / "tiny"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"

DEFAULT_POLICY_PATH = DATA_ROOT / "cost_sensitive_decision_policy_spec.json"
DEFAULT_PROBLEM_SPEC_PATH = UPSTREAM_DATA_ROOT / "problem_spec.json"
DEFAULT_CALIBRATION_REPORT_PATH = (
    PHASE_15_ROOT / "12-calibration" / "outputs" / "calibration_report.json"
)
DEFAULT_CALIBRATED_PREDICTIONS_PATH = (
    PHASE_15_ROOT / "12-calibration" / "outputs" / "calibrated_predictions.csv"
)
DEFAULT_SEGMENT_REPORT_PATH = (
    PHASE_16_ROOT / "07-segment-analysis" / "outputs" / "strong_model_segment_report.json"
)
DEFAULT_SEGMENT_SPEC_PATH = (
    PHASE_16_ROOT / "07-segment-analysis" / "outputs" / "strong_model_segment_serialized_spec.json"
)

GENERATED_AT = "2026-07-05T12:30:00+03:00"


class CostSensitiveDecisionError(ValueError):
    """Raised when cost-sensitive decision inputs cannot be parsed."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
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
    raise CostSensitiveDecisionError(f"Cannot parse boolean label: {value!r}")


def parse_bool(value: Any) -> bool:
    return bool(bool_label(value))


def safe_rate(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return rounded(float(numerator) / float(denominator))


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
    problem_spec: dict[str, Any],
    calibration_report: dict[str, Any],
    segment_report: dict[str, Any],
    segment_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    required = {
        "cost_sensitive_decision_audit_id",
        "problem_id",
        "baseline_package_id",
        "baseline_model_id",
        "candidate_model_id",
        "segment_analysis_audit_id",
        "calibration_policy_id",
        "analysis_split",
        "final_holdout_split",
        "score_sources",
        "cost_policy",
        "budget_policy",
        "threshold_policy",
        "decision_policy",
        "interpretation_policy",
        "warning_policy",
        "output",
    }
    missing = sorted(required - set(policy))
    if missing:
        checks.append(failed("cost_sensitive_policy_has_required_fields", missing, "no missing fields"))
    else:
        checks.append(passed("cost_sensitive_policy_has_required_fields", sorted(required), "required policy fields"))

    errors: list[dict[str, Any]] = []
    if policy.get("problem_id") != problem_spec.get("problem_id"):
        errors.append({"field": "problem_id", "observed": policy.get("problem_id"), "expected": problem_spec.get("problem_id")})

    summary = calibration_report.get("summary", {})
    if calibration_report.get("valid") is not True:
        errors.append({"field": "calibration_report.valid", "observed": calibration_report.get("valid"), "expected": True})
    if summary.get("calibration_policy_id") != policy.get("calibration_policy_id"):
        errors.append(
            {
                "field": "calibration_report.summary.calibration_policy_id",
                "observed": summary.get("calibration_policy_id"),
                "expected": policy.get("calibration_policy_id"),
            }
        )
    if summary.get("source_model_id") != policy.get("baseline_model_id"):
        errors.append(
            {
                "field": "calibration_report.summary.source_model_id",
                "observed": summary.get("source_model_id"),
                "expected": policy.get("baseline_model_id"),
            }
        )
    if summary.get("readiness_status") != "ready_for_leakage_lesson":
        errors.append(
            {
                "field": "calibration_report.summary.readiness_status",
                "observed": summary.get("readiness_status"),
                "expected": "ready_for_leakage_lesson",
            }
        )

    segment_summary = segment_report.get("summary", {})
    if segment_report.get("valid") is not True:
        errors.append({"field": "segment_report.valid", "observed": segment_report.get("valid"), "expected": True})
    expected_segment = {
        "segment_analysis_audit_id": policy.get("segment_analysis_audit_id"),
        "baseline_model_id": policy.get("baseline_model_id"),
        "early_stopping_model_id": policy.get("candidate_model_id"),
        "analysis_split": policy.get("analysis_split"),
        "final_holdout_split": policy.get("final_holdout_split"),
    }
    for field, expected in expected_segment.items():
        if segment_summary.get(field) != expected:
            errors.append({"field": f"segment_report.summary.{field}", "observed": segment_summary.get(field), "expected": expected})
    if segment_summary.get("readiness_status") != "ready_for_cost_sensitive_decision_lesson":
        errors.append(
            {
                "field": "segment_report.summary.readiness_status",
                "observed": segment_summary.get("readiness_status"),
                "expected": "ready_for_cost_sensitive_decision_lesson",
            }
        )
    if segment_spec.get("segment_analysis_audit_id") != policy.get("segment_analysis_audit_id"):
        errors.append(
            {
                "field": "segment_spec.segment_analysis_audit_id",
                "observed": segment_spec.get("segment_analysis_audit_id"),
                "expected": policy.get("segment_analysis_audit_id"),
            }
        )

    if errors:
        checks.append(failed("cost_policy_matches_upstream_handoff", errors, "same problem, calibration and segment handoffs"))
    else:
        checks.append(
            passed(
                "cost_policy_matches_upstream_handoff",
                {
                    "problem_id": policy["problem_id"],
                    "baseline_model_id": policy["baseline_model_id"],
                    "candidate_model_id": policy["candidate_model_id"],
                    "analysis_split": policy["analysis_split"],
                },
                "policy matches upstream handoffs",
            )
        )

    cost_errors: list[dict[str, Any]] = []
    cost_policy = policy.get("cost_policy", {})
    problem_costs = problem_spec.get("metric_policy", {}).get("cost_weights", {})
    for field, policy_field in (
        ("false_positive", "false_positive_cost"),
        ("false_negative", "false_negative_cost"),
    ):
        if float(cost_policy.get(policy_field, -1)) != float(problem_costs.get(field, -2)):
            cost_errors.append(
                {
                    "field": f"cost_policy.{policy_field}",
                    "observed": cost_policy.get(policy_field),
                    "expected": problem_costs.get(field),
                }
            )
    if cost_policy.get("unit") != problem_costs.get("unit"):
        cost_errors.append({"field": "cost_policy.unit", "observed": cost_policy.get("unit"), "expected": problem_costs.get("unit")})
    max_actions = policy.get("budget_policy", {}).get("max_actions")
    if max_actions != problem_spec.get("decision_budget", {}).get("max_actions"):
        cost_errors.append(
            {
                "field": "budget_policy.max_actions",
                "observed": max_actions,
                "expected": problem_spec.get("decision_budget", {}).get("max_actions"),
            }
        )
    if cost_errors:
        checks.append(failed("business_cost_and_budget_match_problem_spec", cost_errors, "problem spec cost weights and budget"))
    else:
        checks.append(
            passed(
                "business_cost_and_budget_match_problem_spec",
                {
                    "false_positive_cost": cost_policy["false_positive_cost"],
                    "false_negative_cost": cost_policy["false_negative_cost"],
                    "max_actions": max_actions,
                },
                "problem spec cost weights and budget",
            )
        )

    threshold_errors: list[dict[str, Any]] = []
    threshold_policy = policy.get("threshold_policy", {})
    if threshold_policy.get("selection_data") != policy.get("analysis_split"):
        threshold_errors.append(
            {
                "field": "threshold_policy.selection_data",
                "observed": threshold_policy.get("selection_data"),
                "expected": policy.get("analysis_split"),
            }
        )
    if threshold_policy.get("forbid_threshold_selection_on_test") is not True:
        threshold_errors.append(
            {
                "field": "threshold_policy.forbid_threshold_selection_on_test",
                "observed": threshold_policy.get("forbid_threshold_selection_on_test"),
                "expected": True,
            }
        )
    if threshold_policy.get("selection_data") == policy.get("final_holdout_split"):
        threshold_errors.append(
            {
                "field": "threshold_policy.selection_data",
                "observed": threshold_policy.get("selection_data"),
                "expected": f"not {policy.get('final_holdout_split')}",
            }
        )
    if not isinstance(threshold_policy.get("candidate_thresholds"), list) or not threshold_policy.get("candidate_thresholds"):
        threshold_errors.append({"field": "threshold_policy.candidate_thresholds", "observed": threshold_policy.get("candidate_thresholds"), "expected": "non-empty list"})
    if threshold_errors:
        checks.append(failed("threshold_selection_uses_validation_only", threshold_errors, "validation split only, test excluded"))
    else:
        checks.append(
            passed(
                "threshold_selection_uses_validation_only",
                {
                    "selection_data": threshold_policy["selection_data"],
                    "final_holdout_split": policy["final_holdout_split"],
                    "candidate_threshold_count": len(threshold_policy["candidate_thresholds"]),
                },
                "validation split only, test excluded",
            )
        )

    output = policy.get("output", {})
    output_missing = [
        field
        for field in (
            "report_file",
            "decision_row_file",
            "threshold_comparison_file",
            "budget_impact_file",
            "decision_gate_file",
            "audit_file",
            "serialized_spec_file",
        )
        if not output.get(field)
    ]
    if output_missing:
        checks.append(failed("output_contract_names_all_artifacts", output_missing, "all output filenames are declared"))
    else:
        checks.append(passed("output_contract_names_all_artifacts", sorted(output), "all output filenames are declared"))
    return checks


def make_decision_rows(
    *,
    policy: dict[str, Any],
    calibrated_predictions_path: Path,
    segment_report: dict[str, Any],
) -> list[dict[str, Any]]:
    split = policy["analysis_split"]
    score_sources = policy["score_sources"]
    calibrated_rows = [
        row
        for row in read_csv_rows(calibrated_predictions_path)
        if row["split"] == split and row["model_id"] == policy["baseline_model_id"]
    ]
    if not calibrated_rows:
        raise CostSensitiveDecisionError("calibrated baseline rows are empty for the analysis split")

    baseline_rows: list[dict[str, Any]] = []
    for row in calibrated_rows:
        score = rounded(float(row[score_sources["baseline"]["score_column"]]))
        baseline_rows.append(
            {
                "analysis_split": split,
                "model_role": "baseline",
                "model_id": row["model_id"],
                "score_source": score_sources["baseline"]["score_column"],
                "score_type": score_sources["baseline"]["score_type"],
                "calibration_status": score_sources["baseline"]["calibration_status"],
                "split": row["split"],
                "snapshot_id": row["snapshot_id"],
                "score": score,
                "actual_label": bool_label(row["actual_label"]),
                "upstream_selected_at_budget": parse_bool(row["selected_at_budget_calibrated"]),
                "trained_on_split": row["trained_on_split"],
                "generated_at": GENERATED_AT,
            }
        )

    segment_rows = [
        row
        for row in segment_report.get("confusion_rows", [])
        if row.get("split") == split and row.get("model_role") == "catboost"
    ]
    if not segment_rows:
        raise CostSensitiveDecisionError("catboost segment rows are empty for the analysis split")

    candidate_rows: list[dict[str, Any]] = []
    for row in segment_rows:
        candidate_rows.append(
            {
                "analysis_split": split,
                "model_role": "catboost",
                "model_id": policy["candidate_model_id"],
                "score_source": score_sources["catboost"]["score_column"],
                "score_type": score_sources["catboost"]["score_type"],
                "calibration_status": score_sources["catboost"]["calibration_status"],
                "split": row["split"],
                "snapshot_id": row["snapshot_id"],
                "score": rounded(float(row["score"])),
                "actual_label": bool_label(row["actual_label"]),
                "upstream_selected_at_budget": bool(row["selected_for_action"]),
                "trained_on_split": "train",
                "generated_at": GENERATED_AT,
            }
        )

    rows = baseline_rows + candidate_rows
    for model_role in ("baseline", "catboost"):
        model_rows = sorted(
            [row for row in rows if row["model_role"] == model_role],
            key=lambda row: (-float(row["score"]), row["snapshot_id"]),
        )
        for rank, row in enumerate(model_rows, start=1):
            row["score_rank"] = rank
    return sorted(rows, key=lambda row: (row["model_role"], int(row["score_rank"]), row["snapshot_id"]))


def confusion_label(selected: bool, actual: int) -> str:
    if selected and actual == 1:
        return "tp"
    if selected and actual == 0:
        return "fp"
    if not selected and actual == 1:
        return "fn"
    return "tn"


def evaluate_selection(
    *,
    rows: list[dict[str, Any]],
    selected_ids: set[str],
    false_positive_cost: float,
    false_negative_cost: float,
) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    true_positive_ids: list[str] = []
    false_positive_ids: list[str] = []
    false_negative_ids: list[str] = []
    selected_ordered: list[str] = []
    for row in sorted(rows, key=lambda item: (int(item["score_rank"]), item["snapshot_id"])):
        snapshot_id = row["snapshot_id"]
        selected = snapshot_id in selected_ids
        actual = int(row["actual_label"])
        if selected:
            selected_ordered.append(snapshot_id)
        label = confusion_label(selected, actual)
        if label == "tp":
            tp += 1
            true_positive_ids.append(snapshot_id)
        elif label == "fp":
            fp += 1
            false_positive_ids.append(snapshot_id)
        elif label == "fn":
            fn += 1
            false_negative_ids.append(snapshot_id)
        else:
            tn += 1
    action_count = len(selected_ordered)
    total_error_cost = rounded(fp * false_positive_cost + fn * false_negative_cost)
    return {
        "action_count": action_count,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": safe_rate(tp, tp + fp),
        "recall": safe_rate(tp, tp + fn),
        "false_positive_rate": safe_rate(fp, fp + tn),
        "false_negative_rate": safe_rate(fn, tp + fn),
        "total_error_cost": total_error_cost,
        "average_error_cost": safe_rate(total_error_cost or 0.0, len(rows)),
        "selected_ids": ",".join(selected_ordered),
        "true_positive_ids": ",".join(true_positive_ids),
        "false_positive_ids": ",".join(false_positive_ids),
        "false_negative_ids": ",".join(false_negative_ids),
    }


def threshold_rows_for_model(
    *,
    model_rows: list[dict[str, Any]],
    thresholds: list[float],
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    model_role = model_rows[0]["model_role"]
    model_id = model_rows[0]["model_id"]
    score_source = model_rows[0]["score_source"]
    calibration_status = model_rows[0]["calibration_status"]
    for threshold in thresholds:
        selected_ids = {row["snapshot_id"] for row in model_rows if float(row["score"]) >= float(threshold)}
        metrics = evaluate_selection(
            rows=model_rows,
            selected_ids=selected_ids,
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        rows.append(
            {
                "model_role": model_role,
                "model_id": model_id,
                "score_source": score_source,
                "calibration_status": calibration_status,
                "threshold": rounded(float(threshold)),
                "decision_rule": "threshold_policy",
                "budget_max_actions": budget,
                "budget_status": "within_budget" if metrics["action_count"] <= budget else "over_budget",
                "threshold_is_budget_eligible": metrics["action_count"] <= budget,
                "threshold_selected": False,
                **metrics,
            }
        )
    selected = select_best_threshold(rows)
    for row in rows:
        row["threshold_selected"] = row is selected
    return rows


def select_best_threshold(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row["threshold_is_budget_eligible"]]
    if not eligible:
        raise CostSensitiveDecisionError("no threshold is eligible under the configured action budget")
    return sorted(
        eligible,
        key=lambda row: (
            float(row["total_error_cost"]),
            -(row["recall"] if row["recall"] is not None else -1.0),
            int(row["action_count"]),
            -float(row["threshold"]),
        ),
    )[0]


def build_threshold_comparison(policy: dict[str, Any], decision_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cost_policy = policy["cost_policy"]
    budget = int(policy["budget_policy"]["max_actions"])
    thresholds = [float(value) for value in policy["threshold_policy"]["candidate_thresholds"]]
    rows: list[dict[str, Any]] = []
    for model_role in ("baseline", "catboost"):
        model_rows = [row for row in decision_rows if row["model_role"] == model_role]
        rows.extend(
            threshold_rows_for_model(
                model_rows=model_rows,
                thresholds=thresholds,
                budget=budget,
                false_positive_cost=float(cost_policy["false_positive_cost"]),
                false_negative_cost=float(cost_policy["false_negative_cost"]),
            )
        )
    return rows


def selected_threshold_row(threshold_comparison: list[dict[str, Any]], model_role: str) -> dict[str, Any]:
    return next(row for row in threshold_comparison if row["model_role"] == model_role and row["threshold_selected"])


def top_k_ids(model_rows: list[dict[str, Any]], k: int) -> set[str]:
    return {
        row["snapshot_id"]
        for row in sorted(model_rows, key=lambda item: (-float(item["score"]), item["snapshot_id"]))[:k]
    }


def build_budget_impact(
    *,
    policy: dict[str, Any],
    decision_rows: list[dict[str, Any]],
    threshold_comparison: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cost_policy = policy["cost_policy"]
    budget = int(policy["budget_policy"]["max_actions"])
    false_positive_cost = float(cost_policy["false_positive_cost"])
    false_negative_cost = float(cost_policy["false_negative_cost"])
    rows: list[dict[str, Any]] = []
    for model_role in ("baseline", "catboost"):
        model_rows = [row for row in decision_rows if row["model_role"] == model_role]
        selected = selected_threshold_row(threshold_comparison, model_role)
        rows.append(
            {
                "model_role": model_role,
                "model_id": selected["model_id"],
                "decision_rule": "selected_threshold_policy",
                "threshold": selected["threshold"],
                "k": "",
                "budget_max_actions": budget,
                "budget_status": selected["budget_status"],
                **{field: selected[field] for field in selection_metric_fields()},
            }
        )

        ids = top_k_ids(model_rows, budget)
        metrics = evaluate_selection(
            rows=model_rows,
            selected_ids=ids,
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        rows.append(
            {
                "model_role": model_role,
                "model_id": model_rows[0]["model_id"],
                "decision_rule": "top_k_budget_policy",
                "threshold": "",
                "k": budget,
                "budget_max_actions": budget,
                "budget_status": "within_budget",
                **metrics,
            }
        )

        fixed_ids = {row["snapshot_id"] for row in model_rows if float(row["score"]) >= 0.5}
        fixed = evaluate_selection(
            rows=model_rows,
            selected_ids=fixed_ids,
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        rows.append(
            {
                "model_role": model_role,
                "model_id": model_rows[0]["model_id"],
                "decision_rule": "fixed_threshold_0_5_diagnostic",
                "threshold": 0.5,
                "k": "",
                "budget_max_actions": budget,
                "budget_status": "within_budget" if fixed["action_count"] <= budget else "over_budget",
                **fixed,
            }
        )
    return rows


def selection_metric_fields() -> list[str]:
    return [
        "action_count",
        "tp",
        "fp",
        "tn",
        "fn",
        "precision",
        "recall",
        "false_positive_rate",
        "false_negative_rate",
        "total_error_cost",
        "average_error_cost",
        "selected_ids",
        "true_positive_ids",
        "false_positive_ids",
        "false_negative_ids",
    ]


def budget_row(budget_impact: list[dict[str, Any]], model_role: str, decision_rule: str) -> dict[str, Any]:
    return next(row for row in budget_impact if row["model_role"] == model_role and row["decision_rule"] == decision_rule)


def build_decision_gate(
    *,
    policy: dict[str, Any],
    threshold_comparison: list[dict[str, Any]],
    budget_impact: list[dict[str, Any]],
    segment_report: dict[str, Any],
) -> list[dict[str, Any]]:
    baseline_threshold = selected_threshold_row(threshold_comparison, "baseline")
    candidate_threshold = selected_threshold_row(threshold_comparison, "catboost")
    baseline_top_k = budget_row(budget_impact, "baseline", "top_k_budget_policy")
    candidate_top_k = budget_row(budget_impact, "catboost", "top_k_budget_policy")
    segment_summary = segment_report["summary"]
    candidate_calibration_status = policy["score_sources"]["catboost"]["calibration_status"]
    candidate_calibrated = candidate_calibration_status.startswith("approved")
    hidden_failure_count = int(segment_summary.get("hidden_failure_slice_count", 0))
    segment_warning_count = len(segment_summary.get("warnings", []))

    gates: list[dict[str, Any]] = []

    def add_gate(
        gate_id: str,
        passed_gate: bool,
        observed: Any,
        expected: Any,
        *,
        required_for_promotion: bool = True,
        severity: str = "blocking_for_promotion",
    ) -> None:
        gates.append(
            {
                "gate_id": gate_id,
                "passed": passed_gate,
                "required_for_promotion": required_for_promotion,
                "severity": severity,
                "observed": observed,
                "expected": expected,
            }
        )

    add_gate(
        "final_holdout_excluded_from_threshold_selection",
        policy["threshold_policy"]["selection_data"] != policy["final_holdout_split"],
        policy["threshold_policy"]["selection_data"],
        f"not {policy['final_holdout_split']}",
        severity="method_guardrail",
    )
    add_gate(
        "candidate_threshold_cost_lte_baseline_best",
        float(candidate_threshold["total_error_cost"]) <= float(baseline_threshold["total_error_cost"]),
        {
            "candidate_total_error_cost": candidate_threshold["total_error_cost"],
            "baseline_total_error_cost": baseline_threshold["total_error_cost"],
        },
        "candidate cost <= baseline cost",
    )
    add_gate(
        "candidate_top_k_cost_lte_baseline_top_k",
        float(candidate_top_k["total_error_cost"]) <= float(baseline_top_k["total_error_cost"]),
        {
            "candidate_top_k_total_error_cost": candidate_top_k["total_error_cost"],
            "baseline_top_k_total_error_cost": baseline_top_k["total_error_cost"],
        },
        "candidate top-k cost <= baseline top-k cost",
    )
    add_gate(
        "candidate_has_approved_calibration",
        candidate_calibrated,
        candidate_calibration_status,
        "approved candidate calibration",
    )
    add_gate(
        "segment_hidden_failures_absent",
        hidden_failure_count == 0 and segment_warning_count == 0,
        {
            "hidden_failure_slice_count": hidden_failure_count,
            "segment_warning_count": segment_warning_count,
        },
        "no unresolved segment warnings",
    )
    add_gate(
        "no_causal_offer_effect_claim",
        "does not estimate the causal effect" in policy["interpretation_policy"]["claim"],
        policy["interpretation_policy"]["claim"],
        "decision artifact states that retention-offer effect is out of scope",
        required_for_promotion=False,
        severity="claim_boundary",
    )
    promotion_passed = all(row["passed"] for row in gates if row["required_for_promotion"])
    gates.append(
        {
            "gate_id": "promotion_requires_all_gates",
            "passed": promotion_passed,
            "required_for_promotion": False,
            "severity": "decision_status",
            "observed": "all required gates passed" if promotion_passed else "one or more required gates failed",
            "expected": "all required gates passed before promotion",
        }
    )
    return gates


def add_table_checks(
    *,
    checks: list[dict[str, Any]],
    policy: dict[str, Any],
    decision_rows: list[dict[str, Any]],
    threshold_comparison: list[dict[str, Any]],
    budget_impact: list[dict[str, Any]],
    decision_gate: list[dict[str, Any]],
    segment_report: dict[str, Any],
) -> None:
    roles = {row["model_role"] for row in decision_rows}
    snapshot_sets = {
        role: {row["snapshot_id"] for row in decision_rows if row["model_role"] == role}
        for role in roles
    }
    if roles == {"baseline", "catboost"} and len(set(map(tuple, [sorted(value) for value in snapshot_sets.values()]))) == 1:
        checks.append(passed("decision_rows_cover_same_validation_population", {role: sorted(ids) for role, ids in snapshot_sets.items()}, "same snapshot ids for both models"))
    else:
        checks.append(failed("decision_rows_cover_same_validation_population", {role: sorted(ids) for role, ids in snapshot_sets.items()}, "same snapshot ids for both models"))

    expected_threshold_rows = len(policy["threshold_policy"]["candidate_thresholds"]) * 2
    selected_count = len([row for row in threshold_comparison if row["threshold_selected"]])
    if len(threshold_comparison) == expected_threshold_rows and selected_count == 2:
        checks.append(passed("threshold_comparison_complete", {"row_count": len(threshold_comparison), "selected_threshold_count": selected_count}, {"row_count": expected_threshold_rows, "selected_threshold_count": 2}))
    else:
        checks.append(failed("threshold_comparison_complete", {"row_count": len(threshold_comparison), "selected_threshold_count": selected_count}, {"row_count": expected_threshold_rows, "selected_threshold_count": 2}))

    if len(budget_impact) == 6 and {"selected_threshold_policy", "top_k_budget_policy", "fixed_threshold_0_5_diagnostic"} == {row["decision_rule"] for row in budget_impact}:
        checks.append(passed("budget_impact_complete", {"row_count": len(budget_impact)}, "three decision rules per model"))
    else:
        checks.append(failed("budget_impact_complete", {"row_count": len(budget_impact)}, "three decision rules per model"))

    failed_required_gates = [row["gate_id"] for row in decision_gate if row["required_for_promotion"] and not row["passed"]]
    if failed_required_gates:
        checks.append(
            failed(
                "candidate_not_promoted_due_to_decision_gate",
                failed_required_gates,
                "all promotion gates pass",
                severity="warning",
            )
        )
    else:
        checks.append(passed("candidate_not_promoted_due_to_decision_gate", [], "no failed promotion gates"))

    candidate_status = policy["score_sources"]["catboost"]["calibration_status"]
    if policy["warning_policy"]["require_calibration_warning_for_candidate"] and not candidate_status.startswith("approved"):
        checks.append(
            failed(
                "candidate_score_is_not_calibrated",
                candidate_status,
                "approved candidate calibration",
                severity="warning",
            )
        )

    baseline_best = selected_threshold_row(threshold_comparison, "baseline")
    candidate_best = selected_threshold_row(threshold_comparison, "catboost")
    if float(candidate_best["total_error_cost"]) > float(baseline_best["total_error_cost"]):
        checks.append(
            failed(
                "catboost_threshold_cost_worse_than_baseline",
                {
                    "candidate_total_error_cost": candidate_best["total_error_cost"],
                    "baseline_total_error_cost": baseline_best["total_error_cost"],
                },
                "candidate cost <= baseline cost",
                severity="warning",
            )
        )

    baseline_top_k = budget_row(budget_impact, "baseline", "top_k_budget_policy")
    candidate_top_k = budget_row(budget_impact, "catboost", "top_k_budget_policy")
    if float(candidate_top_k["total_error_cost"]) > float(baseline_top_k["total_error_cost"]):
        checks.append(
            failed(
                "catboost_top_k_budget_cost_worse_than_baseline",
                {
                    "candidate_top_k_total_error_cost": candidate_top_k["total_error_cost"],
                    "baseline_top_k_total_error_cost": baseline_top_k["total_error_cost"],
                },
                "candidate top-k cost <= baseline top-k cost",
                severity="warning",
            )
        )

    if policy["warning_policy"]["require_segment_warning_propagation"] and segment_report["summary"].get("warnings"):
        checks.append(
            failed(
                "segment_warnings_propagated_to_decision_gate",
                segment_report["summary"]["warnings"],
                "segment warnings must be visible in the decision gate",
                severity="warning",
            )
        )

    if policy["warning_policy"]["require_no_causal_effect_boundary"]:
        checks.append(
            failed(
                "no_causal_offer_effect_boundary_visible",
                policy["interpretation_policy"]["claim"],
                "the report must not claim causal offer effect",
                severity="warning",
            )
        )


def decision_status(policy: dict[str, Any], decision_gate: list[dict[str, Any]]) -> str:
    promotion_passed = next(row for row in decision_gate if row["gate_id"] == "promotion_requires_all_gates")["passed"]
    if promotion_passed:
        return policy["decision_policy"]["outcome_if_passed"]
    return policy["decision_policy"]["outcome_if_failed"]


def build_serialized_spec(
    *,
    policy: dict[str, Any],
    threshold_comparison: list[dict[str, Any]],
    budget_impact: list[dict[str, Any]],
    decision_gate: list[dict[str, Any]],
    calibration_report: dict[str, Any],
    segment_report: dict[str, Any],
) -> dict[str, Any]:
    baseline_threshold = selected_threshold_row(threshold_comparison, "baseline")
    candidate_threshold = selected_threshold_row(threshold_comparison, "catboost")
    baseline_top_k = budget_row(budget_impact, "baseline", "top_k_budget_policy")
    candidate_top_k = budget_row(budget_impact, "catboost", "top_k_budget_policy")
    return {
        "cost_sensitive_decision_audit_id": policy["cost_sensitive_decision_audit_id"],
        "problem_id": policy["problem_id"],
        "baseline_model_id": policy["baseline_model_id"],
        "candidate_model_id": policy["candidate_model_id"],
        "analysis_split": policy["analysis_split"],
        "final_holdout_split": policy["final_holdout_split"],
        "score_sources": policy["score_sources"],
        "cost_policy": policy["cost_policy"],
        "budget_policy": policy["budget_policy"],
        "threshold_policy": policy["threshold_policy"],
        "selection_summary": {
            "baseline_selected_threshold": baseline_threshold["threshold"],
            "catboost_selected_threshold": candidate_threshold["threshold"],
            "baseline_threshold_selected_ids": baseline_threshold["selected_ids"].split(",") if baseline_threshold["selected_ids"] else [],
            "catboost_threshold_selected_ids": candidate_threshold["selected_ids"].split(",") if candidate_threshold["selected_ids"] else [],
            "baseline_top_k_selected_ids": baseline_top_k["selected_ids"].split(",") if baseline_top_k["selected_ids"] else [],
            "catboost_top_k_selected_ids": candidate_top_k["selected_ids"].split(",") if candidate_top_k["selected_ids"] else [],
            "baseline_best_total_error_cost": baseline_threshold["total_error_cost"],
            "catboost_best_total_error_cost": candidate_threshold["total_error_cost"],
            "baseline_top_k_total_error_cost": baseline_top_k["total_error_cost"],
            "catboost_top_k_total_error_cost": candidate_top_k["total_error_cost"],
        },
        "decision_gate": decision_gate,
        "upstream_handoff": {
            "calibration_policy_id": calibration_report["summary"]["calibration_policy_id"],
            "calibration_readiness_status": calibration_report["summary"]["readiness_status"],
            "segment_analysis_audit_id": segment_report["summary"]["segment_analysis_audit_id"],
            "segment_readiness_status": segment_report["summary"]["readiness_status"],
            "segment_warnings": segment_report["summary"]["warnings"],
        },
        "generated_at": GENERATED_AT,
    }


def build_summary(
    *,
    policy: dict[str, Any],
    threshold_comparison: list[dict[str, Any]],
    budget_impact: list[dict[str, Any]],
    decision_gate: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_threshold = selected_threshold_row(threshold_comparison, "baseline")
    candidate_threshold = selected_threshold_row(threshold_comparison, "catboost")
    baseline_top_k = budget_row(budget_impact, "baseline", "top_k_budget_policy")
    candidate_top_k = budget_row(budget_impact, "catboost", "top_k_budget_policy")
    errors = blocking_errors(checks)
    status = decision_status(policy, decision_gate)
    return {
        "cost_sensitive_decision_audit_id": policy["cost_sensitive_decision_audit_id"],
        "problem_id": policy["problem_id"],
        "baseline_model_id": policy["baseline_model_id"],
        "candidate_model_id": policy["candidate_model_id"],
        "analysis_split": policy["analysis_split"],
        "final_holdout_split": policy["final_holdout_split"],
        "false_positive_cost": policy["cost_policy"]["false_positive_cost"],
        "false_negative_cost": policy["cost_policy"]["false_negative_cost"],
        "budget_max_actions": policy["budget_policy"]["max_actions"],
        "baseline_selected_threshold": baseline_threshold["threshold"],
        "catboost_selected_threshold": candidate_threshold["threshold"],
        "baseline_best_total_error_cost": baseline_threshold["total_error_cost"],
        "catboost_best_total_error_cost": candidate_threshold["total_error_cost"],
        "candidate_cost_delta_vs_baseline": rounded(float(candidate_threshold["total_error_cost"]) - float(baseline_threshold["total_error_cost"])),
        "baseline_top_k_total_error_cost": baseline_top_k["total_error_cost"],
        "catboost_top_k_total_error_cost": candidate_top_k["total_error_cost"],
        "candidate_top_k_cost_delta_vs_baseline": rounded(float(candidate_top_k["total_error_cost"]) - float(baseline_top_k["total_error_cost"])),
        "baseline_threshold_selected_ids": baseline_threshold["selected_ids"],
        "catboost_threshold_selected_ids": candidate_threshold["selected_ids"],
        "baseline_top_k_selected_ids": baseline_top_k["selected_ids"],
        "catboost_top_k_selected_ids": candidate_top_k["selected_ids"],
        "candidate_has_approved_calibration": policy["score_sources"]["catboost"]["calibration_status"].startswith("approved"),
        "failed_promotion_gates": [
            row["gate_id"] for row in decision_gate if row["required_for_promotion"] and not row["passed"]
        ],
        "decision_status": status,
        "blocking_errors": errors,
        "warnings": warning_ids(checks),
        "readiness_status": "blocked_before_cost_sensitive_decision" if errors else policy["decision_policy"]["next_lesson_readiness"],
    }


def empty_invalid_report(file_check: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": False,
        "problem_id": None,
        "summary": {
            "cost_sensitive_decision_audit_id": None,
            "blocking_errors": blocking_errors([file_check]),
            "warnings": [],
            "readiness_status": "blocked_before_cost_sensitive_decision",
        },
        "decision_rows": [],
        "threshold_comparison": [],
        "budget_impact": [],
        "decision_gate": [],
        "checks": [file_check],
        "serialized_spec": {},
    }


def run(
    *,
    policy_path: Path = DEFAULT_POLICY_PATH,
    problem_spec_path: Path = DEFAULT_PROBLEM_SPEC_PATH,
    calibration_report_path: Path = DEFAULT_CALIBRATION_REPORT_PATH,
    calibrated_predictions_path: Path = DEFAULT_CALIBRATED_PREDICTIONS_PATH,
    segment_report_path: Path = DEFAULT_SEGMENT_REPORT_PATH,
    segment_spec_path: Path = DEFAULT_SEGMENT_SPEC_PATH,
) -> dict[str, Any]:
    paths = {
        "policy": policy_path,
        "problem_spec": problem_spec_path,
        "calibration_report": calibration_report_path,
        "calibrated_predictions": calibrated_predictions_path,
        "segment_report": segment_report_path,
        "segment_spec": segment_spec_path,
    }
    file_check = validate_required_files(paths)
    if not file_check["valid"]:
        return empty_invalid_report(file_check)

    policy = read_json(policy_path)
    problem_spec = read_json(problem_spec_path)
    calibration_report = read_json(calibration_report_path)
    segment_report = read_json(segment_report_path)
    segment_spec = read_json(segment_spec_path)
    checks = [file_check]
    checks.extend(
        validate_policy(
            policy=policy,
            problem_spec=problem_spec,
            calibration_report=calibration_report,
            segment_report=segment_report,
            segment_spec=segment_spec,
        )
    )
    decision_rows = make_decision_rows(
        policy=policy,
        calibrated_predictions_path=calibrated_predictions_path,
        segment_report=segment_report,
    )
    threshold_comparison = build_threshold_comparison(policy, decision_rows)
    budget_impact = build_budget_impact(
        policy=policy,
        decision_rows=decision_rows,
        threshold_comparison=threshold_comparison,
    )
    decision_gate = build_decision_gate(
        policy=policy,
        threshold_comparison=threshold_comparison,
        budget_impact=budget_impact,
        segment_report=segment_report,
    )
    add_table_checks(
        checks=checks,
        policy=policy,
        decision_rows=decision_rows,
        threshold_comparison=threshold_comparison,
        budget_impact=budget_impact,
        decision_gate=decision_gate,
        segment_report=segment_report,
    )
    serialized_spec = build_serialized_spec(
        policy=policy,
        threshold_comparison=threshold_comparison,
        budget_impact=budget_impact,
        decision_gate=decision_gate,
        calibration_report=calibration_report,
        segment_report=segment_report,
    )
    summary = build_summary(
        policy=policy,
        threshold_comparison=threshold_comparison,
        budget_impact=budget_impact,
        decision_gate=decision_gate,
        checks=checks,
    )
    return {
        "valid": not blocking_errors(checks),
        "problem_id": policy["problem_id"],
        "summary": summary,
        "decision_rows": decision_rows,
        "threshold_comparison": threshold_comparison,
        "budget_impact": budget_impact,
        "decision_gate": decision_gate,
        "checks": checks,
        "serialized_spec": serialized_spec,
    }


def write_outputs(result: dict[str, Any], output_root: Path, output_spec: dict[str, str]) -> None:
    write_json(output_root / output_spec["report_file"], {key: value for key, value in result.items() if key != "serialized_spec"})
    write_json(output_root / output_spec["serialized_spec_file"], result["serialized_spec"])
    write_csv(
        output_root / output_spec["decision_row_file"],
        result["decision_rows"],
        [
            "analysis_split",
            "model_role",
            "model_id",
            "score_source",
            "score_type",
            "calibration_status",
            "split",
            "snapshot_id",
            "score",
            "score_rank",
            "actual_label",
            "upstream_selected_at_budget",
            "trained_on_split",
            "generated_at",
        ],
    )
    write_csv(
        output_root / output_spec["threshold_comparison_file"],
        result["threshold_comparison"],
        [
            "model_role",
            "model_id",
            "score_source",
            "calibration_status",
            "threshold",
            "decision_rule",
            "budget_max_actions",
            "budget_status",
            "threshold_is_budget_eligible",
            "threshold_selected",
            *selection_metric_fields(),
        ],
    )
    write_csv(
        output_root / output_spec["budget_impact_file"],
        result["budget_impact"],
        [
            "model_role",
            "model_id",
            "decision_rule",
            "threshold",
            "k",
            "budget_max_actions",
            "budget_status",
            *selection_metric_fields(),
        ],
    )
    write_csv(
        output_root / output_spec["decision_gate_file"],
        result["decision_gate"],
        ["gate_id", "passed", "required_for_promotion", "severity", "observed", "expected"],
    )
    write_csv(
        output_root / output_spec["audit_file"],
        result["checks"],
        ["id", "severity", "valid", "observed", "expected", "sample"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate threshold, cost and top-k decisions for the strong model candidate.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--problem-spec", type=Path, default=DEFAULT_PROBLEM_SPEC_PATH)
    parser.add_argument("--calibration-report", type=Path, default=DEFAULT_CALIBRATION_REPORT_PATH)
    parser.add_argument("--calibrated-predictions", type=Path, default=DEFAULT_CALIBRATED_PREDICTIONS_PATH)
    parser.add_argument("--segment-report", type=Path, default=DEFAULT_SEGMENT_REPORT_PATH)
    parser.add_argument("--segment-spec", type=Path, default=DEFAULT_SEGMENT_SPEC_PATH)
    parser.add_argument("--output-root", type=Path, default=LESSON_ROOT / "outputs")
    args = parser.parse_args()

    result = run(
        policy_path=args.policy,
        problem_spec_path=args.problem_spec,
        calibration_report_path=args.calibration_report,
        calibrated_predictions_path=args.calibrated_predictions,
        segment_report_path=args.segment_report,
        segment_spec_path=args.segment_spec,
    )
    output_spec = read_json(args.policy)["output"] if args.policy.is_file() else {
        "report_file": "cost_sensitive_decision_report.json",
        "decision_row_file": "cost_sensitive_decision_rows.csv",
        "threshold_comparison_file": "threshold_comparison.csv",
        "budget_impact_file": "budget_impact.csv",
        "decision_gate_file": "decision_gate.csv",
        "audit_file": "cost_sensitive_decision_policy_audit.csv",
        "serialized_spec_file": "cost_sensitive_decision_serialized_spec.json",
    }
    write_outputs(result, args.output_root, output_spec)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
