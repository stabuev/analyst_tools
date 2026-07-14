from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

AUDIT_VERSION = "1.0.0"
REQUIRED_CONTRACT_FIELDS = {
    "contract_id",
    "project_id",
    "version",
    "data_as_of",
    "timezone",
    "tables",
    "relationships",
    "analysis_population",
    "public_release_policy",
    "route_policy",
    "route_controls",
    "known_defects",
}
REQUIRED_TABLE_FIELDS = {
    "source_id",
    "path",
    "owner",
    "origin",
    "license",
    "allowed_uses",
    "publication_class",
    "reproducibility",
    "grain",
    "freshness",
    "schema",
}
SUPPORTED_TYPES = {"string", "integer", "float", "boolean", "timestamp"}
PUBLIC_SAMPLE_FIELDS = (
    "as_of_week",
    "segment_id",
    "users",
    "activated_users",
    "activation_rate",
    "support_ticket_count",
    "churned_users",
)
ROUTE_CONTROL_IDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("core_analytics", "standard"): (
        "complete_observation_windows",
        "descriptive_claim_only",
    ),
    ("product_experiments", "standard"): (
        "randomization_unit",
        "assignment_exposure_integrity",
        "srm_check",
    ),
    ("data_analytics_engineering", "standard"): (
        "lineage_complete",
        "freshness_sla",
        "grain_tests",
    ),
    ("decision_science", "causal"): (
        "pre_treatment_covariates",
        "treatment_outcome_timing",
        "post_treatment_exclusion",
    ),
    ("decision_science", "forecast"): (
        "chronological_cutoff",
        "known_at_origin",
        "complete_time_index",
    ),
    ("machine_learning", "baseline"): (
        "prediction_time",
        "label_horizon",
        "split_roles",
        "feature_availability",
    ),
    ("machine_learning", "strong_model"): (
        "prediction_time",
        "label_horizon",
        "split_roles",
        "feature_availability",
    ),
    ("delivery_product", "standard"): (
        "upstream_evidence_only",
        "freshness_visibility",
        "no_hidden_recompute",
    ),
}


class DataContractError(ValueError):
    """Raised when capstone data inputs cannot be parsed."""


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check(
    check_id: str,
    valid: bool,
    *,
    observed: Any,
    expected: Any,
    message: str,
    severity: str = "block",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": bool(valid),
        "observed": observed,
        "expected": expected,
        "message": message,
    }


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DataContractError(f"{source} must contain a JSON object")
    return value


def write_json(path: str | Path, value: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def read_csv(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    with Path(path).open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: str | Path, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
    return target


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise DataContractError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DataContractError(f"{field} must be an ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataContractError(f"{field} must be timezone-aware: {value}")
    return parsed


def load_brief_builder():
    artifact = (
        Path(__file__).resolve().parents[2]
        / "01-problem-selection"
        / "outputs"
        / "capstone_brief_validator.py"
    )
    spec = importlib.util.spec_from_file_location("capstone_brief_validator", artifact)
    if spec is None or spec.loader is None:
        raise DataContractError(f"cannot load upstream brief builder: {artifact}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def default_route_policy(route: str, variant: str) -> dict[str, Any]:
    controls = ROUTE_CONTROL_IDS.get((route, variant))
    if controls is None:
        raise DataContractError(f"unsupported route/variant: {route}/{variant}")
    policies: dict[str, Any] = {}
    for control_id in controls:
        policies[control_id] = {
            "owner": "capstone-author",
            "failure_action": "block_next_stage",
            "documented_before_analysis": True,
        }
    if (route, variant) == ("core_analytics", "standard"):
        policies["complete_observation_windows"].update(
            {
                "source_id": "user_week",
                "column": "window_complete",
                "required_value": True,
            }
        )
        policies["descriptive_claim_only"].update(
            {"allowed_claim_types": ["descriptive", "associational"]}
        )
    return policies


def default_route_controls(route: str, variant: str) -> list[dict[str, Any]]:
    controls = ROUTE_CONTROL_IDS.get((route, variant))
    if controls is None:
        raise DataContractError(f"unsupported route/variant: {route}/{variant}")
    return [
        {
            "id": control_id,
            "evidence_fields": [f"data_contract.route_policy.{control_id}"],
            "policy": "block_next_stage_on_failure",
            "enforced": True,
        }
        for control_id in controls
    ]


def default_contract(project_id: str) -> dict[str, Any]:
    common = {
        "owner": "analytics-platform",
        "origin": "deterministic_synthetic_generator",
        "license": "CC0-1.0",
        "allowed_uses": ["course", "portfolio_public_aggregate"],
        "publication_class": "restricted",
        "reproducibility": {
            "kind": "generated",
            "command": "capstone_data_contract_auditor.py --write-example ...",
        },
    }
    return {
        "contract_id": "weekly-retention-data-v1",
        "project_id": project_id,
        "version": "1.0.0",
        "data_as_of": "2026-01-12T00:00:00Z",
        "timezone": "UTC",
        "tables": [
            {
                **common,
                "source_id": "users",
                "path": "users.csv",
                "grain": {"keys": ["user_id"], "duplicate_policy": "forbid"},
                "freshness": {"timestamp_field": "source_updated_at", "max_age_days": 14},
                "schema": [
                    {
                        "name": "user_id",
                        "type": "string",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "signup_at",
                        "type": "timestamp",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "country",
                        "type": "string",
                        "nullable": False,
                        "classification": "public",
                    },
                    {
                        "name": "plan",
                        "type": "string",
                        "nullable": False,
                        "classification": "public",
                    },
                    {
                        "name": "is_test_user",
                        "type": "boolean",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "source_updated_at",
                        "type": "timestamp",
                        "nullable": False,
                        "classification": "restricted",
                    },
                ],
            },
            {
                **common,
                "source_id": "user_week",
                "path": "user_week.csv",
                "grain": {
                    "keys": ["user_id", "as_of_week"],
                    "duplicate_policy": "forbid",
                },
                "freshness": {"timestamp_field": "source_updated_at", "max_age_days": 14},
                "schema": [
                    {
                        "name": "user_id",
                        "type": "string",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "as_of_week",
                        "type": "timestamp",
                        "nullable": False,
                        "classification": "public",
                    },
                    {
                        "name": "segment_id",
                        "type": "string",
                        "nullable": False,
                        "classification": "public",
                    },
                    {
                        "name": "activation_complete",
                        "type": "boolean",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "support_ticket_count",
                        "type": "integer",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "churned_7d",
                        "type": "boolean",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "window_complete",
                        "type": "boolean",
                        "nullable": False,
                        "classification": "public",
                    },
                    {
                        "name": "source_updated_at",
                        "type": "timestamp",
                        "nullable": False,
                        "classification": "restricted",
                    },
                ],
            },
            {
                **common,
                "source_id": "support_tickets",
                "path": "support_tickets.csv",
                "grain": {"keys": ["ticket_id"], "duplicate_policy": "forbid"},
                "freshness": {"timestamp_field": "source_updated_at", "max_age_days": 14},
                "schema": [
                    {
                        "name": "ticket_id",
                        "type": "string",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "user_id",
                        "type": "string",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "created_at",
                        "type": "timestamp",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "category",
                        "type": "string",
                        "nullable": False,
                        "classification": "public",
                    },
                    {
                        "name": "resolution_hours",
                        "type": "float",
                        "nullable": False,
                        "classification": "restricted",
                    },
                    {
                        "name": "source_updated_at",
                        "type": "timestamp",
                        "nullable": False,
                        "classification": "restricted",
                    },
                ],
            },
        ],
        "relationships": [
            {
                "id": "user_week_to_users",
                "from_source": "user_week",
                "from_keys": ["user_id"],
                "to_source": "users",
                "to_keys": ["user_id"],
                "cardinality": "many_to_one",
                "orphan_policy": "block",
            },
            {
                "id": "support_tickets_to_users",
                "from_source": "support_tickets",
                "from_keys": ["user_id"],
                "to_source": "users",
                "to_keys": ["user_id"],
                "cardinality": "many_to_one",
                "orphan_policy": "block",
            },
        ],
        "analysis_population": {
            "source_id": "user_week",
            "eligibility_column": "window_complete",
            "required_value": True,
        },
        "public_release_policy": {
            "allowed_classifications": ["public", "aggregated"],
            "forbidden_classifications": ["restricted", "secret"],
            "minimum_group_size": 2,
            "sample_grain": ["as_of_week", "segment_id"],
        },
        "route_policy": default_route_policy("core_analytics", "standard"),
        "route_controls": default_route_controls("core_analytics", "standard"),
        "known_defects": [
            {
                "id": "late_support_ticket_delivery",
                "status": "controlled",
                "handling": "freshness gate and rerun before defense",
            }
        ],
    }


def default_rows() -> dict[str, list[dict[str, Any]]]:
    updated = "2026-01-10T12:00:00Z"
    users = [
        {
            "user_id": f"u{index}",
            "signup_at": f"2025-12-{index + 1:02d}T09:00:00Z",
            "country": "RU" if index <= 4 else "KZ",
            "plan": "basic" if index % 2 else "pro",
            "is_test_user": "false",
            "source_updated_at": updated,
        }
        for index in range(1, 9)
    ]
    user_week: list[dict[str, Any]] = []
    support_counts = [2, 1, 3, 0, 0, 1, 0, 1]
    for index in range(1, 9):
        user_week.append(
            {
                "user_id": f"u{index}",
                "as_of_week": "2026-01-05T00:00:00Z",
                "segment_id": "high_touch" if index <= 4 else "self_serve",
                "activation_complete": "true" if index in {1, 2, 5, 6, 7} else "false",
                "support_ticket_count": support_counts[index - 1],
                "churned_7d": "true" if index in {3, 4, 8} else "false",
                "window_complete": "true",
                "source_updated_at": updated,
            }
        )
    tickets = [
        {
            "ticket_id": f"t{index}",
            "user_id": user_id,
            "created_at": f"2026-01-{5 + index:02d}T10:00:00Z",
            "category": category,
            "resolution_hours": resolution,
            "source_updated_at": updated,
        }
        for index, (user_id, category, resolution) in enumerate(
            [
                ("u1", "billing", "2.5"),
                ("u1", "onboarding", "4.0"),
                ("u2", "billing", "1.5"),
                ("u3", "technical", "8.0"),
                ("u3", "technical", "6.0"),
                ("u3", "billing", "3.0"),
                ("u6", "onboarding", "2.0"),
                ("u8", "billing", "5.0"),
            ],
            start=1,
        )
    ]
    return {"users": users, "user_week": user_week, "support_tickets": tickets}


def write_source_csvs(root: Path, contract: dict[str, Any]) -> dict[str, Path]:
    rows_by_source = default_rows()
    paths: dict[str, Path] = {}
    for table in contract["tables"]:
        source_id = table["source_id"]
        rows = rows_by_source[source_id]
        path = root / table["path"]
        fields = [field["name"] for field in table["schema"]]
        write_csv(path, rows, fields)
        paths[source_id] = path
    return paths


def build_dataset_manifest(contract: dict[str, Any], source_root: Path) -> dict[str, Any]:
    resources = []
    for table in contract["tables"]:
        path = source_root / table["path"]
        rows, columns = read_csv(path)
        resources.append(
            {
                "source_id": table["source_id"],
                "path": table["path"],
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "rows": len(rows),
                "columns": columns,
            }
        )
    return {
        "manifest_id": "weekly-retention-dataset-manifest-v1",
        "contract_id": contract["contract_id"],
        "project_id": contract["project_id"],
        "hash_algorithm": "sha256",
        "resources": resources,
    }


def write_sample_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    brief_builder = load_brief_builder()
    brief_path = brief_builder.write_example(root_path / "brief-input")
    brief_result = brief_builder.build_capstone_brief_package(
        brief_path=brief_path,
        output_dir=root_path / "upstream-brief-package",
    )
    state = read_json(brief_result["state_path"])
    contract = default_contract(state["project_id"])
    source_root = root_path / "source-data"
    source_root.mkdir(parents=True, exist_ok=True)
    write_source_csvs(source_root, contract)
    contract_path = write_json(root_path / "data_contract.json", contract)
    manifest_path = write_json(
        root_path / "dataset_manifest.json",
        build_dataset_manifest(contract, source_root),
    )
    return {
        "upstream_brief_package": brief_result["output_dir"],
        "data_contract_path": contract_path,
        "dataset_manifest_path": manifest_path,
        "source_root": source_root,
    }


def table_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = contract.get("tables")
    if not isinstance(tables, list):
        return {}
    return {
        table["source_id"]: table
        for table in tables
        if isinstance(table, dict) and non_empty_text(table.get("source_id"))
    }


def manifest_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = manifest.get("resources")
    if not isinstance(resources, list):
        return {}
    return {
        resource["source_id"]: resource
        for resource in resources
        if isinstance(resource, dict) and non_empty_text(resource.get("source_id"))
    }


def validate_upstream_brief(package: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    required = {
        "capstone_state.json",
        "capstone_brief_audit.json",
        "brief_manifest.json",
    }
    missing = sorted(name for name in required if not (package / name).is_file())
    if missing:
        return {}, check(
            "upstream_brief_is_ready_and_untampered",
            False,
            observed={"missing": missing},
            expected=sorted(required),
            message="Data work starts only from a passing, checksum-verified brief.",
        )
    state = read_json(package / "capstone_state.json")
    audit = read_json(package / "capstone_brief_audit.json")
    manifest = read_json(package / "brief_manifest.json")
    errors: list[dict[str, Any]] = []
    state_entry = (manifest.get("outputs") or {}).get("capstone_state", {})
    if state_entry.get("sha256") != sha256_file(package / "capstone_state.json"):
        errors.append({"field": "capstone_state.sha256", "reason": "manifest mismatch"})
    if audit.get("valid") is not True or audit.get("status") != "ready_for_data_contract":
        errors.append({"field": "capstone_brief_audit", "reason": "brief is not ready"})
    if state.get("stage_status") != "ready_for_data_contract":
        errors.append(
            {"field": "capstone_state.stage_status", "observed": state.get("stage_status")}
        )
    if state.get("current_stage") != "problem_selection":
        errors.append(
            {"field": "capstone_state.current_stage", "observed": state.get("current_stage")}
        )
    if audit.get("project_id") != state.get("project_id"):
        errors.append({"field": "project_id", "reason": "upstream files disagree"})
    return state, check(
        "upstream_brief_is_ready_and_untampered",
        not errors,
        observed={"project_id": state.get("project_id"), "errors": errors},
        expected="passing brief audit, ready state and matching state checksum",
        message="A changed brief invalidates every downstream data decision.",
    )


def validate_contract_structure(contract: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_CONTRACT_FIELDS - set(contract))
    errors: list[dict[str, Any]] = []
    if missing:
        errors.append({"field": "data_contract", "missing": missing})
    if contract.get("project_id") != state.get("project_id"):
        errors.append(
            {
                "field": "project_id",
                "contract": contract.get("project_id"),
                "upstream": state.get("project_id"),
            }
        )
    if contract.get("timezone") != "UTC":
        errors.append(
            {"field": "timezone", "observed": contract.get("timezone"), "expected": "UTC"}
        )
    try:
        parse_timestamp(contract.get("data_as_of"), "data_as_of")
    except DataContractError as error:
        errors.append({"field": "data_as_of", "reason": str(error)})
    tables = contract.get("tables")
    source_ids: list[str] = []
    if not isinstance(tables, list) or not tables:
        errors.append({"field": "tables", "reason": "non-empty list required"})
    else:
        for position, table in enumerate(tables):
            if not isinstance(table, dict):
                errors.append({"position": position, "reason": "table must be object"})
                continue
            table_missing = sorted(REQUIRED_TABLE_FIELDS - set(table))
            if table_missing:
                errors.append({"source_id": table.get("source_id"), "missing": table_missing})
            if non_empty_text(table.get("source_id")):
                source_ids.append(table["source_id"])
        if len(source_ids) != len(set(source_ids)):
            errors.append({"field": "tables.source_id", "reason": "must be unique"})
    return check(
        "data_contract_structure_matches_upstream_project",
        not errors,
        observed={
            "contract_id": contract.get("contract_id"),
            "source_ids": source_ids,
            "errors": errors,
        },
        expected="complete contract, UTC data_as_of and matching upstream project_id",
        message="The data contract is versioned evidence, not a detached schema note.",
    )


def validate_source_policies(contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for source_id, table in table_map(contract).items():
        for field in ("owner", "origin", "license"):
            if not non_empty_text(table.get(field)):
                errors.append({"source_id": source_id, "field": field, "reason": "required"})
        if not isinstance(table.get("allowed_uses"), list) or not table["allowed_uses"]:
            errors.append({"source_id": source_id, "field": "allowed_uses", "reason": "required"})
        if table.get("publication_class") not in {"public", "aggregated", "restricted", "secret"}:
            errors.append(
                {"source_id": source_id, "field": "publication_class", "reason": "unsupported"}
            )
        reproducibility = table.get("reproducibility")
        if not isinstance(reproducibility, dict) or not non_empty_text(
            reproducibility.get("command")
        ):
            errors.append(
                {"source_id": source_id, "field": "reproducibility.command", "reason": "required"}
            )
        path = table.get("path")
        if not non_empty_text(path) or Path(path).is_absolute() or ".." in Path(path).parts:
            errors.append(
                {"source_id": source_id, "field": "path", "reason": "safe relative path required"}
            )
    defects = contract.get("known_defects")
    if not isinstance(defects, list) or not defects:
        errors.append({"field": "known_defects", "reason": "at least one explicit entry required"})
    return check(
        "sources_have_owner_origin_license_usage_and_reproducibility",
        not errors,
        observed={"source_count": len(table_map(contract)), "errors": errors},
        expected="each source has policy metadata and known defects are documented",
        message="A readable CSV is not automatically permitted, reproducible or publishable.",
    )


def validate_manifest_and_files(
    contract: dict[str, Any], manifest: dict[str, Any], source_root: Path
) -> tuple[dict[str, tuple[list[dict[str, str]], list[str]]], dict[str, Any]]:
    tables = table_map(contract)
    resources = manifest_map(manifest)
    loaded: dict[str, tuple[list[dict[str, str]], list[str]]] = {}
    errors: list[dict[str, Any]] = []
    if manifest.get("contract_id") != contract.get("contract_id"):
        errors.append({"field": "manifest.contract_id", "reason": "contract mismatch"})
    if manifest.get("project_id") != contract.get("project_id"):
        errors.append({"field": "manifest.project_id", "reason": "project mismatch"})
    if set(resources) != set(tables):
        errors.append(
            {
                "field": "manifest.resources",
                "missing": sorted(set(tables) - set(resources)),
                "unexpected": sorted(set(resources) - set(tables)),
            }
        )
    for source_id, table in tables.items():
        path = source_root / str(table.get("path", ""))
        resource = resources.get(source_id, {})
        if not path.is_file():
            errors.append({"source_id": source_id, "field": "path", "reason": "file missing"})
            continue
        try:
            rows, columns = read_csv(path)
        except (OSError, UnicodeError, csv.Error) as error:
            errors.append({"source_id": source_id, "field": "csv", "reason": str(error)})
            continue
        loaded[source_id] = (rows, columns)
        observed = {
            "path": table.get("path"),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "rows": len(rows),
            "columns": columns,
        }
        for field, value in observed.items():
            if resource.get(field) != value:
                errors.append(
                    {
                        "source_id": source_id,
                        "field": field,
                        "manifest": resource.get(field),
                        "actual": value,
                    }
                )
    return loaded, check(
        "dataset_manifest_matches_source_bytes",
        not errors,
        observed={"loaded_sources": sorted(loaded), "errors": errors},
        expected="one exact manifest resource per contract table with matching bytes and SHA-256",
        message="Manifest drift must fail before the data are interpreted.",
    )


def value_matches_type(value: str, field: dict[str, Any]) -> bool:
    if value == "":
        return field.get("nullable") is True
    field_type = field.get("type")
    try:
        if field_type == "string":
            return True
        if field_type == "integer":
            int(value)
            return "." not in value
        if field_type == "float":
            float(value)
            return True
        if field_type == "boolean":
            return value.lower() in {"true", "false"}
        if field_type == "timestamp":
            parse_timestamp(value, field.get("name", "timestamp"))
            return True
    except (ValueError, DataContractError):
        return False
    return False


def validate_schemas_and_grain(
    contract: dict[str, Any],
    loaded: dict[str, tuple[list[dict[str, str]], list[str]]],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for source_id, table in table_map(contract).items():
        schema = table.get("schema")
        if not isinstance(schema, list) or not schema:
            errors.append({"source_id": source_id, "field": "schema", "reason": "required"})
            continue
        schema_names = [field.get("name") for field in schema if isinstance(field, dict)]
        for field in schema:
            if not isinstance(field, dict):
                errors.append(
                    {"source_id": source_id, "field": "schema", "reason": "object required"}
                )
                continue
            if field.get("type") not in SUPPORTED_TYPES:
                errors.append(
                    {
                        "source_id": source_id,
                        "column": field.get("name"),
                        "reason": "unsupported type",
                    }
                )
            if field.get("classification") not in {"public", "aggregated", "restricted", "secret"}:
                errors.append(
                    {
                        "source_id": source_id,
                        "column": field.get("name"),
                        "reason": "classification required",
                    }
                )
        if source_id not in loaded:
            continue
        rows, columns = loaded[source_id]
        if columns != schema_names:
            errors.append(
                {
                    "source_id": source_id,
                    "field": "columns",
                    "actual": columns,
                    "expected": schema_names,
                }
            )
        for row_number, row in enumerate(rows, start=2):
            for field in schema:
                if isinstance(field, dict) and not value_matches_type(
                    row.get(field.get("name"), ""), field
                ):
                    errors.append(
                        {
                            "source_id": source_id,
                            "row": row_number,
                            "column": field.get("name"),
                            "value": row.get(field.get("name"), ""),
                            "reason": "type or nullability mismatch",
                        }
                    )
        grain = table.get("grain")
        keys = grain.get("keys") if isinstance(grain, dict) else None
        if not isinstance(keys, list) or not keys or grain.get("duplicate_policy") != "forbid":
            errors.append(
                {
                    "source_id": source_id,
                    "field": "grain",
                    "reason": "forbid policy and keys required",
                }
            )
            continue
        key_counts: Counter[tuple[str, ...]] = Counter()
        for row in rows:
            key = tuple(row.get(column, "") for column in keys)
            if any(not value for value in key):
                errors.append(
                    {"source_id": source_id, "field": "grain", "reason": "null key", "key": key}
                )
            key_counts[key] += 1
        duplicates = [key for key, count in key_counts.items() if count > 1]
        if duplicates:
            errors.append(
                {
                    "source_id": source_id,
                    "field": "grain",
                    "reason": "duplicate key",
                    "sample": duplicates[:5],
                }
            )
    return check(
        "schemas_types_nullability_and_grain_match_data",
        not errors,
        observed={"errors": errors},
        expected="exact columns, supported values, non-null unique keys and forbidden duplicates",
        message="Schema and grain are verified against rows rather than trusted as prose.",
    )


def row_key(row: dict[str, str], keys: list[str]) -> tuple[str, ...]:
    return tuple(row.get(key, "") for key in keys)


def validate_relationships(
    contract: dict[str, Any],
    loaded: dict[str, tuple[list[dict[str, str]], list[str]]],
) -> dict[str, Any]:
    relationships = contract.get("relationships")
    errors: list[dict[str, Any]] = []
    if not isinstance(relationships, list) or not relationships:
        errors.append({"field": "relationships", "reason": "non-empty list required"})
    else:
        for relationship in relationships:
            if not isinstance(relationship, dict):
                errors.append({"field": "relationships", "reason": "object required"})
                continue
            relationship_id = relationship.get("id")
            from_source = relationship.get("from_source")
            to_source = relationship.get("to_source")
            from_keys = relationship.get("from_keys")
            to_keys = relationship.get("to_keys")
            if relationship.get("cardinality") != "many_to_one":
                errors.append(
                    {"id": relationship_id, "field": "cardinality", "expected": "many_to_one"}
                )
            if relationship.get("orphan_policy") != "block":
                errors.append(
                    {"id": relationship_id, "field": "orphan_policy", "expected": "block"}
                )
            if (
                from_source not in loaded
                or to_source not in loaded
                or not isinstance(from_keys, list)
                or not isinstance(to_keys, list)
                or len(from_keys) != len(to_keys)
            ):
                errors.append({"id": relationship_id, "reason": "sources or key lists invalid"})
                continue
            from_rows = loaded[from_source][0]
            to_rows = loaded[to_source][0]
            to_counts = Counter(row_key(row, to_keys) for row in to_rows)
            duplicate_targets = [key for key, count in to_counts.items() if count > 1]
            if duplicate_targets:
                errors.append(
                    {
                        "id": relationship_id,
                        "reason": "to-side not unique",
                        "sample": duplicate_targets[:5],
                    }
                )
            target_keys = set(to_counts)
            orphans = [
                row_key(row, from_keys)
                for row in from_rows
                if row_key(row, from_keys) not in target_keys
            ]
            if orphans:
                errors.append(
                    {"id": relationship_id, "reason": "orphan rows", "sample": orphans[:5]}
                )
    return check(
        "relationships_enforce_cardinality_and_orphans",
        not errors,
        observed={"errors": errors},
        expected="declared many-to-one relationships with unique parents and zero orphans",
        message="A valid table grain can still produce an invalid join graph.",
    )


def validate_freshness_and_population(
    contract: dict[str, Any],
    loaded: dict[str, tuple[list[dict[str, str]], list[str]]],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    try:
        data_as_of = parse_timestamp(contract.get("data_as_of"), "data_as_of")
    except DataContractError as error:
        return check(
            "freshness_and_observation_windows_are_explicit",
            False,
            observed={"errors": [{"field": "data_as_of", "reason": str(error)}]},
            expected="timezone-aware data_as_of and fresh complete rows",
            message="Freshness is part of the decision contract.",
        )
    for source_id, table in table_map(contract).items():
        if source_id not in loaded:
            continue
        freshness = table.get("freshness")
        if not isinstance(freshness, dict):
            errors.append({"source_id": source_id, "field": "freshness", "reason": "required"})
            continue
        field = freshness.get("timestamp_field")
        max_age = freshness.get("max_age_days")
        if not non_empty_text(field) or not isinstance(max_age, int) or max_age <= 0:
            errors.append(
                {
                    "source_id": source_id,
                    "field": "freshness",
                    "reason": "field and positive max_age_days required",
                }
            )
            continue
        timestamps: list[datetime] = []
        for row in loaded[source_id][0]:
            try:
                timestamps.append(parse_timestamp(row.get(field), f"{source_id}.{field}"))
            except DataContractError as error:
                errors.append({"source_id": source_id, "field": field, "reason": str(error)})
        if timestamps:
            latest = max(timestamps)
            if latest > data_as_of:
                errors.append(
                    {
                        "source_id": source_id,
                        "field": field,
                        "reason": "future availability",
                        "latest": latest.isoformat(),
                    }
                )
            age_days = (data_as_of - latest).total_seconds() / 86400
            if age_days > max_age:
                errors.append(
                    {
                        "source_id": source_id,
                        "field": field,
                        "reason": "stale",
                        "age_days": age_days,
                        "max_age_days": max_age,
                    }
                )
    population = contract.get("analysis_population")
    if not isinstance(population, dict):
        errors.append({"field": "analysis_population", "reason": "object required"})
    else:
        source_id = population.get("source_id")
        column = population.get("eligibility_column")
        required = population.get("required_value")
        if source_id not in loaded or required is not True or not non_empty_text(column):
            errors.append(
                {
                    "field": "analysis_population",
                    "reason": "source, column and true policy required",
                }
            )
        else:
            eligible = [
                row for row in loaded[source_id][0] if row.get(column, "").lower() == "true"
            ]
            if not eligible:
                errors.append(
                    {"field": "analysis_population", "reason": "no complete eligible rows"}
                )
    return check(
        "freshness_and_observation_windows_are_explicit",
        not errors,
        observed={"data_as_of": contract.get("data_as_of"), "errors": errors},
        expected="no future/stale availability and at least one complete analysis row",
        message="Incomplete or stale rows stay visible but cannot silently enter analysis.",
    )


def nested_exists(value: Any, path: str) -> bool:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current is not None


def validate_route_controls(contract: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    route = state.get("route")
    variant = state.get("route_variant")
    required = ROUTE_CONTROL_IDS.get((route, variant))
    errors: list[dict[str, Any]] = []
    controls = contract.get("route_controls")
    route_policy = contract.get("route_policy")
    if required is None:
        errors.append({"field": "route/variant", "observed": [route, variant]})
        required = ()
    if not isinstance(route_policy, dict):
        errors.append({"field": "route_policy", "reason": "object required"})
        route_policy = {}
    control_map: dict[str, dict[str, Any]] = {}
    if not isinstance(controls, list):
        errors.append({"field": "route_controls", "reason": "list required"})
    else:
        control_map = {
            item["id"]: item
            for item in controls
            if isinstance(item, dict) and non_empty_text(item.get("id"))
        }
        if set(control_map) != set(required):
            errors.append(
                {
                    "field": "route_controls",
                    "missing": sorted(set(required) - set(control_map)),
                    "unnecessary": sorted(set(control_map) - set(required)),
                }
            )
        for control_id in required:
            control = control_map.get(control_id, {})
            if control.get("enforced") is not True:
                errors.append({"id": control_id, "field": "enforced", "reason": "must be true"})
            if not non_empty_text(control.get("policy")):
                errors.append({"id": control_id, "field": "policy", "reason": "required"})
            evidence_fields = control.get("evidence_fields")
            if not isinstance(evidence_fields, list) or not evidence_fields:
                errors.append({"id": control_id, "field": "evidence_fields", "reason": "required"})
            if control_id not in route_policy:
                errors.append({"id": control_id, "field": "route_policy", "reason": "missing"})
            for evidence in evidence_fields if isinstance(evidence_fields, list) else []:
                if evidence.startswith("data_contract."):
                    if not nested_exists(contract, evidence.removeprefix("data_contract.")):
                        errors.append({"id": control_id, "field": evidence, "reason": "unresolved"})
                elif evidence.startswith("capstone_state."):
                    if not nested_exists(state, evidence.removeprefix("capstone_state.")):
                        errors.append({"id": control_id, "field": evidence, "reason": "unresolved"})
                else:
                    errors.append(
                        {"id": control_id, "field": evidence, "reason": "unsupported evidence root"}
                    )
    if (route, variant) == ("core_analytics", "standard"):
        allowed = (route_policy.get("descriptive_claim_only") or {}).get("allowed_claim_types", [])
        if state.get("claim_type") not in allowed:
            errors.append(
                {"field": "claim_type", "observed": state.get("claim_type"), "allowed": allowed}
            )
    return check(
        "route_specific_data_controls_are_enforced",
        not errors,
        observed={
            "route": route,
            "variant": variant,
            "control_ids": sorted(control_map),
            "errors": errors,
        },
        expected=list(required),
        message=(
            "Experiments, marts, causal studies, forecasts, ML and delivery "
            "have different leakage gates."
        ),
    )


def validate_public_policy(contract: dict[str, Any]) -> dict[str, Any]:
    policy = contract.get("public_release_policy")
    errors: list[dict[str, Any]] = []
    if not isinstance(policy, dict):
        errors.append({"field": "public_release_policy", "reason": "object required"})
    else:
        allowed = set(policy.get("allowed_classifications", []))
        forbidden = set(policy.get("forbidden_classifications", []))
        if not {"public", "aggregated"} <= allowed:
            errors.append({"field": "allowed_classifications", "observed": sorted(allowed)})
        if not {"restricted", "secret"} <= forbidden or allowed & forbidden:
            errors.append({"field": "forbidden_classifications", "observed": sorted(forbidden)})
        if (
            not isinstance(policy.get("minimum_group_size"), int)
            or policy["minimum_group_size"] < 2
        ):
            errors.append({"field": "minimum_group_size", "reason": "integer >= 2 required"})
        if policy.get("sample_grain") != ["as_of_week", "segment_id"]:
            errors.append({"field": "sample_grain", "observed": policy.get("sample_grain")})
    classifications = {
        field.get("classification")
        for table in table_map(contract).values()
        for field in table.get("schema", [])
        if isinstance(field, dict)
    }
    if "restricted" not in classifications:
        errors.append(
            {"field": "schema.classification", "reason": "restricted fields must be explicit"}
        )
    return check(
        "public_release_excludes_restricted_and_secret_rows",
        not errors,
        observed={
            "classifications": sorted(item for item in classifications if item),
            "errors": errors,
        },
        expected=(
            "aggregate-only public sample, minimum group size and forbidden "
            "restricted/secret fields"
        ),
        message="A checksum does not grant publication rights or anonymize row-level data.",
    )


def build_public_sample(
    contract: dict[str, Any],
    loaded: dict[str, tuple[list[dict[str, str]], list[str]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    if "user_week" not in loaded:
        return [], [{"source_id": "user_week", "reason": "source unavailable"}]
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in loaded["user_week"][0]:
        if row.get("window_complete", "").lower() == "true":
            groups[(row.get("as_of_week", ""), row.get("segment_id", ""))].append(row)
    minimum = (contract.get("public_release_policy") or {}).get("minimum_group_size", 2)
    output: list[dict[str, Any]] = []
    for (as_of_week, segment_id), rows in sorted(groups.items()):
        if len(rows) < minimum:
            errors.append(
                {"grain": [as_of_week, segment_id], "rows": len(rows), "minimum": minimum}
            )
            continue
        try:
            support_ticket_count = sum(int(row.get("support_ticket_count", "0")) for row in rows)
        except ValueError:
            errors.append(
                {
                    "grain": [as_of_week, segment_id],
                    "field": "support_ticket_count",
                    "reason": "aggregate input is not an integer",
                }
            )
            continue
        activated = sum(row.get("activation_complete", "").lower() == "true" for row in rows)
        output.append(
            {
                "as_of_week": as_of_week,
                "segment_id": segment_id,
                "users": len(rows),
                "activated_users": activated,
                "activation_rate": f"{activated / len(rows):.3f}",
                "support_ticket_count": support_ticket_count,
                "churned_users": sum(row.get("churned_7d", "").lower() == "true" for row in rows),
            }
        )
    return output, errors


def audit_data_contract(
    *,
    upstream_brief_package: str | Path,
    data_contract_path: str | Path,
    dataset_manifest_path: str | Path,
    source_root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    package = Path(upstream_brief_package)
    contract = read_json(data_contract_path)
    manifest = read_json(dataset_manifest_path)
    state, upstream_check = validate_upstream_brief(package)
    loaded, manifest_check = validate_manifest_and_files(contract, manifest, Path(source_root))
    public_rows, public_errors = build_public_sample(contract, loaded)
    checks = [
        upstream_check,
        validate_contract_structure(contract, state),
        validate_source_policies(contract),
        manifest_check,
        validate_schemas_and_grain(contract, loaded),
        validate_relationships(contract, loaded),
        validate_freshness_and_population(contract, loaded),
        validate_route_controls(contract, state),
        validate_public_policy(contract),
        check(
            "public_sample_meets_aggregate_grain_and_group_size",
            bool(public_rows) and not public_errors,
            observed={
                "rows": len(public_rows),
                "errors": public_errors,
                "fields": list(PUBLIC_SAMPLE_FIELDS),
            },
            expected="non-empty aggregate sample with every group at or above minimum size",
            message="Only a policy-compliant aggregate sample may enter the portfolio package.",
        ),
    ]
    blocking_errors = [
        item["id"] for item in checks if not item["valid"] and item["severity"] == "block"
    ]
    upstream_warnings = state.get("warnings", []) if isinstance(state.get("warnings"), list) else []
    valid = not blocking_errors
    report = {
        "version": AUDIT_VERSION,
        "contract_id": contract.get("contract_id"),
        "project_id": contract.get("project_id"),
        "status": "data_ready" if valid else "data_contract_block",
        "valid": valid,
        "checks": checks,
        "summary": {
            "blocking_errors": blocking_errors,
            "warnings": upstream_warnings,
            "check_count": len(checks),
            "source_count": len(table_map(contract)),
            "relationship_count": len(contract.get("relationships", []))
            if isinstance(contract.get("relationships"), list)
            else 0,
            "public_sample_rows": len(public_rows),
            "next_stage": "baseline" if valid else "data_contract",
        },
    }
    return report, state, loaded, {"rows": public_rows, "errors": public_errors}


def lineage_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    relationships = contract.get("relationships", [])
    targets: dict[str, list[str]] = defaultdict(list)
    for relationship in relationships if isinstance(relationships, list) else []:
        if isinstance(relationship, dict):
            targets[str(relationship.get("from_source"))].append(str(relationship.get("to_source")))
    population_source = (contract.get("analysis_population") or {}).get("source_id")
    return [
        {
            "source_id": source_id,
            "path": table.get("path"),
            "owner": table.get("owner"),
            "origin": table.get("origin"),
            "grain_keys": "|".join((table.get("grain") or {}).get("keys", [])),
            "relationship_targets": "|".join(sorted(targets.get(source_id, []))),
            "analysis_population_source": str(source_id == population_source).lower(),
            "status": "declared",
        }
        for source_id, table in sorted(table_map(contract).items())
    ]


def checksum_rows(
    contract: dict[str, Any], manifest: dict[str, Any], source_root: Path
) -> list[dict[str, Any]]:
    resources = manifest_map(manifest)
    rows = []
    for source_id, table in sorted(table_map(contract).items()):
        path = source_root / str(table.get("path", ""))
        expected = resources.get(source_id, {}).get("sha256", "")
        actual = sha256_file(path) if path.is_file() else ""
        rows.append(
            {
                "source_id": source_id,
                "path": table.get("path", ""),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "matches": str(bool(expected) and expected == actual).lower(),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "publication_class": table.get("publication_class", ""),
            }
        )
    return rows


def build_data_contract_package(
    *,
    upstream_brief_package: str | Path,
    data_contract_path: str | Path,
    dataset_manifest_path: str | Path,
    source_root: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    contract = read_json(data_contract_path)
    dataset_manifest = read_json(dataset_manifest_path)
    report, upstream_state, _loaded, public = audit_data_contract(
        upstream_brief_package=upstream_brief_package,
        data_contract_path=data_contract_path,
        dataset_manifest_path=dataset_manifest_path,
        source_root=source_root,
    )
    contract_output = write_json(output / "data_contract.json", contract)
    dataset_output = write_json(output / "dataset_manifest.json", dataset_manifest)
    audit_output = write_json(output / "data_audit.json", report)
    lineage_output = write_csv(
        output / "lineage_report.csv",
        lineage_rows(contract),
        [
            "source_id",
            "path",
            "owner",
            "origin",
            "grain_keys",
            "relationship_targets",
            "analysis_population_source",
            "status",
        ],
    )
    checksum_output = write_csv(
        output / "checksum_inventory.csv",
        checksum_rows(contract, dataset_manifest, Path(source_root)),
        [
            "source_id",
            "path",
            "expected_sha256",
            "actual_sha256",
            "matches",
            "bytes",
            "publication_class",
        ],
    )
    public_output = write_csv(
        output / "public_data_sample.csv",
        public["rows"],
        list(PUBLIC_SAMPLE_FIELDS),
    )
    generated = {
        "data_contract": contract_output,
        "dataset_manifest": dataset_output,
        "data_audit": audit_output,
        "lineage_report": lineage_output,
        "checksum_inventory": checksum_output,
        "public_data_sample": public_output,
    }
    state = dict(upstream_state)
    previous_warnings = state.get("warnings", []) if isinstance(state.get("warnings"), list) else []
    state.update(
        {
            "data_contract_id": contract.get("contract_id"),
            "current_stage": "data_contract",
            "stage_status": report["status"],
            "open_blockers": report["summary"]["blocking_errors"],
            "warnings": list(dict.fromkeys(previous_warnings + report["summary"]["warnings"])),
            "artifact_inventory": list(
                dict.fromkeys(
                    state.get("artifact_inventory", []) + [path.name for path in generated.values()]
                )
            ),
            "evidence_links": [
                {"stage": "data_contract", "path": "data_audit.json"},
                {"stage": "data_contract", "path": "data_contract.json"},
                {"stage": "data_contract", "path": "dataset_manifest.json"},
            ],
            "input_checksums": {
                **state.get("input_checksums", {}),
                Path(data_contract_path).name: sha256_file(data_contract_path),
                Path(dataset_manifest_path).name: sha256_file(dataset_manifest_path),
            },
            "output_checksums": {path.name: sha256_file(path) for path in generated.values()},
            "updated_at": contract.get("data_as_of"),
        }
    )
    state_output = write_json(output / "capstone_state.json", state)
    generated["capstone_state"] = state_output
    package_manifest = {
        "version": AUDIT_VERSION,
        "project_id": contract.get("project_id"),
        "contract_id": contract.get("contract_id"),
        "status": report["status"],
        "valid": report["valid"],
        "hash_algorithm": "sha256",
        "renderer_used": "capstone_data_contract_auditor",
        "raw_sources_copied": False,
        "inputs": {
            "upstream_capstone_state": {
                "path": "upstream-brief-package/capstone_state.json",
                "sha256": sha256_file(Path(upstream_brief_package) / "capstone_state.json"),
            },
            "data_contract": {
                "path": Path(data_contract_path).name,
                "sha256": sha256_file(data_contract_path),
            },
            "dataset_manifest": {
                "path": Path(dataset_manifest_path).name,
                "sha256": sha256_file(dataset_manifest_path),
            },
        },
        "outputs": {
            name: {"path": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for name, path in generated.items()
        },
    }
    package_manifest_path = write_json(output / "data_package_manifest.json", package_manifest)
    return {
        "report": report,
        "output_dir": output,
        "state_path": state_output,
        "manifest_path": package_manifest_path,
        "public_sample_path": public_output,
        "checksum_inventory_path": checksum_output,
        "lineage_report_path": lineage_output,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit a capstone data contract before baseline work begins.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--upstream-brief-package", type=Path, help="Passing package from lesson 18/01."
    )
    parser.add_argument("--data-contract", type=Path, help="Path to data_contract.json.")
    parser.add_argument("--dataset-manifest", type=Path, help="Path to dataset_manifest.json.")
    parser.add_argument(
        "--source-root", type=Path, help="Directory containing declared raw source files."
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Directory for audited data package."
    )
    parser.add_argument(
        "--write-example", type=Path, help="Write deterministic upstream and data inputs here."
    )
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help="Return exit code 1 for blocked data contracts.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    upstream = parsed.upstream_brief_package
    contract = parsed.data_contract
    dataset_manifest = parsed.dataset_manifest
    source_root = parsed.source_root
    if parsed.write_example:
        sample = write_sample_inputs(parsed.write_example)
        upstream = upstream or sample["upstream_brief_package"]
        contract = contract or sample["data_contract_path"]
        dataset_manifest = dataset_manifest or sample["dataset_manifest_path"]
        source_root = source_root or sample["source_root"]
    missing = [
        name
        for name, value in [
            ("--upstream-brief-package", upstream),
            ("--data-contract", contract),
            ("--dataset-manifest", dataset_manifest),
            ("--source-root", source_root),
        ]
        if value is None
    ]
    if missing:
        payload = {
            "version": AUDIT_VERSION,
            "status": "system_error",
            "valid": False,
            "error": {"code": "missing_inputs", "message": ", ".join(missing)},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    try:
        result = build_data_contract_package(
            upstream_brief_package=upstream,
            data_contract_path=contract,
            dataset_manifest_path=dataset_manifest,
            source_root=source_root,
            output_dir=parsed.output_dir,
        )
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, DataContractError) as error:
        payload = {
            "version": AUDIT_VERSION,
            "status": "system_error",
            "valid": False,
            "error": {"code": "invalid_input", "message": str(error)},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "contract_id": report["contract_id"],
        "source_count": report["summary"]["source_count"],
        "public_sample_rows": report["summary"]["public_sample_rows"],
        "blocking_errors": report["summary"]["blocking_errors"],
        "warnings": report["summary"]["warnings"],
        "output_dir": str(result["output_dir"]),
        "manifest": str(result["manifest_path"]),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if parsed.fail_on_invalid and not report["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
