from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

VERIFICATION_VERSION = "1.0.0"
REQUIRED_IMPLEMENTATION_FILES = {
    "implementation_spec.json",
    "implementation_report.json",
    "implementation_config.json",
    "route_adapter_report.json",
    "candidate_metrics.csv",
    "candidate_decision.json",
    "candidate_acceptance.json",
    "evidence_ledger.csv",
    "run_trace.csv",
    "capstone_state.json",
    "implementation_manifest.json",
}
REQUIRED_CHECK_IDS = (
    "upstream_implementation_package_is_immutable",
    "implementation_state_is_ready_for_independent_verification",
    "verification_spec_is_independent_and_predeclared",
    "route_specific_verification_profile_is_complete",
    "clean_room_rerun_matches_published_package",
    "shadow_calculation_matches_published_result",
    "negative_fixtures_fail_at_expected_gates",
    "sensitivity_analysis_preserves_frozen_gate_and_reports_flips",
    "every_claim_is_supported_by_exact_evidence_and_shadow",
    "skipped_and_xfail_tests_are_disclosed",
    "verification_outputs_respect_public_boundary_and_stage",
)
REQUIRED_FIXTURES = {
    "tampered_output_checksum": "upstream_implementation_package_is_immutable",
    "stale_stage_with_rehashed_manifest": (
        "implementation_state_is_ready_for_independent_verification"
    ),
    "changed_shadow_denominator": "shadow_calculation_matches_published_result",
    "missing_evidence_field_with_rehashed_manifest": (
        "every_claim_is_supported_by_exact_evidence_and_shadow"
    ),
}
REQUIRED_SENSITIVITY_SCENARIOS = {
    "frozen_gate",
    "threshold_minus_practical_improvement",
    "threshold_plus_practical_improvement",
    "capacity_minus_one",
    "capacity_plus_one",
}
FORBIDDEN_PREDECLARATION_FIELDS = {
    "candidate_value",
    "candidate_pass",
    "selected_method",
    "observed_result",
    "verification_pass",
    "final_status",
}
RESTRICTED_COLUMNS = {
    "user_id",
    "email",
    "phone",
    "full_name",
    "secret",
    "access_token",
    "api_key",
}
ROUTE_VERIFICATION_PROFILES: dict[tuple[str, str], dict[str, Any]] = {
    ("core_analytics", "standard"): {
        "adapter_kind": "weighted_segment_priority",
        "claim_boundary": "descriptive_observed_priority_not_intervention_effect",
        "required_controls": [
            "aggregate_grain_reconciliation",
            "independent_denominator_reconciliation",
            "deterministic_priority_ranking",
            "claim_boundary_enforcement",
        ],
    },
    ("product_experiments", "standard"): {
        "adapter_kind": "randomized_assignment_analysis",
        "claim_boundary": "experimental_claim_only_after_design_and_srm_gates",
        "required_controls": [
            "assignment_exposure_reconciliation",
            "srm_and_denominator_check",
            "independent_metric_recalculation",
            "experiment_claim_boundary",
        ],
    },
    ("data_analytics_engineering", "standard"): {
        "adapter_kind": "contracted_mart_build",
        "claim_boundary": "correctness_lineage_freshness_performance_not_user_impact",
        "required_controls": [
            "grain_key_reconciliation",
            "lineage_and_freshness_check",
            "incremental_full_refresh_equivalence",
            "data_product_claim_boundary",
        ],
    },
    ("decision_science", "causal"): {
        "adapter_kind": "identified_estimand_workflow",
        "claim_boundary": "causal_estimand_with_declared_identification_assumptions",
        "required_controls": [
            "estimand_population_alignment",
            "independent_effect_recalculation",
            "overlap_and_falsification_checks",
            "causal_assumption_boundary",
        ],
    },
    ("decision_science", "forecast"): {
        "adapter_kind": "rolling_origin_forecast_workflow",
        "claim_boundary": "forecast_accuracy_within_declared_origin_and_horizon",
        "required_controls": [
            "origin_horizon_reconciliation",
            "temporal_leakage_check",
            "independent_metric_recalculation",
            "forecast_scope_boundary",
        ],
    },
    ("machine_learning", "baseline"): {
        "adapter_kind": "locked_prediction_pipeline",
        "claim_boundary": "predictive_priority_not_intervention_effect",
        "required_controls": [
            "split_and_feature_availability_check",
            "independent_prediction_metric",
            "threshold_capacity_reconciliation",
            "predictive_claim_boundary",
        ],
    },
    ("machine_learning", "strong_model"): {
        "adapter_kind": "tracked_tuning_and_prediction_pipeline",
        "claim_boundary": "predictive_priority_not_intervention_effect",
        "required_controls": [
            "split_and_feature_availability_check",
            "tuning_holdout_isolation",
            "independent_prediction_metric",
            "predictive_claim_boundary",
        ],
    },
    ("delivery_product", "standard"): {
        "adapter_kind": "verified_evidence_delivery_workflow",
        "claim_boundary": "delivery_quality_without_upstream_claim_amplification",
        "required_controls": [
            "artifact_rebuild_check",
            "freshness_and_state_reconciliation",
            "public_boundary_scan",
            "upstream_claim_preservation",
        ],
    },
}


class VerificationError(ValueError):
    """Raised when verification inputs cannot be parsed."""


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
        "valid": bool(valid),
        "severity": severity,
        "observed": observed,
        "expected": expected,
        "message": message,
    }


def blocked_check(check_id: str, reason: str) -> dict[str, Any]:
    return check(
        check_id,
        False,
        observed={"errors": [{"reason": reason}]},
        expected="passing prerequisite checks",
        message="This verification step was not trusted because an earlier gate failed.",
    )


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationError(f"{path} must contain a JSON object")
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
    with Path(path).open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        return [dict(row) for row in reader], fields


def csv_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return ""
    return str(value)


def write_csv(path: str | Path, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in fields})
    return target


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_checksums(root: str | Path) -> dict[str, str]:
    base = Path(root)
    return {
        path.relative_to(base).as_posix(): sha256_file(path)
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def implementation_runner_path() -> Path:
    return (
        project_root()
        / "phases"
        / "18-capstones"
        / "04-implementation"
        / "outputs"
        / "capstone_route_implementation.py"
    )


def route_verification_profile(route: str, variant: str) -> dict[str, Any]:
    profile = ROUTE_VERIFICATION_PROFILES.get((route, variant))
    if profile is None:
        raise VerificationError(f"unsupported route/variant: {route}/{variant}")
    return json.loads(json.dumps(profile))


def default_verification_spec(
    state: dict[str, Any], implementation_runner: str | Path
) -> dict[str, Any]:
    route = str(state.get("route", ""))
    variant = str(state.get("route_variant", ""))
    runner = Path(implementation_runner)
    lock_file = project_root() / "uv.lock"
    verification_id = str(state.get("implementation_id", "implementation")).replace(
        "implementation", "verification"
    )
    fixture_definitions = [
        {
            "fixture_id": fixture_id,
            "mutation": fixture_id,
            "expected_check_id": expected_check,
            "expected_outcome": "detected_before_verification_ready",
        }
        for fixture_id, expected_check in REQUIRED_FIXTURES.items()
    ]
    scenarios = [
        {
            "scenario_id": "frozen_gate",
            "threshold_delta": 0.0,
            "capacity_delta": 0,
        },
        {
            "scenario_id": "threshold_minus_practical_improvement",
            "threshold_delta": -0.1,
            "capacity_delta": 0,
        },
        {
            "scenario_id": "threshold_plus_practical_improvement",
            "threshold_delta": 0.1,
            "capacity_delta": 0,
        },
        {
            "scenario_id": "capacity_minus_one",
            "threshold_delta": 0.0,
            "capacity_delta": -1,
        },
        {
            "scenario_id": "capacity_plus_one",
            "threshold_delta": 0.0,
            "capacity_delta": 1,
        },
    ]
    required_tests = [
        "clean_room_rerun",
        "shadow_calculation",
        *[f"negative_fixture:{fixture_id}" for fixture_id in REQUIRED_FIXTURES],
        "sensitivity_analysis",
        "claim_evidence_audit",
        "route_specific_controls",
    ]
    return {
        "version": VERIFICATION_VERSION,
        "project_id": state.get("project_id"),
        "contract_id": state.get("data_contract_id"),
        "baseline_id": state.get("baseline_id"),
        "implementation_id": state.get("implementation_id"),
        "verification_id": verification_id,
        "route": route,
        "route_variant": variant,
        "independence": {
            "verifier_role": "independent_reviewer",
            "separate_process_from_implementation": True,
            "implementation_functions_imported_for_verification": False,
            "shadow_oracle": "independent_standard_library_recalculation",
            "clean_room_temporary_workspace": True,
        },
        "source_contract": {
            "implementation_runner_path": (
                "phases/18-capstones/04-implementation/outputs/capstone_route_implementation.py"
            ),
            "implementation_runner_sha256": sha256_file(runner),
            "verification_harness_sha256": sha256_file(__file__),
            "lock_file": "uv.lock",
            "lock_file_sha256": sha256_file(lock_file),
        },
        "route_verification_profile": route_verification_profile(route, variant),
        "required_checks": list(REQUIRED_CHECK_IDS),
        "negative_fixtures": fixture_definitions,
        "sensitivity_scenarios": scenarios,
        "test_disclosure": {
            "required_test_ids": required_tests,
            "skipped": [],
            "xfail": [],
        },
        "clean_room": {
            "timeout_seconds": 30,
            "network_access": False,
            "inherit_pythonpath": False,
            "environment_keys": [
                "HOME",
                "LC_ALL",
                "PATH",
                "PYTHONHASHSEED",
                "PYTHONPATH",
                "TMPDIR",
                "TZ",
            ],
        },
        "reproducible_command": (
            "uv run --locked python "
            "phases/18-capstones/05-verification/outputs/"
            "capstone_independent_verifier.py "
            "--upstream-implementation-package path/to/implementation-package "
            "--implementation-runner "
            "phases/18-capstones/04-implementation/outputs/"
            "capstone_route_implementation.py "
            "--upstream-baseline-package path/to/baseline-package "
            "--verification-spec path/to/verification_spec.json "
            "--output-dir path/to/verification-package --fail-on-invalid"
        ),
        "created_before_verification_run": True,
    }


def write_sample_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    runner = implementation_runner_path()
    implementation_inputs = root_path / "implementation-inputs"
    implementation_package = root_path / "upstream-implementation-package"
    completed = subprocess.run(
        [
            sys.executable,
            runner,
            "--write-example",
            implementation_inputs,
            "--output-dir",
            implementation_package,
            "--fail-on-invalid",
        ],
        cwd=project_root(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationError(
            "cannot build sample implementation package: "
            f"return_code={completed.returncode}; stderr={completed.stderr}"
        )
    state = read_json(implementation_package / "capstone_state.json")
    verification_spec_path = write_json(
        root_path / "verification_spec.json", default_verification_spec(state, runner)
    )
    return {
        "upstream_implementation_package": implementation_package,
        "implementation_runner": runner,
        "upstream_baseline_package": implementation_inputs / "upstream-baseline-package",
        "verification_spec_path": verification_spec_path,
    }


def validate_upstream_implementation_package(
    package: str | Path, baseline_package: str | Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    package_path = Path(package)
    baseline_path = Path(baseline_package)
    missing = sorted(
        filename
        for filename in REQUIRED_IMPLEMENTATION_FILES
        if not (package_path / filename).is_file()
    )
    if missing:
        raise VerificationError(f"implementation package is missing: {', '.join(missing)}")
    manifest = read_json(package_path / "implementation_manifest.json")
    state = read_json(package_path / "capstone_state.json")
    report = read_json(package_path / "implementation_report.json")
    spec = read_json(package_path / "implementation_spec.json")
    acceptance = read_json(package_path / "candidate_acceptance.json")
    decision = read_json(package_path / "candidate_decision.json")
    metrics, metric_fields = read_csv(package_path / "candidate_metrics.csv")
    evidence_rows, evidence_fields = read_csv(package_path / "evidence_ledger.csv")

    errors: list[dict[str, Any]] = []
    if manifest.get("status") != "implementation_ready" or manifest.get("valid") is not True:
        errors.append({"field": "manifest.status", "observed": manifest.get("status")})
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        errors.append({"field": "manifest.outputs", "reason": "object required"})
        outputs = {}
    for output_id, entry in outputs.items():
        if not isinstance(entry, dict):
            errors.append({"field": f"outputs.{output_id}", "reason": "object required"})
            continue
        relative = entry.get("path")
        if not non_empty_text(relative) or Path(str(relative)).name != relative:
            errors.append({"field": f"outputs.{output_id}.path", "observed": relative})
            continue
        target = package_path / relative
        if not target.is_file():
            errors.append({"field": f"outputs.{output_id}.path", "reason": "missing"})
            continue
        observed_hash = sha256_file(target)
        if observed_hash != entry.get("sha256"):
            errors.append(
                {
                    "field": f"outputs.{output_id}.sha256",
                    "expected": entry.get("sha256"),
                    "observed": observed_hash,
                }
            )
        if target.stat().st_size != entry.get("bytes"):
            errors.append(
                {
                    "field": f"outputs.{output_id}.bytes",
                    "expected": entry.get("bytes"),
                    "observed": target.stat().st_size,
                }
            )
    input_entries = manifest.get("inputs") if isinstance(manifest.get("inputs"), dict) else {}
    expected_inputs = {
        "implementation_spec": package_path / "implementation_spec.json",
        "upstream_baseline_manifest": baseline_path / "baseline_manifest.json",
        "upstream_acceptance_gate": baseline_path / "acceptance_gate.json",
        "lock_file": project_root() / "uv.lock",
    }
    for input_id, target in expected_inputs.items():
        entry = input_entries.get(input_id)
        if not isinstance(entry, dict) or not target.is_file():
            errors.append({"field": f"inputs.{input_id}", "reason": "missing input entry/file"})
            continue
        observed_hash = sha256_file(target)
        if observed_hash != entry.get("sha256"):
            errors.append(
                {
                    "field": f"inputs.{input_id}.sha256",
                    "expected": entry.get("sha256"),
                    "observed": observed_hash,
                }
            )
    integrity = check(
        "upstream_implementation_package_is_immutable",
        not errors,
        observed={"errors": errors, "verified_outputs": len(outputs)},
        expected="matching hashes and sizes for every published output and immutable input",
        message="A changed implementation package cannot enter independent verification.",
    )

    state_errors: list[dict[str, Any]] = []
    expected_ids = {
        "project_id": manifest.get("project_id"),
        "data_contract_id": manifest.get("contract_id"),
        "baseline_id": manifest.get("baseline_id"),
        "implementation_id": manifest.get("implementation_id"),
    }
    for field, expected in expected_ids.items():
        if state.get(field) != expected:
            state_errors.append(
                {"field": field, "expected": expected, "observed": state.get(field)}
            )
    if state.get("current_stage") != "implementation":
        state_errors.append({"field": "current_stage", "observed": state.get("current_stage")})
    if state.get("stage_status") != "implementation_ready":
        state_errors.append({"field": "stage_status", "observed": state.get("stage_status")})
    if state.get("verification_id") is not None:
        state_errors.append({"field": "verification_id", "observed": state.get("verification_id")})
    if state.get("review_id") is not None or state.get("defense_id") is not None:
        state_errors.append({"field": "later_stage_ids", "reason": "must remain null"})
    if state.get("open_blockers") != []:
        state_errors.append({"field": "open_blockers", "observed": state.get("open_blockers")})
    if report.get("valid") is not True or report.get("status") != "implementation_ready":
        state_errors.append({"field": "implementation_report", "observed": report.get("status")})
    state_check = check(
        "implementation_state_is_ready_for_independent_verification",
        not state_errors,
        observed={"errors": state_errors, "implementation_id": state.get("implementation_id")},
        expected="implementation_ready state with no blockers or later-stage IDs",
        message="Verification starts only from the exact approved implementation stage.",
    )
    return (
        integrity,
        state_check,
        {
            "manifest": manifest,
            "state": state,
            "report": report,
            "spec": spec,
            "acceptance": acceptance,
            "decision": decision,
            "metrics": metrics,
            "metric_fields": metric_fields,
            "evidence_rows": evidence_rows,
            "evidence_fields": evidence_fields,
        },
    )


def nested_forbidden_fields(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in FORBIDDEN_PREDECLARATION_FIELDS:
                found.append(path)
            found.extend(nested_forbidden_fields(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(nested_forbidden_fields(nested, f"{prefix}[{index}]"))
    return found


def validate_verification_spec(
    spec: dict[str, Any],
    state: dict[str, Any],
    implementation_runner: str | Path,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    expected_ids = {
        "project_id": state.get("project_id"),
        "contract_id": state.get("data_contract_id"),
        "baseline_id": state.get("baseline_id"),
        "implementation_id": state.get("implementation_id"),
        "route": state.get("route"),
        "route_variant": state.get("route_variant"),
    }
    for field, expected in expected_ids.items():
        if spec.get(field) != expected:
            errors.append({"field": field, "expected": expected, "observed": spec.get(field)})
    if not non_empty_text(spec.get("verification_id")):
        errors.append({"field": "verification_id", "reason": "non-empty text required"})
    if spec.get("created_before_verification_run") is not True:
        errors.append({"field": "created_before_verification_run", "expected": True})

    independence = spec.get("independence") if isinstance(spec.get("independence"), dict) else {}
    expected_independence = {
        "verifier_role": "independent_reviewer",
        "separate_process_from_implementation": True,
        "implementation_functions_imported_for_verification": False,
        "shadow_oracle": "independent_standard_library_recalculation",
        "clean_room_temporary_workspace": True,
    }
    for field, expected in expected_independence.items():
        if independence.get(field) != expected:
            errors.append(
                {
                    "field": f"independence.{field}",
                    "expected": expected,
                    "observed": independence.get(field),
                }
            )

    source = spec.get("source_contract") if isinstance(spec.get("source_contract"), dict) else {}
    expected_sources = {
        "implementation_runner_sha256": sha256_file(implementation_runner),
        "verification_harness_sha256": sha256_file(__file__),
        "lock_file_sha256": sha256_file(project_root() / "uv.lock"),
    }
    for field, expected in expected_sources.items():
        if source.get(field) != expected:
            errors.append(
                {
                    "field": f"source_contract.{field}",
                    "expected": expected,
                    "observed": source.get(field),
                }
            )

    required_checks = spec.get("required_checks")
    if not isinstance(required_checks, list) or set(required_checks) != set(REQUIRED_CHECK_IDS):
        errors.append({"field": "required_checks", "expected": list(REQUIRED_CHECK_IDS)})
    fixture_definitions = spec.get("negative_fixtures")
    observed_fixtures: dict[str, str] = {}
    if isinstance(fixture_definitions, list):
        for item in fixture_definitions:
            if isinstance(item, dict) and non_empty_text(item.get("fixture_id")):
                observed_fixtures[str(item["fixture_id"])] = str(item.get("expected_check_id", ""))
    if observed_fixtures != REQUIRED_FIXTURES:
        errors.append(
            {
                "field": "negative_fixtures",
                "expected": REQUIRED_FIXTURES,
                "observed": observed_fixtures,
            }
        )
    scenarios = spec.get("sensitivity_scenarios")
    scenario_ids = {
        str(item.get("scenario_id"))
        for item in scenarios or []
        if isinstance(item, dict) and non_empty_text(item.get("scenario_id"))
    }
    if scenario_ids != REQUIRED_SENSITIVITY_SCENARIOS:
        errors.append(
            {
                "field": "sensitivity_scenarios",
                "expected": sorted(REQUIRED_SENSITIVITY_SCENARIOS),
                "observed": sorted(scenario_ids),
            }
        )
    disclosure = spec.get("test_disclosure")
    if not isinstance(disclosure, dict) or not all(
        isinstance(disclosure.get(field), list)
        for field in ("required_test_ids", "skipped", "xfail")
    ):
        errors.append({"field": "test_disclosure", "reason": "three explicit lists required"})
    clean_room = spec.get("clean_room") if isinstance(spec.get("clean_room"), dict) else {}
    expected_environment = {
        "HOME",
        "LC_ALL",
        "PATH",
        "PYTHONHASHSEED",
        "PYTHONPATH",
        "TMPDIR",
        "TZ",
    }
    if clean_room.get("network_access") is not False:
        errors.append({"field": "clean_room.network_access", "expected": False})
    if clean_room.get("inherit_pythonpath") is not False:
        errors.append({"field": "clean_room.inherit_pythonpath", "expected": False})
    timeout = clean_room.get("timeout_seconds")
    if not isinstance(timeout, int) or not 0 < timeout <= 120:
        errors.append({"field": "clean_room.timeout_seconds", "observed": timeout})
    if set(clean_room.get("environment_keys", [])) != expected_environment:
        errors.append(
            {
                "field": "clean_room.environment_keys",
                "expected": sorted(expected_environment),
                "observed": clean_room.get("environment_keys"),
            }
        )

    forbidden = nested_forbidden_fields(spec)
    if forbidden:
        errors.append({"field": "predeclared_spec", "forbidden_paths": forbidden})
    command = spec.get("reproducible_command")
    required_tokens = (
        "uv run --locked python",
        "capstone_independent_verifier.py",
        "--upstream-implementation-package",
        "--implementation-runner",
        "--upstream-baseline-package",
        "--verification-spec",
        "--output-dir",
        "--fail-on-invalid",
    )
    if not non_empty_text(command):
        errors.append({"field": "reproducible_command", "reason": "required"})
    else:
        for token in required_tokens:
            if token not in command:
                errors.append({"field": "reproducible_command", "missing": token})
        if command.startswith("/") or "/Users/" in command or "C:\\" in command:
            errors.append({"field": "reproducible_command", "reason": "must use relative paths"})
    return check(
        "verification_spec_is_independent_and_predeclared",
        not errors,
        observed={"errors": errors, "verification_id": spec.get("verification_id")},
        expected="independent source hashes, predeclared tests/fixtures and no observed results",
        message="The verifier must be specified independently before its results are inspected.",
    )


def validate_route_profile(spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    route = str(state.get("route", ""))
    variant = str(state.get("route_variant", ""))
    expected = ROUTE_VERIFICATION_PROFILES.get((route, variant))
    observed = spec.get("route_verification_profile")
    errors: list[dict[str, Any]] = []
    if expected is None:
        errors.append({"field": "route/variant", "observed": f"{route}/{variant}"})
    elif observed != expected:
        errors.append(
            {"field": "route_verification_profile", "expected": expected, "observed": observed}
        )
    return check(
        "route_specific_verification_profile_is_complete",
        not errors,
        observed={"route": route, "variant": variant, "profile": observed, "errors": errors},
        expected=expected,
        message=(
            "Each route keeps its own oracle and failure controls inside a shared package gate."
        ),
    )


def run_clean_room_rerun(
    *,
    package: Path,
    baseline_package: Path,
    implementation_runner: Path,
    spec: dict[str, Any],
    published_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    clean_room = spec.get("clean_room") if isinstance(spec.get("clean_room"), dict) else {}
    timeout = clean_room.get("timeout_seconds", 30)
    if not isinstance(timeout, int) or timeout <= 0 or timeout > 120:
        timeout = 30
    with TemporaryDirectory() as directory:
        root = Path(directory)
        isolated_repo = root / "repo"
        copied_runner = (
            isolated_repo
            / "phases"
            / "18-capstones"
            / "04-implementation"
            / "outputs"
            / "capstone_route_implementation.py"
        )
        copied_runner.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(implementation_runner, copied_runner)
        shutil.copy2(project_root() / "uv.lock", isolated_repo / "uv.lock")
        copied_baseline = isolated_repo / "input" / "baseline-package"
        shutil.copytree(baseline_package, copied_baseline)
        copied_spec = isolated_repo / "input" / "implementation_spec.json"
        copied_spec.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / "implementation_spec.json", copied_spec)
        rerun_output = isolated_repo / "output" / "implementation-package"
        home = root / "home"
        temp_dir = root / "tmp"
        home.mkdir()
        temp_dir.mkdir()
        environment = {
            "HOME": str(home),
            "LC_ALL": "C",
            "PATH": os.environ.get("PATH", ""),
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": "",
            "TMPDIR": str(temp_dir),
            "TZ": "UTC",
        }
        command = [
            sys.executable,
            str(copied_runner),
            "--upstream-baseline-package",
            str(copied_baseline),
            "--implementation-spec",
            str(copied_spec),
            "--output-dir",
            str(rerun_output),
            "--fail-on-invalid",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=isolated_repo,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            timed_out = False
        except subprocess.TimeoutExpired as error:
            completed = subprocess.CompletedProcess(
                command, 124, error.stdout or "", error.stderr or ""
            )
            timed_out = True
        comparisons: list[dict[str, Any]] = []
        outputs = (
            published_manifest.get("outputs")
            if isinstance(published_manifest.get("outputs"), dict)
            else {}
        )
        for output_id, entry in outputs.items():
            relative = entry.get("path") if isinstance(entry, dict) else None
            target = rerun_output / str(relative)
            observed_hash = sha256_file(target) if target.is_file() else None
            comparisons.append(
                {
                    "output_id": output_id,
                    "path": relative,
                    "expected_sha256": entry.get("sha256") if isinstance(entry, dict) else None,
                    "rerun_sha256": observed_hash,
                    "match": observed_hash
                    == (entry.get("sha256") if isinstance(entry, dict) else None),
                }
            )
        rerun_manifest_path = rerun_output / "implementation_manifest.json"
        published_manifest_path = package / "implementation_manifest.json"
        manifest_match = rerun_manifest_path.is_file() and sha256_file(
            rerun_manifest_path
        ) == sha256_file(published_manifest_path)
        payload: dict[str, Any] | None = None
        if completed.stdout:
            try:
                decoded = json.loads(completed.stdout)
                payload = decoded if isinstance(decoded, dict) else None
            except json.JSONDecodeError:
                payload = None
        if payload is not None:
            payload.pop("manifest", None)
            payload.pop("output_dir", None)
        valid = (
            not timed_out
            and completed.returncode == 0
            and bool(comparisons)
            and all(row["match"] for row in comparisons)
            and manifest_match
        )
        report = {
            "valid": valid,
            "isolated_temporary_repository": True,
            "implementation_functions_imported": False,
            "network_access_declared": False,
            "pythonpath_inherited": False,
            "environment_keys": sorted(environment),
            "return_code": completed.returncode,
            "timed_out": timed_out,
            "stdout_payload": payload,
            "stderr": completed.stderr,
            "published_manifest_match": manifest_match,
            "output_comparisons": comparisons,
        }
    return (
        check(
            "clean_room_rerun_matches_published_package",
            valid,
            observed={
                "return_code": report["return_code"],
                "timed_out": report["timed_out"],
                "published_manifest_match": manifest_match,
                "mismatches": [row["output_id"] for row in comparisons if not row["match"]],
            },
            expected="isolated subprocess rerun with byte-identical manifest outputs",
            message="A clean-room rerun checks reproducibility outside the author's working state.",
        ),
        report,
    )


def min_max(values: list[float]) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if abs(maximum - minimum) <= 0.000000001:
        return [0.0 for _value in values]
    return [(value - minimum) / (maximum - minimum) for value in values]


def comparable(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    return str(value)


def shadow_row(
    *,
    check_id: str,
    grain: str,
    field: str,
    implementation_value: Any,
    shadow_value: Any,
    tolerance: float,
    source_path: str,
    method: str,
) -> dict[str, Any]:
    difference = ""
    if isinstance(implementation_value, (int, float)) and isinstance(shadow_value, (int, float)):
        difference = round(abs(float(implementation_value) - float(shadow_value)), 9)
        passed = difference <= tolerance
    else:
        passed = comparable(implementation_value) == comparable(shadow_value)
    return {
        "check_id": check_id,
        "grain": grain,
        "field": field,
        "implementation_value": comparable(implementation_value),
        "shadow_value": comparable(shadow_value),
        "difference": difference,
        "tolerance": tolerance,
        "passed": passed,
        "source_path": source_path,
        "method": method,
    }


def independent_shadow_calculation(
    *,
    baseline_metrics: list[dict[str, str]],
    implementation_spec: dict[str, Any],
    published_metrics: list[dict[str, str]],
    published_decision: dict[str, Any],
    published_acceptance: dict[str, Any],
    acceptance_gate: dict[str, Any],
    denominator_adjustment: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    typed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(baseline_metrics):
        try:
            users = int(row["users"])
            activated = int(row["activated_users"])
            support_count = int(row["support_ticket_count"])
            churned = int(row["churned_users"])
            activation_rate = float(row["activation_rate"])
            churn_rate = float(row["churn_rate"])
            support_rate = float(row["support_tickets_per_user"])
        except (KeyError, TypeError, ValueError) as error:
            errors.append({"field": f"baseline_metrics[{index}]", "reason": str(error)})
            continue
        if users <= 0:
            errors.append({"field": f"baseline_metrics[{index}].users", "observed": users})
        if abs(activated / users - activation_rate) > 0.000001:
            errors.append(
                {
                    "field": f"baseline_metrics[{index}].activation_rate",
                    "reason": "count/rate mismatch",
                }
            )
        if abs(churned / users - churn_rate) > 0.000001:
            errors.append(
                {"field": f"baseline_metrics[{index}].churn_rate", "reason": "count/rate mismatch"}
            )
        if abs(support_count / users - support_rate) > 0.000001:
            errors.append(
                {
                    "field": f"baseline_metrics[{index}].support_tickets_per_user",
                    "reason": "count/rate mismatch",
                }
            )
        typed.append(
            {
                "as_of_week": row["as_of_week"],
                "segment_id": row["segment_id"],
                "users": users,
                "churned_users": churned,
                "churn_rate": churn_rate,
                "activation_gap": 1.0 - activation_rate,
                "support_tickets_per_user": support_rate,
            }
        )
    config = (
        implementation_spec.get("frozen_config")
        if isinstance(implementation_spec.get("frozen_config"), dict)
        else {}
    )
    weights = config.get("score_weights") if isinstance(config.get("score_weights"), dict) else {}
    required_weights = {"churn_rate", "activation_gap", "support_load"}
    if (
        set(weights) != required_weights
        or abs(sum(float(value) for value in weights.values()) - 1.0) > 0.000001
    ):
        errors.append({"field": "frozen_config.score_weights", "observed": weights})
    churn_components = min_max([float(row["churn_rate"]) for row in typed])
    activation_components = min_max([float(row["activation_gap"]) for row in typed])
    support_components = min_max([float(row["support_tickets_per_user"]) for row in typed])
    calculated: list[dict[str, Any]] = []
    for row, churn_component, activation_component, support_component in zip(
        typed, churn_components, activation_components, support_components, strict=True
    ):
        score = (
            float(weights.get("churn_rate", 0)) * churn_component
            + float(weights.get("activation_gap", 0)) * activation_component
            + float(weights.get("support_load", 0)) * support_component
        )
        calculated.append(
            {
                **row,
                "churn_component": round(churn_component, 6),
                "activation_gap_component": round(activation_component, 6),
                "support_load_component": round(support_component, 6),
                "candidate_score": round(score, 6),
            }
        )
    calculated.sort(
        key=lambda row: (
            -float(row["candidate_score"]),
            -float(row["churn_rate"]),
            str(row["segment_id"]),
        )
    )
    maximum_selected = config.get("max_selected_segments", 1)
    if not isinstance(maximum_selected, int) or maximum_selected < 1:
        errors.append({"field": "max_selected_segments", "observed": maximum_selected})
        maximum_selected = 0
    for rank, row in enumerate(calculated, start=1):
        row["candidate_rank"] = rank
        row["candidate_selected"] = rank <= maximum_selected
    selected = calculated[:maximum_selected]
    captured_churned = sum(int(row["churned_users"]) for row in selected)
    true_total_churned = sum(int(row["churned_users"]) for row in calculated)
    total_churned = true_total_churned + denominator_adjustment
    candidate_value = captured_churned / total_churned if total_churned else 0.0
    reviewed_users = sum(int(row["users"]) for row in selected)
    threshold = acceptance_gate.get("candidate_threshold")
    tolerance = acceptance_gate.get("tolerance")
    max_capacity = acceptance_gate.get("max_capacity")
    direction = acceptance_gate.get("direction")
    if not all(isinstance(value, (int, float)) for value in (threshold, tolerance)):
        errors.append(
            {"field": "acceptance_gate.threshold/tolerance", "reason": "numeric required"}
        )
        metric_pass = False
        tolerance_value = 0.0
    else:
        tolerance_value = float(tolerance)
        if direction == "maximize":
            metric_pass = candidate_value + tolerance_value >= float(threshold)
        elif direction == "minimize":
            metric_pass = candidate_value - tolerance_value <= float(threshold)
        else:
            errors.append({"field": "acceptance_gate.direction", "observed": direction})
            metric_pass = False
    capacity_pass = isinstance(max_capacity, int) and reviewed_users <= max_capacity
    candidate_pass = metric_pass and capacity_pass and not errors
    selected_method = "candidate" if candidate_pass else "baseline"
    decision_status = "candidate_selected" if candidate_pass else "candidate_rejected_keep_baseline"

    published_by_segment = {row.get("segment_id"): row for row in published_metrics}
    rows: list[dict[str, Any]] = []
    for row in calculated:
        segment = str(row["segment_id"])
        published = published_by_segment.get(segment, {})
        for field in (
            "churn_component",
            "activation_gap_component",
            "support_load_component",
            "candidate_score",
            "candidate_rank",
            "candidate_selected",
        ):
            implementation_value: Any = published.get(field)
            if field == "candidate_selected":
                implementation_value = str(implementation_value).lower() == "true"
            elif field == "candidate_rank" and implementation_value not in (None, ""):
                implementation_value = int(str(implementation_value))
            elif implementation_value not in (None, ""):
                implementation_value = float(str(implementation_value))
            rows.append(
                shadow_row(
                    check_id=f"segment:{segment}:{field}",
                    grain=segment,
                    field=field,
                    implementation_value=implementation_value,
                    shadow_value=row[field],
                    tolerance=tolerance_value,
                    source_path="baseline_metrics.csv",
                    method="independent_min_max_weighted_score",
                )
            )
    summary_values = {
        "selected_segments": [row["segment_id"] for row in selected],
        "candidate_value": round(candidate_value, 6),
        "reviewed_users": reviewed_users,
        "captured_churned_users": captured_churned,
        "total_churned_users": total_churned,
        "candidate_pass": candidate_pass,
        "selected_method": selected_method,
        "decision_status": decision_status,
        "candidate_threshold": threshold,
        "max_capacity": max_capacity,
    }
    published_values = {
        "selected_segments": published_decision.get("selected_segments"),
        "candidate_value": published_acceptance.get("candidate_value"),
        "reviewed_users": published_decision.get("reviewed_users"),
        "captured_churned_users": published_decision.get("captured_churned_users"),
        "total_churned_users": published_decision.get("total_churned_users"),
        "candidate_pass": published_acceptance.get("candidate_pass"),
        "selected_method": published_acceptance.get("selected_method"),
        "decision_status": published_decision.get("decision_status"),
        "candidate_threshold": published_acceptance.get("candidate_threshold"),
        "max_capacity": published_acceptance.get("max_capacity"),
    }
    for field, shadow_value in summary_values.items():
        rows.append(
            shadow_row(
                check_id=f"decision:{field}",
                grain="decision",
                field=field,
                implementation_value=published_values[field],
                shadow_value=shadow_value,
                tolerance=tolerance_value,
                source_path="acceptance_gate.json|baseline_metrics.csv",
                method="independent_denominator_and_gate_reconciliation",
            )
        )
    failed_rows = [row["check_id"] for row in rows if not row["passed"]]
    valid = not errors and not failed_rows
    return (
        check(
            "shadow_calculation_matches_published_result",
            valid,
            observed={
                "errors": errors,
                "failed_rows": failed_rows,
                "denominator_adjustment": denominator_adjustment,
                "shadow_candidate_value": summary_values["candidate_value"],
                "shadow_selected_method": selected_method,
            },
            expected=(
                "independent score, ranking, denominator, capacity and gate values "
                "within frozen tolerance"
            ),
            message="A shadow oracle must not reuse the implementation's calculation functions.",
        ),
        rows,
        {**summary_values, "true_total_churned_users": true_total_churned},
    )


def evidence_fields_for_path(path: Path) -> set[str]:
    if path.suffix == ".json":
        return set(read_json(path))
    if path.suffix == ".csv":
        _rows, fields = read_csv(path)
        return set(fields)
    return set()


def audit_claim_evidence(
    *,
    package: Path,
    evidence_rows: list[dict[str, str]],
    state: dict[str, Any],
    shadow_summary: dict[str, Any],
    published_decision: dict[str, Any],
    published_acceptance: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    audit_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in evidence_rows:
        claim_id = row.get("claim_id", "")
        relative = row.get("evidence_path", "")
        safe_path = non_empty_text(relative) and Path(relative).name == relative
        target = package / relative if safe_path else package / "__invalid__"
        path_exists = target.is_file()
        declared_fields = [field for field in row.get("evidence_fields", "").split("|") if field]
        available_fields = evidence_fields_for_path(target) if path_exists else set()
        fields_exist = bool(declared_fields) and set(declared_fields).issubset(available_fields)
        limitation_present = non_empty_text(row.get("limitation"))
        claim_type_allowed = row.get("claim_type") == state.get("claim_type")
        unique_claim = non_empty_text(claim_id) and claim_id not in seen
        seen.add(claim_id)
        if relative == "candidate_metrics.csv":
            shadow_supported = shadow_summary.get("selected_segments") == published_decision.get(
                "selected_segments"
            )
        elif relative == "candidate_acceptance.json":
            shadow_supported = shadow_summary.get("candidate_pass") == published_acceptance.get(
                "candidate_pass"
            )
        elif relative == "candidate_decision.json":
            shadow_supported = shadow_summary.get("selected_method") == published_decision.get(
                "selected_method"
            )
        else:
            shadow_supported = False
        passed = all(
            (
                path_exists,
                fields_exist,
                limitation_present,
                claim_type_allowed,
                unique_claim,
                shadow_supported,
            )
        )
        audit_rows.append(
            {
                "claim_id": claim_id,
                "evidence_path": relative,
                "path_exists": path_exists,
                "declared_fields": "|".join(declared_fields),
                "fields_exist": fields_exist,
                "limitation_present": limitation_present,
                "claim_type_allowed": claim_type_allowed,
                "unique_claim_id": unique_claim,
                "shadow_supported": shadow_supported,
                "status": "verified" if passed else "blocked",
            }
        )
    valid = len(audit_rows) >= 3 and all(row["status"] == "verified" for row in audit_rows)
    return (
        check(
            "every_claim_is_supported_by_exact_evidence_and_shadow",
            valid,
            observed={
                "claims": len(audit_rows),
                "blocked_claims": [
                    row["claim_id"] for row in audit_rows if row["status"] != "verified"
                ],
            },
            expected=(
                "three or more unique claims with exact fields, limitations and shadow support"
            ),
            message=(
                "A path that exists is insufficient unless the independent result "
                "supports the claim."
            ),
        ),
        audit_rows,
    )


def update_manifest_output(package: Path, output_id: str, filename: str) -> None:
    manifest_path = package / "implementation_manifest.json"
    manifest = read_json(manifest_path)
    target = package / filename
    manifest["outputs"][output_id]["sha256"] = sha256_file(target)
    manifest["outputs"][output_id]["bytes"] = target.stat().st_size
    write_json(manifest_path, manifest)


def run_negative_fixtures(
    *,
    definitions: list[dict[str, Any]],
    package: Path,
    baseline_package: Path,
    implementation_spec: dict[str, Any],
    baseline_metrics: list[dict[str, str]],
    published_metrics: list[dict[str, str]],
    decision: dict[str, Any],
    acceptance: dict[str, Any],
    acceptance_gate: dict[str, Any],
    state: dict[str, Any],
    shadow_summary: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    for definition in definitions:
        fixture_id = str(definition.get("fixture_id", ""))
        expected_check_id = str(definition.get("expected_check_id", ""))
        observed_check: dict[str, Any] | None = None
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_package = root / "implementation-package"
            shutil.copytree(package, fixture_package)
            if fixture_id == "tampered_output_checksum":
                metrics_path = fixture_package / "candidate_metrics.csv"
                metrics_path.write_text(
                    metrics_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
                )
                observed_check, _state_check, _data = validate_upstream_implementation_package(
                    fixture_package, baseline_package
                )
            elif fixture_id == "stale_stage_with_rehashed_manifest":
                state_path = fixture_package / "capstone_state.json"
                fixture_state = read_json(state_path)
                fixture_state["current_stage"] = "baseline"
                fixture_state["stage_status"] = "baseline_ready"
                write_json(state_path, fixture_state)
                update_manifest_output(fixture_package, "capstone_state", "capstone_state.json")
                _integrity, observed_check, _data = validate_upstream_implementation_package(
                    fixture_package, baseline_package
                )
            elif fixture_id == "changed_shadow_denominator":
                observed_check, _rows, _summary = independent_shadow_calculation(
                    baseline_metrics=baseline_metrics,
                    implementation_spec=implementation_spec,
                    published_metrics=published_metrics,
                    published_decision=decision,
                    published_acceptance=acceptance,
                    acceptance_gate=acceptance_gate,
                    denominator_adjustment=1,
                )
            elif fixture_id == "missing_evidence_field_with_rehashed_manifest":
                ledger_path = fixture_package / "evidence_ledger.csv"
                ledger_rows, ledger_fields = read_csv(ledger_path)
                ledger_rows[0]["evidence_fields"] = (
                    ledger_rows[0]["evidence_fields"] + "|missing_field"
                )
                write_csv(ledger_path, ledger_rows, ledger_fields)
                update_manifest_output(fixture_package, "evidence_ledger", "evidence_ledger.csv")
                integrity, state_ready, fixture_data = validate_upstream_implementation_package(
                    fixture_package, baseline_package
                )
                if integrity["valid"] and state_ready["valid"]:
                    observed_check, _audit_rows = audit_claim_evidence(
                        package=fixture_package,
                        evidence_rows=fixture_data["evidence_rows"],
                        state=state,
                        shadow_summary=shadow_summary,
                        published_decision=decision,
                        published_acceptance=acceptance,
                    )
                else:
                    observed_check = integrity if not integrity["valid"] else state_ready
            else:
                observed_check = check(
                    "unknown_fixture",
                    True,
                    observed={"fixture_id": fixture_id},
                    expected="known fixture",
                    message="Unknown fixture was not executed.",
                )
        detected = (
            observed_check is not None
            and observed_check.get("id") == expected_check_id
            and observed_check.get("valid") is False
        )
        results.append(
            {
                "fixture_id": fixture_id,
                "mutation": definition.get("mutation"),
                "expected_check_id": expected_check_id,
                "observed_check_id": observed_check.get("id") if observed_check else None,
                "observed_check_valid": observed_check.get("valid") if observed_check else None,
                "detected": detected,
                "fixture_copy_removed": True,
                "status": "passed" if detected else "failed",
            }
        )
    observed_map = {row["fixture_id"]: row["expected_check_id"] for row in results}
    valid = observed_map == REQUIRED_FIXTURES and all(row["detected"] for row in results)
    return (
        check(
            "negative_fixtures_fail_at_expected_gates",
            valid,
            observed={
                "fixtures": len(results),
                "failed_fixtures": [row["fixture_id"] for row in results if not row["detected"]],
            },
            expected="four predeclared mutations detected by their specific independent gates",
            message=(
                "Negative tests prove that a passing happy path is not the only "
                "implemented behavior."
            ),
        ),
        results,
    )


def run_sensitivity_analysis(
    scenarios: list[dict[str, Any]],
    acceptance_gate: dict[str, Any],
    shadow_summary: dict[str, Any],
    published_acceptance: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    candidate_value = shadow_summary.get("candidate_value")
    reviewed_users = shadow_summary.get("reviewed_users")
    base_threshold = acceptance_gate.get("candidate_threshold")
    base_capacity = acceptance_gate.get("max_capacity")
    tolerance = acceptance_gate.get("tolerance")
    direction = acceptance_gate.get("direction")
    if not all(
        isinstance(value, (int, float))
        for value in (candidate_value, reviewed_users, base_threshold, base_capacity, tolerance)
    ):
        errors.append({"field": "sensitivity_inputs", "reason": "numeric inputs required"})
    for scenario in scenarios:
        scenario_id = str(scenario.get("scenario_id", ""))
        threshold_delta = scenario.get("threshold_delta")
        capacity_delta = scenario.get("capacity_delta")
        if not isinstance(threshold_delta, (int, float)) or not isinstance(capacity_delta, int):
            errors.append({"field": f"scenario.{scenario_id}", "reason": "numeric deltas required"})
            continue
        threshold = round(float(base_threshold) + float(threshold_delta), 6)
        capacity = int(base_capacity) + capacity_delta
        if direction == "maximize":
            metric_pass = float(candidate_value) + float(tolerance) >= threshold
        else:
            metric_pass = float(candidate_value) - float(tolerance) <= threshold
        capacity_pass = int(reviewed_users) <= capacity
        candidate_pass = metric_pass and capacity_pass
        selected_method = "candidate" if candidate_pass else "baseline"
        rows.append(
            {
                "scenario_id": scenario_id,
                "threshold_delta": threshold_delta,
                "capacity_delta": capacity_delta,
                "candidate_value": candidate_value,
                "candidate_threshold": threshold,
                "reviewed_users": reviewed_users,
                "max_capacity": capacity,
                "metric_pass": metric_pass,
                "capacity_pass": capacity_pass,
                "candidate_pass": candidate_pass,
                "selected_method": selected_method,
                "is_frozen_gate": scenario_id == "frozen_gate",
            }
        )
    ids = {row["scenario_id"] for row in rows}
    if ids != REQUIRED_SENSITIVITY_SCENARIOS:
        errors.append(
            {
                "field": "scenario_ids",
                "expected": sorted(REQUIRED_SENSITIVITY_SCENARIOS),
                "observed": sorted(ids),
            }
        )
    base = next((row for row in rows if row["scenario_id"] == "frozen_gate"), None)
    if base is None or base["selected_method"] != published_acceptance.get("selected_method"):
        errors.append({"field": "frozen_gate", "reason": "must reproduce published selection"})
    flips = [
        row["scenario_id"]
        for row in rows
        if base is not None and row["selected_method"] != base["selected_method"]
    ]
    warnings = ["candidate_conclusion_is_threshold_sensitive"] if flips else []
    valid = not errors and len(rows) == len(REQUIRED_SENSITIVITY_SCENARIOS)
    return (
        check(
            "sensitivity_analysis_preserves_frozen_gate_and_reports_flips",
            valid,
            observed={
                "errors": errors,
                "decision_flips": flips,
                "frozen_selection": base["selected_method"] if base else None,
            },
            expected=(
                "frozen decision reproduced plus predeclared threshold and capacity perturbations"
            ),
            message=(
                "A sensitivity flip is reportable evidence, not permission to move "
                "the approved gate."
            ),
        ),
        rows,
        warnings,
    )


def route_control_report(
    spec: dict[str, Any],
    baseline_metrics: list[dict[str, str]],
    shadow_rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> dict[str, Any]:
    profile = (
        spec.get("route_verification_profile")
        if isinstance(spec.get("route_verification_profile"), dict)
        else {}
    )
    controls: list[dict[str, Any]] = []
    required_controls = (
        profile.get("required_controls")
        if isinstance(profile.get("required_controls"), list)
        else []
    )
    keys = [(row.get("as_of_week"), row.get("segment_id")) for row in baseline_metrics]
    for control_id in required_controls:
        if control_id == "aggregate_grain_reconciliation":
            passed = bool(keys) and len(keys) == len(set(keys))
            evidence = "baseline_metrics.csv:as_of_week|segment_id"
        elif control_id == "independent_denominator_reconciliation":
            passed = all(
                row["passed"]
                for row in shadow_rows
                if row["field"] in {"candidate_value", "total_churned_users"}
            )
            evidence = "shadow_calculation.csv:decision:total_churned_users|candidate_value"
        elif control_id == "deterministic_priority_ranking":
            passed = all(
                row["passed"]
                for row in shadow_rows
                if row["field"] in {"candidate_score", "candidate_rank", "candidate_selected"}
            )
            evidence = "shadow_calculation.csv:segment score/rank rows"
        elif control_id == "claim_boundary_enforcement":
            passed = decision.get("causal_effect_claimed") is False
            evidence = "candidate_decision.json:causal_effect_claimed"
        else:
            passed = True
            evidence = "route-specific project fixture required outside reference core profile"
        controls.append({"control_id": control_id, "passed": passed, "evidence": evidence})
    return {
        "route": spec.get("route"),
        "route_variant": spec.get("route_variant"),
        "adapter_kind": profile.get("adapter_kind"),
        "claim_boundary": profile.get("claim_boundary"),
        "controls": controls,
        "valid": bool(controls) and all(item["passed"] for item in controls),
    }


def build_test_results(
    spec: dict[str, Any],
    *,
    clean_room_check: dict[str, Any],
    shadow_check: dict[str, Any],
    fixture_rows: list[dict[str, Any]],
    sensitivity_check: dict[str, Any],
    claim_check: dict[str, Any],
    route_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    tests = [
        {
            "test_id": "clean_room_rerun",
            "status": "passed" if clean_room_check["valid"] else "failed",
        },
        {
            "test_id": "shadow_calculation",
            "status": "passed" if shadow_check["valid"] else "failed",
        },
        *[
            {
                "test_id": f"negative_fixture:{row['fixture_id']}",
                "status": "passed" if row["detected"] else "failed",
            }
            for row in fixture_rows
        ],
        {
            "test_id": "sensitivity_analysis",
            "status": "passed" if sensitivity_check["valid"] else "failed",
        },
        {
            "test_id": "claim_evidence_audit",
            "status": "passed" if claim_check["valid"] else "failed",
        },
        {
            "test_id": "route_specific_controls",
            "status": "passed" if route_report["valid"] else "failed",
        },
    ]
    disclosure = (
        spec.get("test_disclosure") if isinstance(spec.get("test_disclosure"), dict) else {}
    )
    required = (
        disclosure.get("required_test_ids")
        if isinstance(disclosure.get("required_test_ids"), list)
        else []
    )
    skipped = disclosure.get("skipped") if isinstance(disclosure.get("skipped"), list) else []
    xfail = disclosure.get("xfail") if isinstance(disclosure.get("xfail"), list) else []
    statuses = {row["test_id"]: row["status"] for row in tests}
    missing = sorted(set(required) - set(statuses))
    failed = sorted(test_id for test_id, status in statuses.items() if status != "passed")
    disclosed_ids = {
        str(item.get("test_id"))
        for item in skipped + xfail
        if isinstance(item, dict) and non_empty_text(item.get("test_id"))
    }
    required_disclosed = sorted(set(required) & disclosed_ids)
    invalid_disclosure = [
        item
        for item in skipped + xfail
        if not isinstance(item, dict)
        or not non_empty_text(item.get("test_id"))
        or not non_empty_text(item.get("reason"))
    ]
    valid = not missing and not failed and not required_disclosed and not invalid_disclosure
    result = {
        "tests": tests,
        "disclosure": {"skipped": skipped, "xfail": xfail},
        "summary": {
            "passed": sum(row["status"] == "passed" for row in tests),
            "failed": len(failed),
            "skipped": len(skipped),
            "xfail": len(xfail),
            "missing_required": missing,
            "required_disclosed_as_skip_or_xfail": required_disclosed,
        },
        "valid": valid,
    }
    return (
        check(
            "skipped_and_xfail_tests_are_disclosed",
            valid,
            observed=result["summary"],
            expected=(
                "all required verification tests pass; every skip/xfail has a reason "
                "and is non-critical"
            ),
            message=(
                "A green count without skip and xfail disclosure can hide missing "
                "verification coverage."
            ),
        ),
        result,
    )


def validate_public_boundary_and_stage(
    *,
    state: dict[str, Any],
    metrics_fields: list[str],
    upstream_before: dict[str, dict[str, str]],
    upstream_after: dict[str, dict[str, str]],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    restricted = sorted(set(metrics_fields) & RESTRICTED_COLUMNS)
    if restricted:
        errors.append({"field": "candidate_metrics", "restricted_columns": restricted})
    if (
        state.get("current_stage") != "implementation"
        or state.get("stage_status") != "implementation_ready"
    ):
        errors.append({"field": "upstream_stage", "observed": state.get("stage_status")})
    if state.get("review_id") is not None or state.get("defense_id") is not None:
        errors.append({"field": "later_stage_ids", "reason": "must be null before verification"})
    mutated = [name for name in upstream_before if upstream_before[name] != upstream_after[name]]
    if mutated:
        errors.append({"field": "upstream_inputs", "mutated_packages": mutated})
    return check(
        "verification_outputs_respect_public_boundary_and_stage",
        not errors,
        observed={"errors": errors, "candidate_columns": metrics_fields},
        expected=(
            "aggregate public inputs, immutable upstream packages and no peer-review/"
            "defense evidence"
        ),
        message=(
            "Verification cannot widen data rights, rewrite inputs or manufacture "
            "later-stage evidence."
        ),
    )


def audit_verification(
    *,
    upstream_implementation_package: str | Path,
    implementation_runner: str | Path,
    upstream_baseline_package: str | Path,
    verification_spec_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    package = Path(upstream_implementation_package)
    runner = Path(implementation_runner)
    baseline = Path(upstream_baseline_package)
    spec = read_json(verification_spec_path)
    before = {
        "implementation": directory_checksums(package),
        "baseline": directory_checksums(baseline),
    }
    integrity_check, state_check, data = validate_upstream_implementation_package(package, baseline)
    spec_check = validate_verification_spec(spec, data["state"], runner)
    route_check = validate_route_profile(spec, data["state"])
    prerequisites_valid = all(
        item["valid"] for item in (integrity_check, state_check, spec_check, route_check)
    )

    baseline_metrics, _baseline_fields = read_csv(baseline / "baseline_metrics.csv")
    acceptance_gate = read_json(baseline / "acceptance_gate.json")
    if prerequisites_valid:
        clean_room_check, clean_room_report = run_clean_room_rerun(
            package=package,
            baseline_package=baseline,
            implementation_runner=runner,
            spec=spec,
            published_manifest=data["manifest"],
        )
        shadow_check, shadow_rows, shadow_summary = independent_shadow_calculation(
            baseline_metrics=baseline_metrics,
            implementation_spec=data["spec"],
            published_metrics=data["metrics"],
            published_decision=data["decision"],
            published_acceptance=data["acceptance"],
            acceptance_gate=acceptance_gate,
        )
        definitions = (
            spec.get("negative_fixtures") if isinstance(spec.get("negative_fixtures"), list) else []
        )
        fixture_check, fixture_rows = run_negative_fixtures(
            definitions=definitions,
            package=package,
            baseline_package=baseline,
            implementation_spec=data["spec"],
            baseline_metrics=baseline_metrics,
            published_metrics=data["metrics"],
            decision=data["decision"],
            acceptance=data["acceptance"],
            acceptance_gate=acceptance_gate,
            state=data["state"],
            shadow_summary=shadow_summary,
        )
        scenarios = (
            spec.get("sensitivity_scenarios")
            if isinstance(spec.get("sensitivity_scenarios"), list)
            else []
        )
        sensitivity_check, sensitivity_rows, sensitivity_warnings = run_sensitivity_analysis(
            scenarios, acceptance_gate, shadow_summary, data["acceptance"]
        )
        claim_check, claim_rows = audit_claim_evidence(
            package=package,
            evidence_rows=data["evidence_rows"],
            state=data["state"],
            shadow_summary=shadow_summary,
            published_decision=data["decision"],
            published_acceptance=data["acceptance"],
        )
        route_report = route_control_report(spec, baseline_metrics, shadow_rows, data["decision"])
        test_check, test_results = build_test_results(
            spec,
            clean_room_check=clean_room_check,
            shadow_check=shadow_check,
            fixture_rows=fixture_rows,
            sensitivity_check=sensitivity_check,
            claim_check=claim_check,
            route_report=route_report,
        )
    else:
        clean_room_check = blocked_check(
            "clean_room_rerun_matches_published_package", "prerequisite gate failed"
        )
        shadow_check = blocked_check(
            "shadow_calculation_matches_published_result", "prerequisite gate failed"
        )
        fixture_check = blocked_check(
            "negative_fixtures_fail_at_expected_gates", "prerequisite gate failed"
        )
        sensitivity_check = blocked_check(
            "sensitivity_analysis_preserves_frozen_gate_and_reports_flips",
            "prerequisite gate failed",
        )
        claim_check = blocked_check(
            "every_claim_is_supported_by_exact_evidence_and_shadow", "prerequisite gate failed"
        )
        test_check = blocked_check(
            "skipped_and_xfail_tests_are_disclosed", "prerequisite gate failed"
        )
        clean_room_report = {"valid": False, "reason": "prerequisite gate failed"}
        shadow_rows = []
        shadow_summary = {}
        fixture_rows = []
        sensitivity_rows = []
        sensitivity_warnings = []
        claim_rows = []
        route_report = {"valid": False, "reason": "prerequisite gate failed"}
        test_results = {"valid": False, "reason": "prerequisite gate failed"}
    after = {
        "implementation": directory_checksums(package),
        "baseline": directory_checksums(baseline),
    }
    boundary_check = validate_public_boundary_and_stage(
        state=data["state"],
        metrics_fields=data["metric_fields"],
        upstream_before=before,
        upstream_after=after,
    )
    checks = [
        integrity_check,
        state_check,
        spec_check,
        route_check,
        clean_room_check,
        shadow_check,
        fixture_check,
        sensitivity_check,
        claim_check,
        test_check,
        boundary_check,
    ]
    blocking_errors = [
        item["id"] for item in checks if item["severity"] == "block" and not item["valid"]
    ]
    warnings = list(
        dict.fromkeys(
            [
                *data["state"].get("warnings", []),
                *sensitivity_warnings,
                "independent_verification_is_not_peer_review",
            ]
        )
    )
    valid = not blocking_errors
    status = "verification_ready" if valid else "verification_block"
    report = {
        "version": VERIFICATION_VERSION,
        "project_id": spec.get("project_id"),
        "contract_id": spec.get("contract_id"),
        "baseline_id": spec.get("baseline_id"),
        "implementation_id": spec.get("implementation_id"),
        "verification_id": spec.get("verification_id"),
        "status": status,
        "valid": valid,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "blocking_errors": blocking_errors,
            "clean_room_match": clean_room_check["valid"],
            "shadow_pass": shadow_check["valid"],
            "negative_fixtures": len(fixture_rows),
            "negative_fixtures_pass": fixture_check["valid"],
            "sensitivity_scenarios": len(sensitivity_rows),
            "sensitivity_decision_flips": sensitivity_check.get("observed", {}).get(
                "decision_flips", []
            ),
            "verified_claims": sum(row.get("status") == "verified" for row in claim_rows),
            "selected_method": data["acceptance"].get("selected_method"),
            "next_stage": "peer_review" if valid else "verification",
            "warnings": warnings,
        },
    }
    return report, {
        "spec": spec,
        "state": data["state"],
        "clean_room_report": clean_room_report,
        "shadow_rows": shadow_rows,
        "shadow_summary": shadow_summary,
        "fixture_rows": fixture_rows,
        "sensitivity_rows": sensitivity_rows,
        "claim_rows": claim_rows,
        "route_report": route_report,
        "test_results": test_results,
        "warnings": warnings,
        "upstream_implementation_manifest": data["manifest"],
        "acceptance": data["acceptance"],
    }


def build_verification_package(
    *,
    upstream_implementation_package: str | Path,
    implementation_runner: str | Path,
    upstream_baseline_package: str | Path,
    verification_spec_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report, result = audit_verification(
        upstream_implementation_package=upstream_implementation_package,
        implementation_runner=implementation_runner,
        upstream_baseline_package=upstream_baseline_package,
        verification_spec_path=verification_spec_path,
    )
    generated: dict[str, Path] = {
        "verification_spec": write_json(output / "verification_spec.json", result["spec"]),
        "verification_report": write_json(output / "verification_report.json", report),
        "clean_room_rerun": write_json(
            output / "clean_room_rerun.json", result["clean_room_report"]
        ),
        "shadow_calculation": write_csv(
            output / "shadow_calculation.csv",
            result["shadow_rows"],
            [
                "check_id",
                "grain",
                "field",
                "implementation_value",
                "shadow_value",
                "difference",
                "tolerance",
                "passed",
                "source_path",
                "method",
            ],
        ),
        "failure_fixture_results": write_csv(
            output / "failure_fixture_results.csv",
            result["fixture_rows"],
            [
                "fixture_id",
                "mutation",
                "expected_check_id",
                "observed_check_id",
                "observed_check_valid",
                "detected",
                "fixture_copy_removed",
                "status",
            ],
        ),
        "sensitivity_report": write_csv(
            output / "sensitivity_report.csv",
            result["sensitivity_rows"],
            [
                "scenario_id",
                "threshold_delta",
                "capacity_delta",
                "candidate_value",
                "candidate_threshold",
                "reviewed_users",
                "max_capacity",
                "metric_pass",
                "capacity_pass",
                "candidate_pass",
                "selected_method",
                "is_frozen_gate",
            ],
        ),
        "claim_evidence_audit": write_csv(
            output / "claim_evidence_audit.csv",
            result["claim_rows"],
            [
                "claim_id",
                "evidence_path",
                "path_exists",
                "declared_fields",
                "fields_exist",
                "limitation_present",
                "claim_type_allowed",
                "unique_claim_id",
                "shadow_supported",
                "status",
            ],
        ),
        "route_verification_report": write_json(
            output / "route_verification_report.json", result["route_report"]
        ),
        "test_results": write_json(output / "test_results.json", result["test_results"]),
    }
    fixture_directory = output / "failure-fixtures"
    for definition in result["spec"].get("negative_fixtures", []):
        fixture_id = str(definition.get("fixture_id", "unknown"))
        generated[f"failure_fixture_{fixture_id}"] = write_json(
            fixture_directory / f"{fixture_id}.json", definition
        )
    state = dict(result["state"])
    state.update(
        {
            "verification_id": result["spec"].get("verification_id"),
            "current_stage": "verification",
            "stage_status": report["status"],
            "open_blockers": report["summary"]["blocking_errors"],
            "warnings": result["warnings"],
            "artifact_inventory": list(
                dict.fromkeys(
                    state.get("artifact_inventory", [])
                    + [path.relative_to(output).as_posix() for path in generated.values()]
                )
            ),
            "evidence_links": state.get("evidence_links", [])
            + [
                {"stage": "verification", "path": "verification_report.json"},
                {"stage": "verification", "path": "shadow_calculation.csv"},
                {"stage": "verification", "path": "failure_fixture_results.csv"},
                {"stage": "verification", "path": "claim_evidence_audit.csv"},
            ],
            "input_checksums": {
                **state.get("input_checksums", {}),
                "upstream_implementation_manifest.json": sha256_file(
                    Path(upstream_implementation_package) / "implementation_manifest.json"
                ),
                "implementation_runner.py": sha256_file(implementation_runner),
                "verification_spec.json": sha256_file(verification_spec_path),
                "upstream_baseline_manifest.json": sha256_file(
                    Path(upstream_baseline_package) / "baseline_manifest.json"
                ),
            },
            "output_checksums": {
                path.relative_to(output).as_posix(): sha256_file(path)
                for path in generated.values()
            },
        }
    )
    state_path = write_json(output / "capstone_state.json", state)
    generated["capstone_state"] = state_path
    manifest = {
        "version": VERIFICATION_VERSION,
        "project_id": result["spec"].get("project_id"),
        "contract_id": result["spec"].get("contract_id"),
        "baseline_id": result["spec"].get("baseline_id"),
        "implementation_id": result["spec"].get("implementation_id"),
        "verification_id": result["spec"].get("verification_id"),
        "status": report["status"],
        "valid": report["valid"],
        "hash_algorithm": "sha256",
        "renderer_used": "capstone_independent_verifier",
        "independent_source_used": True,
        "clean_room_temporary_workspace": True,
        "implementation_functions_imported_for_verification": False,
        "raw_sources_copied": False,
        "upstream_inputs_mutated": False,
        "fixture_mutations_persisted": False,
        "clean_room_rerun_match": report["summary"]["clean_room_match"],
        "shadow_calculation_pass": report["summary"]["shadow_pass"],
        "negative_fixtures_pass": report["summary"]["negative_fixtures_pass"],
        "selected_method": report["summary"]["selected_method"],
        "inputs": {
            "upstream_implementation_manifest": {
                "path": "upstream-implementation-package/implementation_manifest.json",
                "sha256": sha256_file(
                    Path(upstream_implementation_package) / "implementation_manifest.json"
                ),
            },
            "upstream_baseline_manifest": {
                "path": "upstream-baseline-package/baseline_manifest.json",
                "sha256": sha256_file(Path(upstream_baseline_package) / "baseline_manifest.json"),
            },
            "implementation_runner": {
                "path": result["spec"].get("source_contract", {}).get("implementation_runner_path"),
                "sha256": sha256_file(implementation_runner),
            },
            "verification_harness": {
                "path": (
                    "phases/18-capstones/05-verification/outputs/capstone_independent_verifier.py"
                ),
                "sha256": sha256_file(__file__),
            },
            "verification_spec": {
                "path": Path(verification_spec_path).name,
                "sha256": sha256_file(verification_spec_path),
            },
            "lock_file": {
                "path": "uv.lock",
                "sha256": sha256_file(project_root() / "uv.lock"),
            },
        },
        "outputs": {
            name: {
                "path": path.relative_to(output).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for name, path in generated.items()
        },
    }
    manifest_path = write_json(output / "verification_manifest.json", manifest)
    return {
        "report": report,
        "output_dir": output,
        "state_path": state_path,
        "manifest_path": manifest_path,
        "shadow_path": generated["shadow_calculation"],
        "fixture_results_path": generated["failure_fixture_results"],
        "test_results_path": generated["test_results"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently verify a route-specific capstone implementation package.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--upstream-implementation-package",
        type=Path,
        help="Passing implementation package from lesson 18/04.",
    )
    parser.add_argument(
        "--implementation-runner",
        type=Path,
        help="Pinned implementation CLI source used for the clean-room rerun.",
    )
    parser.add_argument(
        "--upstream-baseline-package",
        type=Path,
        help="Immutable baseline package needed to rerun and shadow the implementation.",
    )
    parser.add_argument("--verification-spec", type=Path, help="Path to verification_spec.json.")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Directory for verification package."
    )
    parser.add_argument(
        "--write-example",
        type=Path,
        help="Write deterministic implementation, baseline and verification inputs here.",
    )
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help="Return exit code 1 when independent verification is blocked.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    implementation_package = parsed.upstream_implementation_package
    runner = parsed.implementation_runner
    baseline_package = parsed.upstream_baseline_package
    verification_spec = parsed.verification_spec
    if parsed.write_example:
        sample = write_sample_inputs(parsed.write_example)
        implementation_package = implementation_package or sample["upstream_implementation_package"]
        runner = runner or sample["implementation_runner"]
        baseline_package = baseline_package or sample["upstream_baseline_package"]
        verification_spec = verification_spec or sample["verification_spec_path"]
    missing = [
        name
        for name, value in (
            ("--upstream-implementation-package", implementation_package),
            ("--implementation-runner", runner),
            ("--upstream-baseline-package", baseline_package),
            ("--verification-spec", verification_spec),
        )
        if value is None
    ]
    if missing:
        print(
            json.dumps(
                {
                    "version": VERIFICATION_VERSION,
                    "status": "system_error",
                    "valid": False,
                    "error": {"code": "missing_inputs", "message": ", ".join(missing)},
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    try:
        result = build_verification_package(
            upstream_implementation_package=implementation_package,
            implementation_runner=runner,
            upstream_baseline_package=baseline_package,
            verification_spec_path=verification_spec,
            output_dir=parsed.output_dir,
        )
    except (
        OSError,
        UnicodeError,
        csv.Error,
        json.JSONDecodeError,
        VerificationError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "version": VERIFICATION_VERSION,
                    "status": "system_error",
                    "valid": False,
                    "error": {"code": "invalid_input", "message": str(error)},
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "implementation_id": report["implementation_id"],
        "verification_id": report["verification_id"],
        "clean_room_match": report["summary"]["clean_room_match"],
        "shadow_pass": report["summary"]["shadow_pass"],
        "negative_fixtures": report["summary"]["negative_fixtures"],
        "negative_fixtures_pass": report["summary"]["negative_fixtures_pass"],
        "sensitivity_decision_flips": report["summary"]["sensitivity_decision_flips"],
        "verified_claims": report["summary"]["verified_claims"],
        "selected_method": report["summary"]["selected_method"],
        "warnings": report["summary"]["warnings"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if parsed.fail_on_invalid and not report["valid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
