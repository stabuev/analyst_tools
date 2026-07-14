from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
DATA_ROOT = PHASE_16_ROOT / "data" / "tiny"

DEFAULT_CONTRACT_PATH = DATA_ROOT / "categorical_feature_contract.json"
DEFAULT_CATBOOST_SPEC_PATH = DATA_ROOT / "catboost_model_spec.json"
DEFAULT_FEATURES_PATH = UPSTREAM_DATA_ROOT / "ml_raw_features.csv"
DEFAULT_MANIFEST_PATH = UPSTREAM_DATA_ROOT / "ml_split_manifest.csv"
DEFAULT_FEATURE_AVAILABILITY_PATH = (
    PHASE_15_ROOT / "13-leakage" / "outputs" / "feature_availability_report.csv"
)
DEFAULT_CATBOOST_REPORT_PATH = PHASE_16_ROOT / "01-catboost" / "outputs" / "catboost_report.json"

GENERATED_AT = "2026-07-03T13:00:00+03:00"


def portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


class CategoricalFeatureError(ValueError):
    """Raised when categorical feature audit inputs cannot be parsed."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows([{field: csv_ready(row.get(field)) for field in fieldnames} for row in rows])


def csv_ready(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise CategoricalFeatureError(f"Cannot parse boolean value: {value!r}")


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


def blocking_errors(checks: list[dict[str, Any]]) -> list[str]:
    return [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]


def warning_ids(checks: list[dict[str, Any]]) -> list[str]:
    return [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]


def validate_required_files(paths: dict[str, Path]) -> dict[str, Any]:
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        return failed("input_files_are_present", sorted(paths), "all required input files", missing)
    return passed("input_files_are_present", sorted(paths), "all required input files")


def contract_feature_names(contract: dict[str, Any]) -> list[str]:
    features = contract.get("categorical_features")
    if not isinstance(features, list):
        raise CategoricalFeatureError("categorical_features must be a list")
    names = []
    for item in features:
        if not isinstance(item, dict) or not item.get("feature_name"):
            raise CategoricalFeatureError("each categorical feature must declare feature_name")
        names.append(str(item["feature_name"]))
    return names


def feature_policy_by_name(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["feature_name"]): item for item in contract.get("categorical_features", [])}


def validate_contract_handoff(
    *,
    contract: dict[str, Any],
    catboost_spec: dict[str, Any],
    catboost_report: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    required = {
        "categorical_audit_id",
        "problem_id",
        "catboost_baseline_id",
        "catboost_model_id",
        "fit_split",
        "selection_split",
        "final_holdout_split",
        "categorical_features",
        "missing_category_token",
        "availability_policy",
        "known_bad_categorical_candidates",
        "output",
    }
    missing = sorted(required - set(contract))
    if missing:
        errors.append({"field": "root", "missing": missing})

    expected_identity = {
        "problem_id": catboost_spec.get("problem_id"),
        "catboost_baseline_id": catboost_spec.get("catboost_baseline_id"),
        "catboost_model_id": catboost_spec.get("candidate", {}).get("model_id"),
        "fit_split": "train",
        "selection_split": "validation",
        "final_holdout_split": "test",
    }
    for field, expected in expected_identity.items():
        if contract.get(field) != expected:
            errors.append({"field": field, "observed": contract.get(field), "expected": expected})

    report_summary = catboost_report.get("summary", {})
    if catboost_report.get("valid") is not True:
        errors.append({"field": "catboost_report.valid", "observed": catboost_report.get("valid"), "expected": True})
    if report_summary.get("readiness_status") != "ready_for_categorical_feature_lesson":
        errors.append(
            {
                "field": "catboost_report.summary.readiness_status",
                "observed": report_summary.get("readiness_status"),
                "expected": "ready_for_categorical_feature_lesson",
            }
        )

    contract_features = contract_feature_names(contract)
    if len(contract_features) != len(set(contract_features)):
        duplicates = sorted(name for name in set(contract_features) if contract_features.count(name) > 1)
        errors.append({"field": "categorical_features", "duplicates": duplicates})

    spec_features = catboost_spec.get("feature_contract", {}).get("categorical_features", [])
    report_features = report_summary.get("cat_features", [])
    if contract_features != spec_features:
        errors.append(
            {
                "field": "categorical_features",
                "observed": contract_features,
                "expected": spec_features,
            }
        )
    if contract_features != report_features:
        errors.append(
            {
                "field": "catboost_report.summary.cat_features",
                "observed": report_features,
                "expected": contract_features,
            }
        )

    missing_policies = []
    for item in contract.get("categorical_features", []):
        if not item.get("missing_policy") or not item.get("unknown_category_policy"):
            missing_policies.append(item.get("feature_name"))
    if missing_policies:
        errors.append({"field": "feature policies", "missing": sorted(missing_policies)})

    if errors:
        checks.append(
            failed(
                "categorical_contract_matches_catboost_handoff",
                errors,
                "same problem, CatBoost model and cat_features as 16/01",
            )
        )
    else:
        checks.append(
            passed(
                "categorical_contract_matches_catboost_handoff",
                {
                    "categorical_audit_id": contract["categorical_audit_id"],
                    "catboost_baseline_id": contract["catboost_baseline_id"],
                    "cat_features": contract_features,
                },
            )
        )
    return checks


def join_features_with_manifest(
    features: list[dict[str, str]],
    manifest: list[dict[str, str]],
) -> list[dict[str, str]]:
    by_id = {row["snapshot_id"]: row for row in manifest}
    joined: list[dict[str, str]] = []
    for row in features:
        snapshot_id = row.get("snapshot_id")
        if snapshot_id not in by_id:
            continue
        manifest_row = by_id[snapshot_id]
        joined.append(
            {
                **row,
                "split": manifest_row["split"],
                "split_order": manifest_row["split_order"],
                "prediction_time": manifest_row["prediction_time"],
                "user_id": manifest_row["user_id"],
            }
        )
    return sorted(joined, key=lambda row: (int(row["split_order"]), row["snapshot_id"]))


def normalize_category(value: Any, missing_token: str) -> tuple[str, bool]:
    if value is None or str(value) == "":
        return missing_token, True
    return str(value), False


def build_inventory(
    rows: list[dict[str, str]],
    features: list[str],
    policy_by_feature: dict[str, dict[str, Any]],
    missing_token: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    counts: dict[str, Counter[tuple[str, bool, str]]] = defaultdict(Counter)
    train_values: dict[str, set[str]] = {feature: set() for feature in features}

    for row in rows:
        split = row["split"]
        for feature in features:
            category, is_missing = normalize_category(row.get(feature), missing_token)
            counts[feature][(category, is_missing, split)] += 1
            if split == "train":
                train_values[feature].add(category)

    inventory: list[dict[str, Any]] = []
    for feature in features:
        categories = sorted({category for category, _is_missing, _split in counts[feature]})
        distinct_total = len(categories)
        policy = policy_by_feature[feature]
        max_distinct = int(policy.get("max_distinct_values_tiny", 999999))
        min_train_count = int(policy.get("min_train_count_for_stable_level", 1))
        for category in categories:
            train_count = sum(count for (value, _missing, split), count in counts[feature].items() if value == category and split == "train")
            validation_count = sum(
                count for (value, _missing, split), count in counts[feature].items() if value == category and split == "validation"
            )
            test_count = sum(count for (value, _missing, split), count in counts[feature].items() if value == category and split == "test")
            missing_value = any(is_missing for value, is_missing, _split in counts[feature] if value == category)
            unseen_in_train = category not in train_values[feature]
            rare_in_train = 0 < train_count < min_train_count
            inventory.append(
                {
                    "feature_name": feature,
                    "category_value": category,
                    "semantic_type": policy.get("semantic_type", ""),
                    "train_count": train_count,
                    "validation_count": validation_count,
                    "test_count": test_count,
                    "total_count": train_count + validation_count + test_count,
                    "seen_in_train": not unseen_in_train,
                    "unseen_in_train": unseen_in_train,
                    "missing_value": missing_value,
                    "rare_in_train": rare_in_train,
                    "distinct_values_for_feature": distinct_total,
                    "high_cardinality_feature": distinct_total > max_distinct,
                    "missing_policy": policy.get("missing_policy", ""),
                    "unknown_category_policy": policy.get("unknown_category_policy", ""),
                }
            )

    unknowns: list[dict[str, Any]] = []
    for row in rows:
        if row["split"] == "train":
            continue
        for feature in features:
            category, is_missing = normalize_category(row.get(feature), missing_token)
            if category not in train_values[feature]:
                policy = policy_by_feature[feature]
                unknowns.append(
                    {
                        "snapshot_id": row["snapshot_id"],
                        "split": row["split"],
                        "feature_name": feature,
                        "category_value": category,
                        "missing_value": is_missing,
                        "seen_in_train": False,
                        "policy_action": "allow_native_catboost_unseen_value_and_monitor",
                        "unknown_category_policy": policy.get("unknown_category_policy", ""),
                    }
                )
    return inventory, unknowns


def validate_feature_table(
    rows: list[dict[str, str]],
    features: list[str],
) -> list[dict[str, Any]]:
    if not rows:
        return [failed("categorical_feature_table_has_split_rows", 0, "> 0 joined rows")]

    missing_features = sorted(feature for feature in features if feature not in rows[0])
    observed_splits = sorted({row["split"] for row in rows})
    checks: list[dict[str, Any]] = []
    if missing_features:
        checks.append(failed("categorical_features_exist_in_raw_table", missing_features, "all contract features"))
    else:
        checks.append(passed("categorical_features_exist_in_raw_table", features))

    if observed_splits == ["test", "train", "validation"]:
        checks.append(passed("categorical_feature_table_has_split_rows", observed_splits))
    else:
        checks.append(failed("categorical_feature_table_has_split_rows", observed_splits, ["train", "validation", "test"]))
    return checks


def build_leakage_audit(
    *,
    selected_features: list[str],
    known_bad_candidates: list[str],
    availability_rows: list[dict[str, str]],
    availability_policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_feature = {row["feature_name"]: row for row in availability_rows}
    audit_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    names_to_audit = selected_features + [name for name in known_bad_candidates if name not in selected_features]

    for feature in names_to_audit:
        row = by_feature.get(feature)
        selected = feature in selected_features
        if row is None:
            audit_rows.append(
                {
                    "feature_name": feature,
                    "selected_as_cat_feature": selected,
                    "source_id": "",
                    "timing": "",
                    "risk_type": "missing_availability_record",
                    "used_in_delivery_model": False,
                    "source_allowed_by_problem": False,
                    "timing_allowed_by_policy": False,
                    "candidate_allowed": False,
                    "decision": "blocked_missing_availability_record" if selected else "rejected_missing_availability_record",
                    "blocking_if_selected": selected,
                    "notes": "",
                }
            )
            if selected:
                errors.append({"feature_name": feature, "reason": "missing availability record"})
            continue

        source_allowed = parse_bool(row["source_allowed_by_problem"])
        timing_allowed = parse_bool(row["timing_allowed_by_policy"])
        candidate_allowed = parse_bool(row["candidate_allowed"])
        used_in_delivery = parse_bool(row["used_in_delivery_model"])
        selected_is_allowed = True
        reasons = []
        if availability_policy.get("require_used_in_delivery_model") and not used_in_delivery:
            selected_is_allowed = False
            reasons.append("not used in delivery model")
        if availability_policy.get("require_source_allowed_by_problem") and not source_allowed:
            selected_is_allowed = False
            reasons.append("source forbidden by problem spec")
        if availability_policy.get("require_timing_allowed_by_policy") and not timing_allowed:
            selected_is_allowed = False
            reasons.append("timing after prediction time")
        if availability_policy.get("require_candidate_allowed") and not candidate_allowed:
            selected_is_allowed = False
            reasons.append("candidate not allowed by leakage policy")

        decision = "allowed_delivery_cat_feature"
        if not selected:
            decision = "rejected_known_bad_candidate"
        elif not selected_is_allowed:
            decision = "blocked_selected_leaky_cat_feature"
            errors.append({"feature_name": feature, "reasons": reasons, "risk_type": row["risk_type"]})

        audit_rows.append(
            {
                "feature_name": feature,
                "selected_as_cat_feature": selected,
                "source_id": row["source_id"],
                "timing": row["timing"],
                "risk_type": row["risk_type"],
                "used_in_delivery_model": used_in_delivery,
                "source_allowed_by_problem": source_allowed,
                "timing_allowed_by_policy": timing_allowed,
                "candidate_allowed": candidate_allowed,
                "decision": decision,
                "blocking_if_selected": selected and not selected_is_allowed,
                "notes": row.get("notes", ""),
            }
        )
    return audit_rows, errors


def inventory_warnings(inventory: list[dict[str, Any]], unknowns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    high_card_features = sorted({row["feature_name"] for row in inventory if row["high_cardinality_feature"]})
    rare_levels = [
        {"feature_name": row["feature_name"], "category_value": row["category_value"], "train_count": row["train_count"]}
        for row in inventory
        if row["rare_in_train"]
    ]
    missing_rows = sum(row["total_count"] for row in inventory if row["missing_value"])

    if unknowns:
        checks.append(
            failed(
                "unknown_categories_are_monitored_not_silent",
                len(unknowns),
                "0 unknown validation/test category rows",
                unknowns[:5],
                severity="warning",
            )
        )
    else:
        checks.append(passed("unknown_categories_are_monitored_not_silent", 0))

    if high_card_features:
        checks.append(
            failed(
                "high_cardinality_features_are_flagged",
                high_card_features,
                "no feature exceeds tiny distinct threshold",
                severity="warning",
            )
        )
    else:
        checks.append(passed("high_cardinality_features_are_flagged", []))

    if rare_levels:
        checks.append(
            failed(
                "rare_train_category_levels_are_visible",
                len(rare_levels),
                "0 rare train category levels",
                rare_levels[:8],
                severity="warning",
            )
        )
    else:
        checks.append(passed("rare_train_category_levels_are_visible", 0))

    if missing_rows:
        checks.append(
            failed(
                "missing_categories_follow_declared_policy",
                missing_rows,
                "0 missing categorical rows or declared explicit missing category",
                severity="warning",
            )
        )
    else:
        checks.append(passed("missing_categories_follow_declared_policy", 0))
    return checks


def failure_report(error_id: str, message: str) -> dict[str, Any]:
    check = failed(error_id, message, "loadable categorical feature audit inputs")
    return {
        "valid": False,
        "categorical_audit_id": None,
        "problem_id": None,
        "summary": {
            "blocking_errors": [error_id],
            "warnings": [],
            "readiness_status": "blocked_by_categorical_feature_contract",
            "generated_at": GENERATED_AT,
        },
        "checks": [check],
        "inventory": [],
        "unknowns": [],
        "leakage_audit": [],
        "serialized_contract": {},
    }


def run(
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    catboost_spec_path: Path = DEFAULT_CATBOOST_SPEC_PATH,
    catboost_report_path: Path = DEFAULT_CATBOOST_REPORT_PATH,
    features_path: Path = DEFAULT_FEATURES_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    feature_availability_path: Path = DEFAULT_FEATURE_AVAILABILITY_PATH,
) -> dict[str, Any]:
    input_paths = {
        "categorical_feature_contract": contract_path,
        "catboost_model_spec": catboost_spec_path,
        "catboost_report": catboost_report_path,
        "features": features_path,
        "manifest": manifest_path,
        "feature_availability": feature_availability_path,
    }
    file_check = validate_required_files(input_paths)
    if not file_check["valid"]:
        return failure_report(file_check["id"], ", ".join(file_check["sample"]))

    try:
        contract = read_json(contract_path)
        catboost_spec = read_json(catboost_spec_path)
        catboost_report = read_json(catboost_report_path)
        features = read_csv(features_path)
        manifest = read_csv(manifest_path)
        availability_rows = read_csv(feature_availability_path)
        cat_features = contract_feature_names(contract)
        policy_by_feature = feature_policy_by_name(contract)

        checks = [file_check]
        checks.extend(
            validate_contract_handoff(
                contract=contract,
                catboost_spec=catboost_spec,
                catboost_report=catboost_report,
            )
        )
        joined = join_features_with_manifest(features, manifest)
        checks.extend(validate_feature_table(joined, cat_features))
        leakage_audit, leakage_errors = build_leakage_audit(
            selected_features=cat_features,
            known_bad_candidates=list(contract.get("known_bad_categorical_candidates", [])),
            availability_rows=availability_rows,
            availability_policy=contract.get("availability_policy", {}),
        )
        if leakage_errors:
            checks.append(
                failed(
                    "selected_categorical_features_pass_leakage_policy",
                    leakage_errors,
                    "selected cat features are delivery features available before prediction",
                )
            )
        else:
            checks.append(
                passed(
                    "selected_categorical_features_pass_leakage_policy",
                    cat_features,
                    "delivery features available before prediction",
                )
            )

        inventory: list[dict[str, Any]] = []
        unknowns: list[dict[str, Any]] = []
        if not blocking_errors(checks):
            inventory, unknowns = build_inventory(
                joined,
                cat_features,
                policy_by_feature,
                contract["missing_category_token"],
            )
            checks.append(
                passed(
                    "category_inventory_covers_all_splits",
                    {
                        "feature_count": len(cat_features),
                        "inventory_rows": len(inventory),
                        "splits": sorted({row["split"] for row in joined}),
                    },
                )
            )
            checks.extend(inventory_warnings(inventory, unknowns))

        warnings = warning_ids(checks)
        blocking = blocking_errors(checks)
        high_card_features = sorted({row["feature_name"] for row in inventory if row.get("high_cardinality_feature")})
        rare_level_count = sum(1 for row in inventory if row.get("rare_in_train"))
        missing_category_row_count = sum(row["total_count"] for row in inventory if row.get("missing_value"))
        serialized_contract = {
            "categorical_audit_id": contract.get("categorical_audit_id"),
            "problem_id": contract.get("problem_id"),
            "catboost_baseline_id": contract.get("catboost_baseline_id"),
            "catboost_model_id": contract.get("catboost_model_id"),
            "cat_features": cat_features,
            "missing_category_token": contract.get("missing_category_token"),
            "policies": contract.get("categorical_features", []),
            "availability_policy": contract.get("availability_policy", {}),
            "category_summary": {
                "inventory_rows": len(inventory),
                "unknown_category_row_count": len(unknowns),
                "high_cardinality_features": high_card_features,
                "rare_level_count": rare_level_count,
                "missing_category_row_count": missing_category_row_count,
            },
            "leakage_summary": {
                "selected_feature_count": len(cat_features),
                "known_bad_candidate_count": len(contract.get("known_bad_categorical_candidates", [])),
                "blocked_selected_feature_count": len(leakage_errors),
            },
            "upstream_handoff": {
                "catboost_report": portable_path(catboost_report_path),
                "catboost_readiness_status": catboost_report.get("summary", {}).get("readiness_status"),
            },
            "output": contract.get("output", {}),
        }
        valid = not blocking
        summary = {
            "categorical_audit_id": contract.get("categorical_audit_id"),
            "problem_id": contract.get("problem_id"),
            "catboost_baseline_id": contract.get("catboost_baseline_id"),
            "catboost_model_id": contract.get("catboost_model_id"),
            "cat_features": cat_features,
            "feature_count": len(cat_features),
            "inventory_row_count": len(inventory),
            "unknown_category_row_count": len(unknowns),
            "unknown_feature_count": len({row["feature_name"] for row in unknowns}),
            "missing_category_row_count": missing_category_row_count,
            "high_cardinality_feature_count": len(high_card_features),
            "rare_level_count": rare_level_count,
            "selected_leaky_feature_count": len(leakage_errors),
            "blocking_errors": blocking,
            "warnings": warnings,
            "readiness_status": "ready_for_early_stopping_lesson" if valid else "blocked_by_categorical_feature_contract",
            "generated_at": GENERATED_AT,
        }
        return {
            "valid": valid,
            "categorical_audit_id": contract.get("categorical_audit_id"),
            "problem_id": contract.get("problem_id"),
            "summary": summary,
            "checks": checks,
            "inventory": inventory,
            "unknowns": unknowns,
            "leakage_audit": leakage_audit,
            "serialized_contract": serialized_contract,
        }
    except (CategoricalFeatureError, OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return failure_report("categorical_feature_audit_runtime_error", str(exc))


INVENTORY_FIELDS = [
    "feature_name",
    "category_value",
    "semantic_type",
    "train_count",
    "validation_count",
    "test_count",
    "total_count",
    "seen_in_train",
    "unseen_in_train",
    "missing_value",
    "rare_in_train",
    "distinct_values_for_feature",
    "high_cardinality_feature",
    "missing_policy",
    "unknown_category_policy",
]

UNKNOWNS_FIELDS = [
    "snapshot_id",
    "split",
    "feature_name",
    "category_value",
    "missing_value",
    "seen_in_train",
    "policy_action",
    "unknown_category_policy",
]

LEAKAGE_FIELDS = [
    "feature_name",
    "selected_as_cat_feature",
    "source_id",
    "timing",
    "risk_type",
    "used_in_delivery_model",
    "source_allowed_by_problem",
    "timing_allowed_by_policy",
    "candidate_allowed",
    "decision",
    "blocking_if_selected",
    "notes",
]


def write_outputs(result: dict[str, Any], output_dir: Path, output_spec: dict[str, str]) -> None:
    write_json(output_dir / output_spec["report_file"], {k: v for k, v in result.items() if k != "serialized_contract"})
    write_csv(output_dir / output_spec["inventory_file"], result["inventory"], INVENTORY_FIELDS)
    write_csv(output_dir / output_spec["unknowns_file"], result["unknowns"], UNKNOWNS_FIELDS)
    write_csv(output_dir / output_spec["leakage_audit_file"], result["leakage_audit"], LEAKAGE_FIELDS)
    write_json(output_dir / output_spec["serialized_contract_file"], result["serialized_contract"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit CatBoost categorical feature contract.")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--catboost-spec", type=Path, default=DEFAULT_CATBOOST_SPEC_PATH)
    parser.add_argument("--catboost-report", type=Path, default=DEFAULT_CATBOOST_REPORT_PATH)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--feature-availability", type=Path, default=DEFAULT_FEATURE_AVAILABILITY_PATH)
    parser.add_argument("--output-dir", type=Path, default=LESSON_ROOT / "outputs")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(
        contract_path=args.contract,
        catboost_spec_path=args.catboost_spec,
        catboost_report_path=args.catboost_report,
        features_path=args.features,
        manifest_path=args.manifest,
        feature_availability_path=args.feature_availability,
    )
    output_spec = read_json(args.contract).get("output", {}) if args.contract.is_file() else {}
    if output_spec:
        write_outputs(result, args.output_dir, output_spec)

    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "categorical_audit_id": summary.get("categorical_audit_id"),
                "catboost_model_id": summary.get("catboost_model_id"),
                "feature_count": summary.get("feature_count"),
                "inventory_row_count": summary.get("inventory_row_count"),
                "unknown_category_row_count": summary.get("unknown_category_row_count"),
                "high_cardinality_feature_count": summary.get("high_cardinality_feature_count"),
                "selected_leaky_feature_count": summary.get("selected_leaky_feature_count"),
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
