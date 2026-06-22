from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_MODEL_FIELDS = {
    "model_id",
    "layer",
    "owner",
    "business_question",
    "grain",
    "primary_key",
    "source_tables",
    "upstream_models",
    "materialization",
    "freshness_sla",
    "event_time_column",
    "incremental_strategy",
    "unique_key",
    "late_arrival_window",
    "full_refresh_policy",
    "schema_change_policy",
    "required_tests",
    "warning_checks",
    "accepted_values",
    "reconciliation_rules",
    "snapshot_strategy",
    "documentation_required",
    "downstream_exposures",
    "known_limitations",
    "publication_rule",
}
ALLOWED_LAYERS = {"raw", "staging", "intermediate", "mart", "snapshot"}
ALLOWED_MATERIALIZATIONS = {"source", "view", "table", "ephemeral", "incremental", "snapshot"}
LAYER_RANK = {"raw": 0, "snapshot": 1, "staging": 1, "intermediate": 2, "mart": 3}
KEY_TESTS = {"not_null_primary_key", "unique_primary_key"}
REQUIRED_BRIEF_HEADINGS = (
    "# Customer revenue health mart design brief",
    "## Business question",
    "## Layer map",
    "## Publication rule",
)


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"id": check_id, "valid": True, "observed": observed, "expected": expected, "sample": []}


def failed(
    check_id: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def normalize_contract(value: Any) -> list[dict[str, Any]]:
    models = value.get("models") if isinstance(value, dict) else None
    if not isinstance(models, list):
        raise ValueError("layer contract must be an object with a models list")
    normalized: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("each model contract must be an object")
        normalized.append(model)
    return normalized


def data_tables(data_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = data_contract.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("data contract must contain a tables object")
    return {str(name): table for name, table in tables.items() if isinstance(table, dict)}


def layer_counts(models: list[dict[str, Any]]) -> dict[str, int]:
    counts = {layer: 0 for layer in ("raw", "staging", "intermediate", "mart", "snapshot")}
    for model in models:
        layer = model.get("layer")
        if layer in counts:
            counts[layer] += 1
    return counts


def validate_brief(brief_text: str | None, models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if brief_text is None:
        return []
    checks: list[dict[str, Any]] = []
    missing_headings = [heading for heading in REQUIRED_BRIEF_HEADINGS if heading not in brief_text]
    if missing_headings:
        checks.append(
            failed(
                "brief_required_headings",
                missing_headings,
                "all design brief headings present",
                missing_headings,
            )
        )
    else:
        checks.append(passed("brief_required_headings", len(REQUIRED_BRIEF_HEADINGS), "present"))

    mart_ids = [model["model_id"] for model in models if model.get("layer") == "mart"]
    missing_marts = [model_id for model_id in mart_ids if model_id not in brief_text]
    if missing_marts:
        checks.append(
            failed("brief_mentions_mart_models", missing_marts, "all mart models named", missing_marts)
        )
    else:
        checks.append(passed("brief_mentions_mart_models", mart_ids, "all mart models named"))
    return checks


def validate_contract(
    contract: dict[str, Any],
    data_contract: dict[str, Any],
    brief_text: str | None = None,
) -> dict[str, Any]:
    models = normalize_contract(contract)
    tables = data_tables(data_contract)
    checks: list[dict[str, Any]] = []

    ids = [model.get("model_id") for model in models if isinstance(model.get("model_id"), str)]
    duplicate_ids = sorted({model_id for model_id in ids if ids.count(model_id) > 1})
    if duplicate_ids:
        checks.append(failed("model_ids_unique", duplicate_ids, "unique model_id values", duplicate_ids))
    else:
        checks.append(passed("model_ids_unique", len(ids), "unique model_id values"))

    missing_fields: list[dict[str, Any]] = []
    invalid_layers: list[dict[str, Any]] = []
    invalid_materializations: list[dict[str, Any]] = []
    for model in models:
        model_id = model.get("model_id", "<missing>")
        missing = sorted(REQUIRED_MODEL_FIELDS - set(model))
        if missing:
            missing_fields.append({"model_id": model_id, "missing": missing})
        if model.get("layer") not in ALLOWED_LAYERS:
            invalid_layers.append({"model_id": model_id, "layer": model.get("layer")})
        if model.get("materialization") not in ALLOWED_MATERIALIZATIONS:
            invalid_materializations.append(
                {"model_id": model_id, "materialization": model.get("materialization")}
            )

    if missing_fields:
        checks.append(
            failed("model_required_fields", len(missing_fields), "all required fields", missing_fields)
        )
    else:
        checks.append(passed("model_required_fields", len(models), "all required fields"))
    if invalid_layers:
        checks.append(failed("model_layers_valid", invalid_layers, sorted(ALLOWED_LAYERS), invalid_layers))
    else:
        checks.append(passed("model_layers_valid", layer_counts(models), sorted(ALLOWED_LAYERS)))
    if invalid_materializations:
        checks.append(
            failed(
                "model_materializations_valid",
                invalid_materializations,
                sorted(ALLOWED_MATERIALIZATIONS),
                invalid_materializations,
            )
        )
    else:
        checks.append(
            passed("model_materializations_valid", len(models), sorted(ALLOWED_MATERIALIZATIONS))
        )

    model_by_id = {model["model_id"]: model for model in models if isinstance(model.get("model_id"), str)}

    missing_source_tables: list[dict[str, Any]] = []
    raw_key_mismatches: list[dict[str, Any]] = []
    for model in models:
        model_id = model.get("model_id", "<missing>")
        for source_table in as_list(model.get("source_tables")):
            if source_table not in tables:
                missing_source_tables.append({"model_id": model_id, "source_table": source_table})
        if model.get("layer") == "raw" and model_id in tables:
            declared_key = as_list(model.get("primary_key"))
            contract_key = as_list(tables[model_id].get("primary_key"))
            if declared_key != contract_key:
                raw_key_mismatches.append(
                    {"model_id": model_id, "declared": declared_key, "data_contract": contract_key}
                )
    if missing_source_tables:
        checks.append(
            failed(
                "source_tables_exist",
                len(missing_source_tables),
                "all source_tables exist in data contract",
                missing_source_tables,
            )
        )
    else:
        checks.append(passed("source_tables_exist", len(tables), "all source_tables exist"))
    if raw_key_mismatches:
        checks.append(
            failed(
                "raw_primary_keys_match_data_contract",
                raw_key_mismatches,
                "raw model keys equal data contract keys",
                raw_key_mismatches,
            )
        )
    else:
        checks.append(
            passed("raw_primary_keys_match_data_contract", "ok", "raw model keys equal data contract")
        )

    missing_upstreams: list[dict[str, Any]] = []
    layer_order_errors: list[dict[str, Any]] = []
    missing_upstream_for_non_raw: list[str] = []
    mart_without_intermediate: list[str] = []
    mart_direct_raw: list[dict[str, Any]] = []
    for model in models:
        model_id = model.get("model_id", "<missing>")
        layer = model.get("layer")
        upstreams = as_list(model.get("upstream_models"))
        if layer != "raw" and not upstreams:
            missing_upstream_for_non_raw.append(str(model_id))
        if layer == "raw" and upstreams:
            layer_order_errors.append({"model_id": model_id, "upstream": upstreams, "reason": "raw"})
        upstream_layers = []
        for upstream in upstreams:
            upstream_model = model_by_id.get(upstream)
            if upstream_model is None:
                missing_upstreams.append({"model_id": model_id, "upstream_model": upstream})
                continue
            upstream_layer = upstream_model.get("layer")
            upstream_layers.append(upstream_layer)
            if LAYER_RANK.get(str(upstream_layer), 99) >= LAYER_RANK.get(str(layer), -1):
                layer_order_errors.append(
                    {
                        "model_id": model_id,
                        "layer": layer,
                        "upstream_model": upstream,
                        "upstream_layer": upstream_layer,
                    }
                )
            if layer == "mart" and upstream_layer == "raw":
                mart_direct_raw.append({"model_id": model_id, "upstream_model": upstream})
        if layer == "mart" and "intermediate" not in upstream_layers:
            mart_without_intermediate.append(str(model_id))

    if missing_upstreams:
        checks.append(
            failed("upstream_models_exist", len(missing_upstreams), "all upstream models exist", missing_upstreams)
        )
    else:
        checks.append(passed("upstream_models_exist", len(models), "all upstream models exist"))
    if missing_upstream_for_non_raw:
        checks.append(
            failed(
                "non_raw_models_have_upstream",
                missing_upstream_for_non_raw,
                "staging/intermediate/mart models declare upstream_models",
                missing_upstream_for_non_raw,
            )
        )
    else:
        checks.append(passed("non_raw_models_have_upstream", "ok", "non-raw upstreams declared"))
    if layer_order_errors:
        checks.append(
            failed("layer_order_is_forward", len(layer_order_errors), "dependencies move raw to mart", layer_order_errors)
        )
    else:
        checks.append(passed("layer_order_is_forward", "ok", "dependencies move raw to mart"))
    if mart_direct_raw or mart_without_intermediate:
        sample = mart_direct_raw + [{"model_id": model_id, "reason": "no intermediate upstream"} for model_id in mart_without_intermediate]
        checks.append(
            failed("mart_does_not_skip_layers", sample, "mart depends on intermediate models, not raw", sample)
        )
    else:
        checks.append(passed("mart_does_not_skip_layers", "ok", "mart depends on intermediate models"))

    key_test_errors: list[dict[str, Any]] = []
    mart_contract_errors: list[dict[str, Any]] = []
    freshness_errors: list[str] = []
    limitation_errors: list[str] = []
    for model in models:
        model_id = model.get("model_id", "<missing>")
        tests = set(as_list(model.get("required_tests")))
        primary_key = as_list(model.get("primary_key"))
        if primary_key and not KEY_TESTS.issubset(tests):
            key_test_errors.append(
                {"model_id": model_id, "missing_tests": sorted(KEY_TESTS - tests)}
            )
        layer = model.get("layer")
        if layer in {"raw", "mart"} and not non_empty_text(model.get("freshness_sla")):
            freshness_errors.append(str(model_id))
        if not as_list(model.get("known_limitations")):
            limitation_errors.append(str(model_id))
        if layer == "mart":
            required_conditions = {
                "owner": non_empty_text(model.get("owner")),
                "documentation_required": model.get("documentation_required") is True,
                "downstream_exposures": bool(as_list(model.get("downstream_exposures"))),
                "publication_rule": isinstance(model.get("publication_rule"), dict),
                "reconciliation_rule": bool(as_list(model.get("reconciliation_rules"))),
            }
            failed_conditions = sorted(name for name, ok in required_conditions.items() if not ok)
            if failed_conditions:
                mart_contract_errors.append({"model_id": model_id, "missing": failed_conditions})
    if key_test_errors:
        checks.append(
            failed("primary_key_tests_required", key_test_errors, sorted(KEY_TESTS), key_test_errors)
        )
    else:
        checks.append(passed("primary_key_tests_required", "ok", sorted(KEY_TESTS)))
    if freshness_errors:
        checks.append(
            failed("freshness_declared_for_raw_and_mart", freshness_errors, "freshness_sla", freshness_errors)
        )
    else:
        checks.append(passed("freshness_declared_for_raw_and_mart", "ok", "freshness_sla"))
    if mart_contract_errors:
        checks.append(
            failed("mart_publication_contract", mart_contract_errors, "owner, docs, exposure, publication, reconciliation", mart_contract_errors)
        )
    else:
        checks.append(passed("mart_publication_contract", "ok", "owner, docs, exposure, publication, reconciliation"))
    if limitation_errors:
        checks.append(
            failed("known_limitations_declared", limitation_errors, "at least one limitation per model", limitation_errors)
        )
    else:
        checks.append(passed("known_limitations_declared", "ok", "at least one limitation per model"))

    checks.extend(validate_brief(brief_text, models))
    valid = all(check["valid"] for check in checks)
    return {
        "valid": valid,
        "summary": {
            "project_id": contract.get("project_id"),
            "models": len(models),
            "layers": layer_counts(models),
            "mart_models": [model["model_id"] for model in models if model.get("layer") == "mart"],
            "raw_sources": sorted(tables),
        },
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an analytics layer contract.")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        brief_text = args.brief.read_text(encoding="utf-8") if args.brief else None
        report = validate_contract(
            read_json(args.contract),
            read_json(args.data_contract),
            brief_text=brief_text,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 2

    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
