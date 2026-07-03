from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REQUIRED_SCORE_COLUMNS = {
    "snapshot_id",
    "model_id",
    "score",
    "score_type",
    "trained_on_split",
    "generated_at",
}
REQUIRED_LABEL_COLUMNS = {
    "snapshot_id",
    "target_name",
    "label_observed_at",
    "churned_14d",
    "label_window_complete",
}
REQUIRED_MANIFEST_COLUMNS = {
    "snapshot_id",
    "user_id",
    "prediction_time",
    "split",
    "split_order",
    "role",
    "assigned_by_policy",
}
ROLE_BY_SPLIT = {
    "train": "fit_preprocessing_and_estimator",
    "validation": "model_selection_and_threshold_selection",
    "test": "final_once_only_evaluation",
}
REPORT_SPLITS = ("validation", "test")


class ClassificationMetricError(ValueError):
    """Raised when metric-evaluator inputs cannot be parsed."""


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": [],
    }


def failed(
    check_id: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
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


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ClassificationMetricError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ClassificationMetricError(f"expected boolean, got {value!r}")


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ClassificationMetricError(f"expected integer, got {value!r}") from error


def parse_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ClassificationMetricError(f"expected number, got {value!r}") from error
    if not math.isfinite(parsed):
        raise ClassificationMetricError(f"expected finite number, got {value!r}")
    return parsed


def rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return rounded(float(numerator) / float(denominator))


def target_column(spec: dict[str, Any]) -> str:
    target_definition = spec.get("target_definition")
    if isinstance(target_definition, dict) and target_definition.get("target_column"):
        return str(target_definition["target_column"])
    return "churned_14d"


def cost_weights(spec: dict[str, Any]) -> dict[str, float]:
    metric_policy = spec.get("metric_policy") if isinstance(spec.get("metric_policy"), dict) else {}
    weights = metric_policy.get("cost_weights") if isinstance(metric_policy, dict) else {}
    if not isinstance(weights, dict):
        return {"false_positive": 1.0, "false_negative": 1.0}
    return {
        "false_positive": parse_float(weights.get("false_positive", 1.0)),
        "false_negative": parse_float(weights.get("false_negative", 1.0)),
    }


def offer_budget(spec: dict[str, Any]) -> int:
    budget = spec.get("decision_budget")
    if not isinstance(budget, dict):
        raise ClassificationMetricError("decision_budget object is required")
    return parse_int(budget.get("max_actions"))


def validate_metric_policy(spec: dict[str, Any]) -> dict[str, Any]:
    metric_policy = spec.get("metric_policy")
    threshold_policy = spec.get("threshold_policy")
    budget = spec.get("decision_budget")
    errors: list[dict[str, Any]] = []

    if not isinstance(metric_policy, dict):
        errors.append({"field": "metric_policy", "reason": "object required"})
    else:
        if metric_policy.get("primary_metric") != "precision_at_offer_budget":
            errors.append(
                {
                    "field": "metric_policy.primary_metric",
                    "observed": metric_policy.get("primary_metric"),
                    "expected": "precision_at_offer_budget",
                }
            )
        secondary = set(metric_policy.get("secondary_metrics") or [])
        required_secondary = {"recall", "pr_auc", "roc_auc", "log_loss"}
        if not required_secondary <= secondary:
            errors.append(
                {
                    "field": "metric_policy.secondary_metrics",
                    "missing": sorted(required_secondary - secondary),
                }
            )
        if metric_policy.get("accuracy_role") != "diagnostic_only":
            errors.append(
                {
                    "field": "metric_policy.accuracy_role",
                    "observed": metric_policy.get("accuracy_role"),
                    "expected": "diagnostic_only",
                }
            )
        weights = metric_policy.get("cost_weights")
        if not isinstance(weights, dict):
            errors.append({"field": "metric_policy.cost_weights", "reason": "object required"})
        else:
            for field in ("false_positive", "false_negative"):
                try:
                    value = parse_float(weights.get(field))
                except ClassificationMetricError as error:
                    errors.append(
                        {
                            "field": f"metric_policy.cost_weights.{field}",
                            "reason": str(error),
                        }
                    )
                    continue
                if value < 0:
                    errors.append(
                        {
                            "field": f"metric_policy.cost_weights.{field}",
                            "reason": "non-negative cost required",
                        }
                    )

    if not isinstance(threshold_policy, dict):
        errors.append({"field": "threshold_policy", "reason": "object required"})
    else:
        if threshold_policy.get("selection_data") != "validation":
            errors.append(
                {
                    "field": "threshold_policy.selection_data",
                    "observed": threshold_policy.get("selection_data"),
                    "expected": "validation",
                }
            )
        if threshold_policy.get("rule") != "min_error_cost_under_offer_budget":
            errors.append(
                {
                    "field": "threshold_policy.rule",
                    "observed": threshold_policy.get("rule"),
                    "expected": "min_error_cost_under_offer_budget",
                }
            )

    try:
        parsed_budget = parse_int(budget.get("max_actions") if isinstance(budget, dict) else None)
    except ClassificationMetricError as error:
        errors.append({"field": "decision_budget.max_actions", "reason": str(error)})
    else:
        if parsed_budget <= 0:
            errors.append(
                {
                    "field": "decision_budget.max_actions",
                    "reason": "positive budget required",
                }
            )

    if errors:
        return failed(
            "metric_and_threshold_policy_are_declared",
            len(errors),
            "precision/recall/PR metrics, validation threshold and numeric FP/FN costs",
            errors,
        )
    return passed(
        "metric_and_threshold_policy_are_declared",
        {
            "primary_metric": metric_policy["primary_metric"],
            "selection_data": threshold_policy["selection_data"],
            "max_actions": parsed_budget,
        },
        "metric policy aligned with business decision",
    )


def validate_score_schema_and_coverage(
    manifest: list[dict[str, str]],
    manifest_columns: list[str],
    scores: list[dict[str, str]],
    score_columns: list[str],
) -> dict[str, Any]:
    missing_manifest_columns = sorted(REQUIRED_MANIFEST_COLUMNS - set(manifest_columns))
    missing_score_columns = sorted(REQUIRED_SCORE_COLUMNS - set(score_columns))
    if missing_manifest_columns or missing_score_columns:
        return failed(
            "score_schema_and_coverage",
            {
                "manifest_missing": missing_manifest_columns,
                "score_missing": missing_score_columns,
            },
            "required manifest and score columns",
        )

    manifest_ids = {row["snapshot_id"] for row in manifest}
    score_ids = [row["snapshot_id"] for row in scores]
    errors: list[dict[str, Any]] = []
    duplicate_ids = sorted(
        snapshot_id for snapshot_id, count in Counter(score_ids).items() if count > 1
    )
    missing_ids = sorted(manifest_ids - set(score_ids))
    extra_ids = sorted(set(score_ids) - manifest_ids)
    model_ids = sorted({row["model_id"] for row in scores if row.get("model_id")})

    if duplicate_ids:
        errors.append(
            {
                "field": "snapshot_id",
                "reason": "duplicate score rows",
                "sample": duplicate_ids,
            }
        )
    if missing_ids:
        errors.append(
            {
                "field": "snapshot_id",
                "reason": "split rows missing scores",
                "sample": missing_ids,
            }
        )
    if extra_ids:
        errors.append(
            {
                "field": "snapshot_id",
                "reason": "scores for rows outside split manifest",
                "sample": extra_ids,
            }
        )
    if len(model_ids) != 1:
        errors.append(
            {
                "field": "model_id",
                "reason": "exactly one candidate model is expected in this lesson",
                "observed": model_ids,
            }
        )

    for row in scores:
        snapshot_id = row.get("snapshot_id")
        try:
            score = parse_float(row.get("score"))
        except ClassificationMetricError as error:
            errors.append({"snapshot_id": snapshot_id, "field": "score", "reason": str(error)})
            continue
        if score < 0 or score > 1:
            errors.append(
                {
                    "snapshot_id": snapshot_id,
                    "field": "score",
                    "reason": "probability score must be between 0 and 1",
                    "observed": score,
                }
            )
        if row.get("score_type") != "churn_risk_probability":
            errors.append(
                {
                    "snapshot_id": snapshot_id,
                    "field": "score_type",
                    "expected": "churn_risk_probability",
                    "observed": row.get("score_type"),
                }
            )
        if row.get("trained_on_split") != "train":
            errors.append(
                {
                    "snapshot_id": snapshot_id,
                    "field": "trained_on_split",
                    "expected": "train",
                    "observed": row.get("trained_on_split"),
                }
            )

    if errors:
        return failed(
            "score_schema_and_coverage",
            len(errors),
            "one probability score per split manifest row",
            errors[:10],
        )
    return passed(
        "score_schema_and_coverage",
        {"score_rows": len(scores), "model_id": model_ids[0]},
        "one probability score per split manifest row",
    )


def validate_labels_and_roles(
    spec: dict[str, Any],
    labels: list[dict[str, str]],
    label_columns: list[str],
    manifest: list[dict[str, str]],
) -> dict[str, Any]:
    missing_label_columns = sorted(REQUIRED_LABEL_COLUMNS - set(label_columns))
    if missing_label_columns:
        return failed(
            "labels_and_split_roles_support_metrics",
            {"labels_missing": missing_label_columns},
            "required label columns",
        )

    column = target_column(spec)
    label_by_snapshot = {row["snapshot_id"]: row for row in labels}
    class_counts_by_split: dict[str, Counter[bool]] = defaultdict(Counter)
    errors: list[dict[str, Any]] = []

    for row in manifest:
        split = row.get("split", "")
        if split in ROLE_BY_SPLIT and row.get("role") != ROLE_BY_SPLIT[split]:
            errors.append(
                {
                    "snapshot_id": row.get("snapshot_id"),
                    "field": "role",
                    "split": split,
                    "observed": row.get("role"),
                    "expected": ROLE_BY_SPLIT[split],
                }
            )
        label = label_by_snapshot.get(row["snapshot_id"])
        if label is None:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "ml_labels.snapshot_id",
                    "reason": "label missing for split row",
                }
            )
            continue
        try:
            if not parse_bool(label.get("label_window_complete")):
                errors.append(
                    {
                        "snapshot_id": row["snapshot_id"],
                        "field": "label_window_complete",
                        "reason": "metric row requires complete target horizon",
                    }
                )
            class_counts_by_split[split][parse_bool(label[column])] += 1
        except ClassificationMetricError as error:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": column,
                    "reason": str(error),
                }
            )

    for split in REPORT_SPLITS:
        counts = class_counts_by_split[split]
        if counts[True] == 0 or counts[False] == 0:
            errors.append(
                {
                    "split": split,
                    "reason": "both positive and negative labels are required for PR/FPR metrics",
                    "class_counts": {"positive": counts[True], "negative": counts[False]},
                }
            )

    if errors:
        return failed(
            "labels_and_split_roles_support_metrics",
            len(errors),
            "complete labels, validation threshold role and final test role",
            errors[:10],
        )
    return passed(
        "labels_and_split_roles_support_metrics",
        {
            split: {
                "positive": class_counts_by_split[split][True],
                "negative": class_counts_by_split[split][False],
            }
            for split in REPORT_SPLITS
        },
        "complete labels and split roles support metric evaluation",
    )


def build_records(
    *,
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
    labels: list[dict[str, str]],
    manifest: list[dict[str, str]],
    scores: list[dict[str, str]],
) -> list[dict[str, Any]]:
    column = target_column(spec)
    snapshot_by_id = {row["snapshot_id"]: row for row in snapshots}
    label_by_id = {row["snapshot_id"]: row for row in labels}
    score_by_id = {row["snapshot_id"]: row for row in scores}
    records: list[dict[str, Any]] = []
    for row in manifest:
        snapshot_id = row["snapshot_id"]
        label = label_by_id.get(snapshot_id)
        score = score_by_id.get(snapshot_id)
        if label is None or score is None:
            continue
        try:
            target = parse_bool(label[column])
            probability = parse_float(score["score"])
        except (ClassificationMetricError, KeyError):
            continue
        snapshot = snapshot_by_id.get(snapshot_id, {})
        records.append(
            {
                "snapshot_id": snapshot_id,
                "user_id": row["user_id"],
                "split": row["split"],
                "prediction_time": row["prediction_time"],
                "target": target,
                "score": probability,
                "model_id": score.get("model_id", ""),
                "segment_id": snapshot.get("segment_id", ""),
                "platform": snapshot.get("platform", ""),
                "country": snapshot.get("country", ""),
            }
        )
    return records


def confusion_at_threshold(
    records: list[dict[str, Any]],
    *,
    threshold: float,
    budget: int,
    weights: dict[str, float],
) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for row in records:
        predicted_positive = row["score"] >= threshold
        if predicted_positive and row["target"]:
            tp += 1
        elif predicted_positive and not row["target"]:
            fp += 1
        elif not predicted_positive and row["target"]:
            fn += 1
        else:
            tn += 1

    offered = tp + fp
    total = tp + fp + tn + fn
    total_cost = fp * weights["false_positive"] + fn * weights["false_negative"]
    return {
        "threshold": rounded(threshold),
        "rows": total,
        "offer_count": offered,
        "budget": budget,
        "budget_status": "within_budget" if offered <= budget else "over_budget",
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": safe_ratio(tp, tp + fp),
        "recall": safe_ratio(tp, tp + fn),
        "fpr": safe_ratio(fp, fp + tn),
        "fnr": safe_ratio(fn, tp + fn),
        "accuracy": safe_ratio(tp + tn, total),
        "total_error_cost": rounded(total_cost),
        "average_error_cost": safe_ratio(total_cost, total),
    }


def threshold_candidates(records: list[dict[str, Any]]) -> list[float]:
    scores = {row["score"] for row in records}
    scores.add(1.0)
    return sorted(scores, reverse=True)


def threshold_sweep(
    records: list[dict[str, Any]], *, budget: int, weights: dict[str, float]
) -> list[dict[str, Any]]:
    return [
        confusion_at_threshold(records, threshold=threshold, budget=budget, weights=weights)
        for threshold in threshold_candidates(records)
    ]


def selection_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    precision = row["precision"] if row["precision"] is not None else -1.0
    recall = row["recall"] if row["recall"] is not None else -1.0
    return (row["total_error_cost"], -precision, -recall, row["threshold"])


def select_threshold(sweep: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [row for row in sweep if row["budget_status"] == "within_budget"]
    if not eligible:
        return None
    return sorted(eligible, key=selection_sort_key)[0]


def average_precision(records: list[dict[str, Any]]) -> float | None:
    positives = sum(1 for row in records if row["target"])
    if positives == 0:
        return None
    tp = 0
    fp = 0
    previous_recall = 0.0
    area = 0.0
    for row in sorted(records, key=lambda item: (-item["score"], item["snapshot_id"])):
        if row["target"]:
            tp += 1
        else:
            fp += 1
        recall = tp / positives
        precision = tp / (tp + fp)
        if row["target"]:
            area += (recall - previous_recall) * precision
            previous_recall = recall
    return rounded(area)


def roc_auc(records: list[dict[str, Any]]) -> float | None:
    positive_scores = [row["score"] for row in records if row["target"]]
    negative_scores = [row["score"] for row in records if not row["target"]]
    if not positive_scores or not negative_scores:
        return None
    wins = 0.0
    for positive in positive_scores:
        for negative in negative_scores:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return rounded(wins / (len(positive_scores) * len(negative_scores)))


def log_loss(records: list[dict[str, Any]]) -> float | None:
    if not records:
        return None
    epsilon = 1e-15
    total = 0.0
    for row in records:
        score = min(max(row["score"], epsilon), 1 - epsilon)
        target = 1.0 if row["target"] else 0.0
        total -= target * math.log(score) + (1 - target) * math.log(1 - score)
    return rounded(total / len(records))


def ranking_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_split[row["split"]].append(row)
    return {
        split: {
            "average_precision": average_precision(split_records),
            "roc_auc": roc_auc(split_records),
            "log_loss": log_loss(split_records),
        }
        for split, split_records in sorted(by_split.items())
        if split in REPORT_SPLITS
    }


def build_summary(
    spec: dict[str, Any],
    records: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    weights = cost_weights(spec)
    budget = offer_budget(spec)
    records_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        records_by_split[row["split"]].append(row)

    validation_sweep = threshold_sweep(
        records_by_split["validation"], budget=budget, weights=weights
    )
    selected = select_threshold(validation_sweep)
    if selected is None:
        checks.append(
            failed(
                "threshold_can_be_selected_on_validation",
                "none",
                "at least one validation threshold within offer budget",
            )
        )
        selected_threshold = None
        selected_by_split: dict[str, Any] = {}
    else:
        selected_threshold = selected["threshold"]
        checks.append(
            passed(
                "threshold_can_be_selected_on_validation",
                {
                    "threshold": selected_threshold,
                    "selection_data": "validation",
                    "validation_total_error_cost": selected["total_error_cost"],
                },
                "threshold selected on validation only",
            )
        )
        selected_by_split = {
            split: confusion_at_threshold(
                records_by_split[split],
                threshold=float(selected_threshold),
                budget=budget,
                weights=weights,
            )
            for split in REPORT_SPLITS
        }

    rows_by_split = Counter(row["split"] for row in records)
    minimum_report_rows = min((rows_by_split[split] for split in REPORT_SPLITS), default=0)
    if minimum_report_rows < 20:
        checks.append(
            failed(
                "tiny_metric_sample_expected",
                minimum_report_rows,
                "production metric policy needs larger validation/test samples",
                [{"rows_by_split": {split: rows_by_split[split] for split in REPORT_SPLITS}}],
                severity="warning",
            )
        )

    model_ids = sorted({row["model_id"] for row in records if row.get("model_id")})
    return {
        "problem_id": spec.get("problem_id"),
        "model_id": model_ids[0] if len(model_ids) == 1 else None,
        "offer_budget": budget,
        "cost_weights": weights,
        "threshold_selection_rule": "min_error_cost_under_offer_budget",
        "threshold_selected_on": "validation",
        "selected_threshold": selected_threshold,
        "validation_threshold_sweep": validation_sweep,
        "metrics_at_selected_threshold": selected_by_split,
        "ranking_metrics_by_split": ranking_metrics(records),
        "rows_by_split": {split: rows_by_split[split] for split in ("train", "validation", "test")},
        "accuracy_role": "diagnostic_only",
        "readiness_status": "ready_for_preprocessing_and_baselines",
    }


def build_report(
    spec: dict[str, Any], checks: list[dict[str, Any]], summary: dict[str, Any]
) -> dict[str, Any]:
    errors = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warnings = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    return {
        "audit_id": "classification-metric-policy-audit",
        "problem_id": spec.get("problem_id"),
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "checks": checks,
        "summary": {
            **summary,
            "checks_total": len(checks),
            "checks_failed": len(errors) + len(warnings),
            "blocking_errors": [check["id"] for check in errors],
            "warnings": [check["id"] for check in warnings],
        },
    }


def run(
    *,
    spec_path: Path,
    snapshots_path: Path,
    labels_path: Path,
    manifest_path: Path,
    scores_path: Path,
) -> dict[str, Any]:
    spec = read_json(spec_path)
    snapshots, _snapshot_columns = read_csv(snapshots_path)
    labels, label_columns = read_csv(labels_path)
    manifest, manifest_columns = read_csv(manifest_path)
    scores, score_columns = read_csv(scores_path)
    checks = [
        validate_metric_policy(spec),
        validate_score_schema_and_coverage(manifest, manifest_columns, scores, score_columns),
        validate_labels_and_roles(spec, labels, label_columns, manifest),
    ]
    records = build_records(
        spec=spec,
        snapshots=snapshots,
        labels=labels,
        manifest=manifest,
        scores=scores,
    )
    summary = build_summary(spec, records, checks)
    return build_report(spec, checks, summary)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate binary classification metrics and threshold policy."
    )
    parser.add_argument("--spec", required=True, type=Path, help="Path to problem_spec.json.")
    parser.add_argument(
        "--snapshots", required=True, type=Path, help="Path to scoring snapshots CSV."
    )
    parser.add_argument("--labels", required=True, type=Path, help="Path to labels CSV.")
    parser.add_argument("--manifest", required=True, type=Path, help="Path to split manifest CSV.")
    parser.add_argument("--scores", required=True, type=Path, help="Path to candidate scores CSV.")
    parser.add_argument("--output", type=Path, help="Optional path for JSON report.")
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return non-zero when warnings are present.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = run(
        spec_path=args.spec,
        snapshots_path=args.snapshots,
        labels_path=args.labels,
        manifest_path=args.manifest,
        scores_path=args.scores,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
