from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REVIEW_VERSION = "1.0.0"
REVIEWER_TYPES = {"learner_peer", "mentor", "independent_agent"}
SEVERITIES = {"blocker", "major", "minor", "question"}
RESPONSE_STATUSES = {"accepted", "partially_accepted", "declined_with_evidence"}
RUBRIC_DIMENSIONS = [
    ("problem_framing", "Problem framing"),
    ("data_contract", "Data contract"),
    ("method_and_baseline", "Method and baseline"),
    ("verification", "Verification"),
    ("delivery_and_handoff", "Delivery and handoff"),
    ("review_and_defense", "Review and defense"),
]
REPO_ROOT = Path(__file__).resolve().parents[4]
UPSTREAM_VERIFIER = (
    REPO_ROOT
    / "phases"
    / "18-capstones"
    / "05-verification"
    / "outputs"
    / "capstone_independent_verifier.py"
)


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def read_csv(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: str | Path, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: serialize_cell(row.get(field)) for field in fields})
    return target


def serialize_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def safe_relative_path(value: Any) -> bool:
    if not non_empty_text(value):
        return False
    path = Path(str(value).split("#", 1)[0])
    return not path.is_absolute() and ".." not in path.parts


def evidence_file(package: Path, selector: str) -> Path:
    return package / selector.split("#", 1)[0]


def check(
    check_id: str,
    valid: bool,
    *,
    observed: Any,
    expected: Any,
    message: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": bool(valid),
        "severity": "block",
        "observed": observed,
        "expected": expected,
        "message": message,
    }


def directory_checksums(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_dir():
        return {}
    return {
        item.relative_to(path).as_posix(): {
            "sha256": sha256_file(item),
            "bytes": item.stat().st_size,
        }
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def validate_manifest_outputs(package: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        return [{"field": "outputs", "reason": "non-empty object required"}]
    seen: set[str] = set()
    for output_id, item in outputs.items():
        if not isinstance(item, dict):
            errors.append({"field": f"outputs.{output_id}", "reason": "object required"})
            continue
        relative = item.get("path")
        if not safe_relative_path(relative):
            errors.append({"field": f"outputs.{output_id}.path", "observed": relative})
            continue
        relative = str(relative)
        if relative in seen:
            errors.append({"field": f"outputs.{output_id}.path", "reason": "duplicate"})
        seen.add(relative)
        target = package / relative
        if not target.is_file():
            errors.append({"field": f"outputs.{output_id}.path", "reason": "missing"})
            continue
        observed_hash = sha256_file(target)
        if observed_hash != item.get("sha256"):
            errors.append(
                {
                    "field": f"outputs.{output_id}.sha256",
                    "expected": item.get("sha256"),
                    "observed": observed_hash,
                }
            )
        if target.stat().st_size != item.get("bytes"):
            errors.append(
                {
                    "field": f"outputs.{output_id}.bytes",
                    "expected": item.get("bytes"),
                    "observed": target.stat().st_size,
                }
            )
    return errors


def validate_upstream_verification_package(
    package: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    required = [
        "verification_manifest.json",
        "verification_report.json",
        "capstone_state.json",
        "clean_room_rerun.json",
        "sensitivity_report.csv",
        "claim_evidence_audit.csv",
        "test_results.json",
    ]
    missing = [name for name in required if not (package / name).is_file()]
    if missing:
        return (
            check(
                "upstream_verification_package_is_immutable_and_ready",
                False,
                observed={"missing": missing, "errors": []},
                expected="verification_ready package with a complete SHA-256 manifest",
                message="Peer review must target the exact independently verified package.",
            ),
            {},
        )
    manifest = read_json(package / "verification_manifest.json")
    report = read_json(package / "verification_report.json")
    state = read_json(package / "capstone_state.json")
    errors = validate_manifest_outputs(package, manifest)
    expected_ids = {
        "project_id": state.get("project_id"),
        "verification_id": state.get("verification_id"),
    }
    for field, expected in expected_ids.items():
        for source_name, source in (("manifest", manifest), ("report", report)):
            if source.get(field) != expected:
                errors.append(
                    {
                        "field": f"{source_name}.{field}",
                        "expected": expected,
                        "observed": source.get(field),
                    }
                )
    if report.get("status") != "verification_ready" or report.get("valid") is not True:
        errors.append({"field": "verification_report.status", "observed": report.get("status")})
    if (
        state.get("current_stage") != "verification"
        or state.get("stage_status") != "verification_ready"
    ):
        errors.append(
            {"field": "capstone_state.stage_status", "observed": state.get("stage_status")}
        )
    if state.get("review_id") is not None or state.get("defense_id") is not None:
        errors.append({"field": "capstone_state.later_stage_ids", "reason": "must be null"})
    return (
        check(
            "upstream_verification_package_is_immutable_and_ready",
            not errors,
            observed={"errors": errors, "verified_outputs": len(manifest.get("outputs", {}))},
            expected="verification_ready package with matching IDs, sizes and SHA-256 hashes",
            message="Peer review must target the exact independently verified package.",
        ),
        {"manifest": manifest, "report": report, "state": state},
    )


def nested_forbidden_keys(value: Any, forbidden: set[str], prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in forbidden:
                found.append(path)
            found.extend(nested_forbidden_keys(child, forbidden, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(nested_forbidden_keys(child, forbidden, f"{prefix}[{index}]"))
    return found


def validate_review_spec(spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for field in ("project_id", "verification_id", "review_id"):
        if not non_empty_text(spec.get(field)):
            errors.append({"field": field, "reason": "non-empty text required"})
    for field, expected in (
        ("project_id", state.get("project_id")),
        ("verification_id", state.get("verification_id")),
    ):
        if spec.get(field) != expected:
            errors.append({"field": field, "expected": expected, "observed": spec.get(field)})
    if set(spec.get("allowed_reviewer_types", [])) != REVIEWER_TYPES:
        errors.append({"field": "allowed_reviewer_types", "expected": sorted(REVIEWER_TYPES)})
    if set(spec.get("allowed_severities", [])) != SEVERITIES:
        errors.append({"field": "allowed_severities", "expected": sorted(SEVERITIES)})
    if set(spec.get("allowed_response_statuses", [])) != RESPONSE_STATUSES:
        errors.append({"field": "allowed_response_statuses", "expected": sorted(RESPONSE_STATUSES)})
    self_review = spec.get("required_self_review_checks")
    if (
        not isinstance(self_review, list)
        or len(self_review) < 4
        or not all(non_empty_text(item) for item in self_review)
    ):
        errors.append(
            {"field": "required_self_review_checks", "reason": "four or more IDs required"}
        )
    reruns = spec.get("rerun_checks")
    if not isinstance(reruns, dict) or set(reruns) != {
        "sensitivity_analysis",
        "claim_evidence_audit",
        "clean_room_rerun_summary",
    }:
        errors.append({"field": "rerun_checks", "reason": "frozen check catalog required"})
    change_map = spec.get("change_check_map")
    if not isinstance(change_map, dict) or not change_map:
        errors.append({"field": "change_check_map", "reason": "non-empty mapping required"})
    elif any(
        not safe_relative_path(scope)
        or not isinstance(check_ids, list)
        or not check_ids
        or not set(check_ids).issubset(set(reruns or {}))
        for scope, check_ids in change_map.items()
    ):
        errors.append({"field": "change_check_map", "reason": "unknown path or check ID"})
    rubric = spec.get("rubric_dimensions")
    if rubric != [dimension_id for dimension_id, _name in RUBRIC_DIMENSIONS]:
        errors.append(
            {"field": "rubric_dimensions", "expected": [item[0] for item in RUBRIC_DIMENSIONS]}
        )
    forbidden = nested_forbidden_keys(
        spec,
        {"resolved", "final_status", "finding_count", "observed_result", "review_ready"},
    )
    if forbidden:
        errors.append({"field": "predeclared_spec", "forbidden_result_fields": forbidden})
    return check(
        "review_spec_is_predeclared_and_route_neutral",
        not errors,
        observed={"errors": errors, "review_id": spec.get("review_id")},
        expected="frozen reviewer, severity, response, rerun and rubric contracts without results",
        message="Review rules must be fixed before findings and responses are known.",
    )


def validate_self_review(submission: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    self_review = (
        submission.get("self_review") if isinstance(submission.get("self_review"), dict) else {}
    )
    reviewer = submission.get("reviewer") if isinstance(submission.get("reviewer"), dict) else {}
    rows = self_review.get("checks") if isinstance(self_review.get("checks"), list) else []
    observed_ids = [row.get("check_id") for row in rows if isinstance(row, dict)]
    required_ids = spec.get("required_self_review_checks", [])
    errors: list[dict[str, Any]] = []
    if len(observed_ids) != len(set(observed_ids)) or set(observed_ids) != set(required_ids):
        errors.append(
            {"field": "self_review.checks", "expected": required_ids, "observed": observed_ids}
        )
    incomplete = [row.get("check_id") for row in rows if row.get("completed") is not True]
    if incomplete:
        errors.append({"field": "self_review.checks", "incomplete": incomplete})
    completed_at = self_review.get("completed_at")
    review_started_at = reviewer.get("review_started_at")
    if (
        not non_empty_text(completed_at)
        or not non_empty_text(review_started_at)
        or completed_at >= review_started_at
    ):
        errors.append(
            {
                "field": "self_review.completed_at",
                "reason": "must precede reviewer.review_started_at",
            }
        )
    if not non_empty_text(self_review.get("author_id")):
        errors.append({"field": "self_review.author_id", "reason": "required"})
    return check(
        "author_self_review_precedes_independent_review",
        not errors,
        observed={"errors": errors, "completed_checks": len(rows)},
        expected="all predeclared self-review checks completed before independent review",
        message="Peer review starts after, not instead of, the author's own review.",
    )


def validate_reviewer_independence(
    submission: dict[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    reviewer = submission.get("reviewer") if isinstance(submission.get("reviewer"), dict) else {}
    self_review = (
        submission.get("self_review") if isinstance(submission.get("self_review"), dict) else {}
    )
    errors: list[dict[str, Any]] = []
    reviewer_type = reviewer.get("reviewer_type")
    if reviewer_type not in REVIEWER_TYPES:
        errors.append({"field": "reviewer.reviewer_type", "observed": reviewer_type})
    if not non_empty_text(reviewer.get("reviewer_id")):
        errors.append({"field": "reviewer.reviewer_id", "reason": "required"})
    if (
        reviewer.get("reviewer_id") == self_review.get("author_id")
        or reviewer.get("is_project_author") is not False
    ):
        errors.append({"field": "reviewer.independence", "reason": "reviewer cannot be author"})
    if reviewer.get("conflict_of_interest") is not False:
        errors.append({"field": "reviewer.conflict_of_interest", "reason": "must be false"})
    if reviewer.get("reviewed_manifest_sha256") != manifest_sha256:
        errors.append(
            {
                "field": "reviewer.reviewed_manifest_sha256",
                "expected": manifest_sha256,
                "observed": reviewer.get("reviewed_manifest_sha256"),
            }
        )
    if reviewer_type == "independent_agent":
        if reviewer.get("clean_review_context") is not True:
            errors.append(
                {"field": "reviewer.clean_review_context", "reason": "required for agent"}
            )
        if not non_empty_text(reviewer.get("assistance_disclosure")):
            errors.append(
                {"field": "reviewer.assistance_disclosure", "reason": "required for agent"}
            )
    return check(
        "reviewer_independence_is_disclosed",
        not errors,
        observed={"errors": errors, "reviewer_type": reviewer_type},
        expected="independent reviewer identity, conflict disclosure and exact reviewed manifest",
        message="An undisclosed self-review cannot count as independent peer review.",
    )


def index_claims(claims: Any) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    result: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    if not isinstance(claims, list):
        return {}, [{"field": "claims", "reason": "list required"}]
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict) or not non_empty_text(claim.get("claim_id")):
            errors.append({"field": f"claims[{index}]", "reason": "claim_id required"})
            continue
        claim_id = str(claim["claim_id"])
        if claim_id in result:
            errors.append({"field": f"claims[{index}].claim_id", "reason": "duplicate"})
        result[claim_id] = claim
    return result, errors


def validate_findings(
    submission: dict[str, Any], package: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reviewer = submission.get("reviewer") if isinstance(submission.get("reviewer"), dict) else {}
    findings = submission.get("findings") if isinstance(submission.get("findings"), list) else []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, finding in enumerate(findings):
        prefix = f"findings[{index}]"
        if not isinstance(finding, dict):
            errors.append({"field": prefix, "reason": "object required"})
            continue
        finding_id = finding.get("finding_id")
        if not non_empty_text(finding_id) or finding_id in seen:
            errors.append({"field": f"{prefix}.finding_id", "reason": "unique ID required"})
        seen.add(str(finding_id))
        if finding.get("severity") not in SEVERITIES:
            errors.append({"field": f"{prefix}.severity", "observed": finding.get("severity")})
        for field in ("title", "evidence_path", "expected_behavior", "verification_method"):
            if not non_empty_text(finding.get(field)):
                errors.append({"field": f"{prefix}.{field}", "reason": "required"})
        evidence_path = finding.get("evidence_path")
        if (
            not safe_relative_path(evidence_path)
            or not evidence_file(package, str(evidence_path)).is_file()
        ):
            errors.append(
                {"field": f"{prefix}.evidence_path", "reason": "exact existing evidence required"}
            )
        if "#" not in str(evidence_path):
            errors.append(
                {"field": f"{prefix}.evidence_path", "reason": "field or row selector required"}
            )
        if finding.get("raised_by_reviewer_id") != reviewer.get("reviewer_id"):
            errors.append(
                {"field": f"{prefix}.raised_by_reviewer_id", "reason": "must match reviewer"}
            )
        forbidden = sorted(set(finding) & {"resolved", "status", "closed"})
        if forbidden:
            errors.append({"field": prefix, "forbidden_resolution_fields": forbidden})
    if not findings:
        errors.append(
            {"field": "findings", "reason": "reference review needs evidence-based findings"}
        )
    return (
        check(
            "findings_have_severity_and_exact_evidence",
            not errors,
            observed={"errors": errors, "finding_count": len(findings)},
            expected=(
                "unique findings with allowed severity, exact evidence and verification method"
            ),
            message="A review comment is actionable only when another person can verify it.",
        ),
        findings,
    )


def validate_author_responses(
    submission: dict[str, Any], findings: list[dict[str, Any]], package: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    responses = (
        submission.get("author_responses")
        if isinstance(submission.get("author_responses"), list)
        else []
    )
    finding_ids = {item.get("finding_id") for item in findings}
    response_by_finding: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, Any]] = []
    reviewed, claim_errors = index_claims(submission.get("reviewed_claims"))
    errors.extend(
        {"field": f"reviewed_{item['field']}", **{k: v for k, v in item.items() if k != "field"}}
        for item in claim_errors
    )
    for index, response in enumerate(responses):
        prefix = f"author_responses[{index}]"
        if not isinstance(response, dict):
            errors.append({"field": prefix, "reason": "object required"})
            continue
        finding_id = response.get("finding_id")
        response_by_finding.setdefault(str(finding_id), []).append(response)
        if finding_id not in finding_ids:
            errors.append({"field": f"{prefix}.finding_id", "reason": "unknown finding"})
        if response.get("response_status") not in RESPONSE_STATUSES:
            errors.append(
                {"field": f"{prefix}.response_status", "observed": response.get("response_status")}
            )
        if not non_empty_text(response.get("rationale")):
            errors.append({"field": f"{prefix}.rationale", "reason": "required"})
        if sorted(set(response) & {"resolved", "closed", "review_status"}):
            errors.append({"field": prefix, "reason": "resolution is derived, not author-declared"})
        status = response.get("response_status")
        scopes = (
            response.get("changed_scopes")
            if isinstance(response.get("changed_scopes"), list)
            else []
        )
        reruns = (
            response.get("rerun_check_ids")
            if isinstance(response.get("rerun_check_ids"), list)
            else []
        )
        if status in {"accepted", "partially_accepted"} and (not scopes or not reruns):
            errors.append({"field": prefix, "reason": "accepted changes require scopes and reruns"})
        if status == "declined_with_evidence":
            evidence_paths = response.get("response_evidence_paths")
            if not isinstance(evidence_paths, list) or not evidence_paths:
                errors.append({"field": f"{prefix}.response_evidence_paths", "reason": "required"})
            elif any(
                not safe_relative_path(path) or not evidence_file(package, str(path)).is_file()
                for path in evidence_paths
            ):
                errors.append(
                    {"field": f"{prefix}.response_evidence_paths", "reason": "missing evidence"}
                )
        for scope in scopes:
            claim_id = str(scope).split("claim_id=", 1)[1] if "claim_id=" in str(scope) else ""
            if claim_id not in reviewed:
                errors.append({"field": f"{prefix}.changed_scopes", "unknown_claim": claim_id})
            elif response.get("reviewed_claim_sha256") != canonical_sha256(reviewed[claim_id]):
                errors.append(
                    {
                        "field": f"{prefix}.reviewed_claim_sha256",
                        "claim_id": claim_id,
                        "expected": canonical_sha256(reviewed[claim_id]),
                        "observed": response.get("reviewed_claim_sha256"),
                    }
                )
    for finding_id in finding_ids:
        if len(response_by_finding.get(str(finding_id), [])) != 1:
            errors.append(
                {
                    "field": "author_responses.finding_id",
                    "finding_id": finding_id,
                    "expected": "exactly one response",
                }
            )
    return (
        check(
            "author_responses_use_evidence_statuses",
            not errors,
            observed={"errors": errors, "response_count": len(responses)},
            expected="one typed response per finding; no author-declared resolution",
            message="A response records agreement and evidence, while re-review decides closure.",
        ),
        responses,
    )


def build_changed_inventory(
    submission: dict[str, Any], spec: dict[str, Any]
) -> list[dict[str, Any]]:
    proposed, _errors = index_claims(submission.get("proposed_claims"))
    reviewed, _errors = index_claims(submission.get("reviewed_claims"))
    expected_hash_by_scope: dict[str, str] = {}
    finding_by_scope: dict[str, str] = {}
    for response in submission.get("author_responses", []):
        if not isinstance(response, dict):
            continue
        for scope in response.get("changed_scopes", []):
            expected_hash_by_scope[str(scope)] = str(response.get("reviewed_claim_sha256", ""))
            finding_by_scope[str(scope)] = str(response.get("finding_id", ""))
    rows: list[dict[str, Any]] = []
    for scope in sorted(expected_hash_by_scope):
        claim_id = scope.split("claim_id=", 1)[1] if "claim_id=" in scope else ""
        before = proposed.get(claim_id)
        after = reviewed.get(claim_id)
        before_hash = canonical_sha256(before) if before is not None else ""
        after_hash = canonical_sha256(after) if after is not None else ""
        rows.append(
            {
                "finding_id": finding_by_scope[scope],
                "change_scope": scope,
                "change_kind": "added"
                if before is None
                else "modified"
                if before_hash != after_hash
                else "unchanged",
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "expected_after_sha256": expected_hash_by_scope[scope],
                "checksum_match": bool(after_hash) and after_hash == expected_hash_by_scope[scope],
                "required_rerun_check_ids": spec.get("change_check_map", {}).get(scope, []),
            }
        )
    return rows


def source_hashes(package: Path, selectors: list[str]) -> list[dict[str, str]]:
    return [
        {"path": selector, "sha256": sha256_file(evidence_file(package, selector))}
        for selector in selectors
        if evidence_file(package, selector).is_file()
    ]


def run_rerun_checks(package: Path, submission: dict[str, Any]) -> list[dict[str, Any]]:
    claims, _errors = index_claims(submission.get("reviewed_claims"))
    sensitivity_rows, _fields = read_csv(package / "sensitivity_report.csv")
    frozen = next((row for row in sensitivity_rows if as_bool(row.get("is_frozen_gate"))), {})
    flips = sorted(
        row.get("scenario_id", "")
        for row in sensitivity_rows
        if not as_bool(row.get("is_frozen_gate"))
        and row.get("selected_method") != frozen.get("selected_method")
    )
    sensitivity_claim = claims.get("claim-sensitivity", {})
    baseline_claim = claims.get("claim-baseline", {})
    sensitivity_assertion = sensitivity_claim.get("assertion", {})
    baseline_assertion = baseline_claim.get("assertion", {})
    sensitivity_pass = (
        frozen.get("selected_method") == "baseline"
        and bool(flips)
        and sensitivity_assertion.get("robust_across_scenarios") is False
        and sorted(sensitivity_assertion.get("decision_flip_scenarios", [])) == flips
        and baseline_assertion.get("selected_method") == "baseline"
        and baseline_assertion.get("frozen_gate_preserved") is True
    )
    clean_room = read_json(package / "clean_room_rerun.json")
    clean_claim = claims.get("claim-clean-room", {})
    clean_assertion = clean_claim.get("assertion", {})
    clean_pass = (
        clean_room.get("valid") is True
        and clean_room.get("network_access_declared") is False
        and clean_assertion.get("network_access_declared") is False
        and clean_assertion.get("technical_network_block_proven") is False
    )
    claim_rows, _fields = read_csv(package / "claim_evidence_audit.csv")
    exact_evidence = all(
        non_empty_text(claim.get("evidence_path"))
        and safe_relative_path(claim.get("evidence_path"))
        and evidence_file(package, str(claim.get("evidence_path"))).is_file()
        and non_empty_text(claim.get("limitation"))
        for claim in claims.values()
    )
    claim_pass = (
        bool(claims)
        and exact_evidence
        and all(row.get("status") == "verified" for row in claim_rows)
    )
    return [
        {
            "check_id": "sensitivity_analysis",
            "passed": sensitivity_pass,
            "source_hashes": source_hashes(package, ["sensitivity_report.csv"]),
            "observed": {
                "frozen_selection": frozen.get("selected_method"),
                "decision_flip_scenarios": flips,
                "reviewed_claims": ["claim-sensitivity", "claim-baseline"],
            },
        },
        {
            "check_id": "claim_evidence_audit",
            "passed": claim_pass,
            "source_hashes": source_hashes(package, ["claim_evidence_audit.csv"]),
            "observed": {
                "upstream_verified_claims": sum(
                    row.get("status") == "verified" for row in claim_rows
                ),
                "reviewed_claims": len(claims),
                "exact_evidence": exact_evidence,
            },
        },
        {
            "check_id": "clean_room_rerun_summary",
            "passed": clean_pass,
            "source_hashes": source_hashes(package, ["clean_room_rerun.json"]),
            "observed": {
                "rerun_valid": clean_room.get("valid"),
                "network_access_declared": clean_room.get("network_access_declared"),
                "technical_network_block_proven": clean_assertion.get(
                    "technical_network_block_proven"
                ),
            },
        },
    ]


def build_re_review(
    findings: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    reruns: list[dict[str, Any]],
    spec: dict[str, Any],
    submission: dict[str, Any],
    response_contract_valid: bool,
    package: Path,
) -> dict[str, Any]:
    response_map = {
        str(item.get("finding_id")): item for item in responses if isinstance(item, dict)
    }
    inventory_map = {str(item["change_scope"]): item for item in inventory}
    rerun_map = {str(item["check_id"]): item for item in reruns}
    rows: list[dict[str, Any]] = []
    for finding in findings:
        finding_id = str(finding.get("finding_id"))
        severity = str(finding.get("severity"))
        response = response_map.get(finding_id)
        status = response.get("response_status") if response else "missing"
        scopes = response.get("changed_scopes", []) if response else []
        required_reruns = sorted(
            {
                check_id
                for scope in scopes
                for check_id in spec.get("change_check_map", {}).get(scope, [])
            }
        )
        declared_reruns = sorted(response.get("rerun_check_ids", [])) if response else []
        changes_valid = bool(scopes) and all(
            inventory_map.get(str(scope), {}).get("change_kind") in {"added", "modified"}
            and inventory_map.get(str(scope), {}).get("checksum_match") is True
            for scope in scopes
        )
        reruns_pass = (
            bool(required_reruns)
            and set(required_reruns).issubset(set(declared_reruns))
            and all(
                rerun_map.get(check_id, {}).get("passed") is True for check_id in required_reruns
            )
        )
        waiver = response.get("waiver", {}) if response else {}
        waiver_evidence = waiver.get("evidence_path") if isinstance(waiver, dict) else None
        waiver_valid = (
            isinstance(waiver, dict)
            and waiver.get("accepted_by_decision_owner") is True
            and non_empty_text(waiver.get("owner_role"))
            and safe_relative_path(waiver_evidence)
            and evidence_file(package, str(waiver_evidence)).is_file()
        )
        if status == "accepted":
            closed = changes_valid and reruns_pass and response_contract_valid
            closure_status = (
                "closed_after_change_and_rerun" if closed else "open_missing_change_or_rerun"
            )
        elif status == "partially_accepted":
            closed = changes_valid and reruns_pass and severity in {"minor", "question"}
            closure_status = "closed_with_documented_limit" if closed else "open_partially_accepted"
        elif status == "declined_with_evidence":
            evidence_paths = response.get("response_evidence_paths", []) if response else []
            evidence_valid = bool(evidence_paths)
            closed = evidence_valid and (severity in {"minor", "question"} or waiver_valid)
            closure_status = "closed_with_waiver_evidence" if closed else "open_declined"
        else:
            closed = False
            closure_status = "open_missing_response"
        rows.append(
            {
                "finding_id": finding_id,
                "severity": severity,
                "response_status": status,
                "changed_scopes": scopes,
                "required_rerun_check_ids": required_reruns,
                "declared_rerun_check_ids": declared_reruns,
                "changes_valid": changes_valid,
                "reruns_pass": reruns_pass,
                "waiver_valid": waiver_valid,
                "closure_status": closure_status,
                "closed": closed,
            }
        )
    open_findings = [row["finding_id"] for row in rows if not row["closed"]]
    open_critical = [
        row["finding_id"]
        for row in rows
        if not row["closed"] and row["severity"] in {"blocker", "major"}
    ]
    reviewer = submission.get("reviewer", {})
    return {
        "version": REVIEW_VERSION,
        "review_id": spec.get("review_id"),
        "reviewed_verification_id": spec.get("verification_id"),
        "reviewer_id": reviewer.get("reviewer_id"),
        "reviewer_type": reviewer.get("reviewer_type"),
        "reviewed_manifest_sha256": reviewer.get("reviewed_manifest_sha256"),
        "re_reviewed_at": submission.get("re_reviewed_at"),
        "findings": rows,
        "summary": {
            "finding_count": len(rows),
            "closed_findings": sum(row["closed"] for row in rows),
            "open_findings": open_findings,
            "open_blocker_or_major": open_critical,
            "status": "approved_for_defense" if not open_findings and rows else "changes_requested",
        },
        "valid": bool(rows) and not open_findings,
    }


def build_rubric(
    upstream: dict[str, Any], re_review: dict[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    state = upstream.get("state", {})
    report = upstream.get("report", {})
    summary = report.get("summary", {})
    review_closed = re_review.get("valid") is True
    dimension_values = [
        (
            "problem_framing",
            3 if state.get("decision") and state.get("scope") and state.get("non_goals") else 0,
            ["capstone_state.json#decision", "capstone_state.json#scope"],
            "Decision, scope and non-goals are traceable through the verified stage package.",
        ),
        (
            "data_contract",
            3 if state.get("data_contract_id") and state.get("input_checksums") else 0,
            ["capstone_state.json#data_contract_id", "capstone_state.json#input_checksums"],
            "The review boundary preserves the approved data contract and input checksums.",
        ),
        (
            "method_and_baseline",
            3 if summary.get("selected_method") == "baseline" else 0,
            [
                "verification_report.json#summary.selected_method",
                "sensitivity_report.csv#frozen_gate",
            ],
            "The frozen baseline decision and threshold sensitivity are both explicit.",
        ),
        (
            "verification",
            4
            if report.get("valid") is True
            and summary.get("shadow_pass") is True
            and summary.get("negative_fixtures_pass") is True
            else 0,
            ["verification_report.json#summary", "claim_evidence_audit.csv#status"],
            "Clean-room, shadow, negative, sensitivity and claim checks passed independently.",
        ),
        (
            "delivery_and_handoff",
            3 if manifest_sha256 and state.get("artifact_inventory") else 0,
            ["verification_manifest.json#outputs", "capstone_state.json#artifact_inventory"],
            "The reviewed boundary is reproducible, but final consumer handoff belongs to defense.",
        ),
        (
            "review_and_defense",
            3 if review_closed else 0,
            ["re_review_report.json#summary", "author_responses.csv#finding_id"],
            "Review findings are closed with rerun evidence; live defense is still pending.",
        ),
    ]
    names = dict(RUBRIC_DIMENSIONS)
    dimensions = [
        {
            "dimension_id": dimension_id,
            "name": names[dimension_id],
            "score": score,
            "max_score": 4,
            "evidence_paths": evidence,
            "rationale": rationale,
        }
        for dimension_id, score, evidence, rationale in dimension_values
    ]
    total = sum(item["score"] for item in dimensions)
    return {
        "version": REVIEW_VERSION,
        "status": "provisional_review_score",
        "dimensions": dimensions,
        "summary": {
            "total_score": total,
            "max_score": 24,
            "all_dimensions_scored": len(dimensions) == 6,
            "provisional_only": True,
            "final_defense_not_scored": True,
        },
    }


def flatten_findings(
    findings: list[dict[str, Any]], re_review: dict[str, Any]
) -> list[dict[str, Any]]:
    closure = {row["finding_id"]: row for row in re_review.get("findings", [])}
    return [
        {
            "finding_id": finding.get("finding_id"),
            "severity": finding.get("severity"),
            "title": finding.get("title"),
            "claim_id": finding.get("claim_id"),
            "evidence_path": finding.get("evidence_path"),
            "expected_behavior": finding.get("expected_behavior"),
            "verification_method": finding.get("verification_method"),
            "raised_by_reviewer_id": finding.get("raised_by_reviewer_id"),
            "closure_status": closure.get(finding.get("finding_id"), {}).get("closure_status"),
        }
        for finding in findings
    ]


def flatten_responses(responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "response_id": response.get("response_id"),
            "finding_id": response.get("finding_id"),
            "response_status": response.get("response_status"),
            "rationale": response.get("rationale"),
            "changed_scopes": response.get("changed_scopes", []),
            "rerun_check_ids": response.get("rerun_check_ids", []),
            "response_evidence_paths": response.get("response_evidence_paths", []),
            "reviewed_claim_sha256": response.get("reviewed_claim_sha256"),
        }
        for response in responses
    ]


def audit_peer_review(
    *,
    upstream_verification_package: str | Path,
    review_spec_path: str | Path,
    review_submission_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    package = Path(upstream_verification_package)
    spec = read_json(review_spec_path)
    submission = read_json(review_submission_path)
    before = directory_checksums(package)
    upstream_check, upstream = validate_upstream_verification_package(package)
    state = upstream.get("state", {})
    manifest_sha = (
        sha256_file(package / "verification_manifest.json")
        if (package / "verification_manifest.json").is_file()
        else ""
    )
    spec_check = validate_review_spec(spec, state)
    ids_errors = []
    for field in ("project_id", "verification_id", "review_id"):
        if submission.get(field) != spec.get(field):
            ids_errors.append(
                {"field": field, "expected": spec.get(field), "observed": submission.get(field)}
            )
    id_check = check(
        "review_submission_matches_predeclared_scope",
        not ids_errors,
        observed={"errors": ids_errors},
        expected="submission IDs match the frozen project, verification and review IDs",
        message="Review findings and responses cannot be moved between package versions.",
    )
    self_review_check = validate_self_review(submission, spec)
    reviewer_check = validate_reviewer_independence(submission, manifest_sha)
    finding_check, findings = validate_findings(submission, package)
    response_check, responses = validate_author_responses(submission, findings, package)
    inventory = build_changed_inventory(submission, spec)
    rerun_sources = (
        "sensitivity_report.csv",
        "claim_evidence_audit.csv",
        "clean_room_rerun.json",
    )
    missing_rerun_sources = [name for name in rerun_sources if not (package / name).is_file()]
    if missing_rerun_sources:
        reruns = [
            {
                "check_id": check_id,
                "passed": False,
                "source_hashes": [],
                "observed": {
                    "reason": "upstream verification evidence is unavailable",
                    "missing_sources": missing_rerun_sources,
                },
            }
            for check_id in (
                "sensitivity_analysis",
                "claim_evidence_audit",
                "clean_room_rerun_summary",
            )
        ]
    else:
        reruns = run_rerun_checks(package, submission)
    changed_errors = [
        {
            "change_scope": row["change_scope"],
            "change_kind": row["change_kind"],
            "checksum_match": row["checksum_match"],
        }
        for row in inventory
        if row["change_kind"] not in {"added", "modified"} or not row["checksum_match"]
    ]
    changed_check = check(
        "changed_claims_have_before_and_after_checksums",
        bool(inventory) and not changed_errors,
        observed={"errors": changed_errors, "changed_scopes": len(inventory)},
        expected="every accepted change has a distinct, matching after checksum",
        message="A response without a verifiable changed artifact is not an implemented fix.",
    )
    re_review = build_re_review(
        findings,
        responses,
        inventory,
        reruns,
        spec,
        submission,
        response_check["valid"],
        package,
    )
    rerun_errors = [item["check_id"] for item in reruns if item.get("passed") is not True]
    rerun_check = check(
        "changed_scopes_rerun_all_affected_checks",
        not rerun_errors and all(row.get("reruns_pass") for row in re_review["findings"]),
        observed={"failed_checks": rerun_errors, "finding_reruns": re_review["findings"]},
        expected="all checks mapped to changed scopes are declared, rerun and passing",
        message="An accepted fix stays open until the affected evidence is rerun.",
    )
    re_review_check = check(
        "independent_re_review_closes_every_finding",
        re_review["valid"],
        observed=re_review["summary"],
        expected="all findings independently closed; no open blocker or major",
        message="The author proposes a fix; the reviewer decides whether evidence closes it.",
    )
    after = directory_checksums(package)
    boundary_errors: list[dict[str, Any]] = []
    if before != after:
        boundary_errors.append(
            {"field": "upstream_verification_package", "reason": "mutated during review"}
        )
    if state.get("defense_id") is not None:
        boundary_errors.append(
            {"field": "capstone_state.defense_id", "reason": "must be null before defense"}
        )
    boundary_check = check(
        "review_respects_immutable_boundary_and_stage",
        not boundary_errors,
        observed={"errors": boundary_errors, "upstream_files": len(before)},
        expected="unchanged verification package and no manufactured defense evidence",
        message=(
            "Review adds a new layer; it does not rewrite verified history or complete defense."
        ),
    )
    rubric = build_rubric(upstream, re_review, manifest_sha)
    rubric_errors = [
        item["dimension_id"]
        for item in rubric["dimensions"]
        if item["score"] not in range(5) or not item["evidence_paths"]
    ]
    rubric_check = check(
        "review_rubric_scores_six_dimensions_with_evidence",
        len(rubric["dimensions"]) == 6 and not rubric_errors,
        observed={"errors": rubric_errors, "provisional_total": rubric["summary"]["total_score"]},
        expected="six evidence-linked scores from 0 to 4, explicitly provisional before defense",
        message="Rubric evidence supports review discussion but cannot replace critical gates.",
    )
    checks = [
        upstream_check,
        spec_check,
        id_check,
        self_review_check,
        reviewer_check,
        finding_check,
        response_check,
        changed_check,
        rerun_check,
        re_review_check,
        boundary_check,
        rubric_check,
    ]
    blocking_errors = [item["id"] for item in checks if not item["valid"]]
    valid = not blocking_errors
    status = "review_ready" if valid else "review_block"
    severity_counts = {
        severity: sum(item.get("severity") == severity for item in findings)
        for severity in sorted(SEVERITIES)
    }
    report = {
        "version": REVIEW_VERSION,
        "project_id": spec.get("project_id"),
        "verification_id": spec.get("verification_id"),
        "review_id": spec.get("review_id"),
        "status": status,
        "valid": valid,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "blocking_errors": blocking_errors,
            "reviewer_type": submission.get("reviewer", {}).get("reviewer_type"),
            "finding_count": len(findings),
            "severity_counts": severity_counts,
            "response_count": len(responses),
            "changed_scopes": len(inventory),
            "rerun_checks": len(reruns),
            "closed_findings": re_review["summary"]["closed_findings"],
            "open_findings": re_review["summary"]["open_findings"],
            "provisional_rubric_score": rubric["summary"]["total_score"],
            "next_stage": "defense" if valid else "peer_review",
            "warnings": [
                "reference_profile_is_not_portfolio_evidence",
                "provisional_rubric_is_not_final_defense_result",
                "review_ready_is_not_defense_ready",
            ],
        },
    }
    return report, {
        "spec": spec,
        "submission": submission,
        "upstream": upstream,
        "findings": flatten_findings(findings, re_review),
        "responses": flatten_responses(responses),
        "inventory": inventory,
        "reruns": reruns,
        "re_review": re_review,
        "rubric": rubric,
        "manifest_sha256": manifest_sha,
    }


def output_record(path: Path) -> dict[str, Any]:
    return {"path": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def build_review_state(
    upstream_state: dict[str, Any],
    report: dict[str, Any],
    generated: dict[str, Path],
    spec_path: Path,
    submission_path: Path,
    manifest_sha256: str,
) -> dict[str, Any]:
    state = json.loads(json.dumps(upstream_state))
    review_files = [path.name for path in generated.values()]
    state["current_stage"] = "review"
    state["stage_status"] = report["status"]
    state["review_id"] = report.get("review_id") if report["valid"] else None
    state["defense_id"] = None
    state["updated_at"] = "2026-01-13T00:00:00Z"
    state["artifact_inventory"] = list(
        dict.fromkeys([*state.get("artifact_inventory", []), *review_files])
    )
    state["evidence_links"] = [
        *state.get("evidence_links", []),
        {"stage": "review", "path": "review_report.json"},
        {"stage": "review", "path": "finding_ledger.csv"},
        {"stage": "review", "path": "author_responses.csv"},
        {"stage": "review", "path": "re_review_report.json"},
    ]
    state["input_checksums"] = {
        **state.get("input_checksums", {}),
        "upstream_verification_manifest.json": manifest_sha256,
        "review_spec.json": sha256_file(spec_path),
        "review_submission.json": sha256_file(submission_path),
    }
    state["output_checksums"] = {path.name: sha256_file(path) for path in generated.values()}
    state["open_blockers"] = report["summary"]["blocking_errors"]
    state["warnings"] = report["summary"]["warnings"]
    return state


def build_review_package(
    *,
    upstream_verification_package: str | Path,
    review_spec_path: str | Path,
    review_submission_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report, result = audit_peer_review(
        upstream_verification_package=upstream_verification_package,
        review_spec_path=review_spec_path,
        review_submission_path=review_submission_path,
    )
    submission = result["submission"]
    generated: dict[str, Path] = {
        "review_spec": write_json(output / "review_spec.json", result["spec"]),
        "review_report": write_json(output / "review_report.json", report),
        "review_rubric": write_json(output / "review_rubric.json", result["rubric"]),
        "finding_ledger": write_csv(
            output / "finding_ledger.csv",
            result["findings"],
            [
                "finding_id",
                "severity",
                "title",
                "claim_id",
                "evidence_path",
                "expected_behavior",
                "verification_method",
                "raised_by_reviewer_id",
                "closure_status",
            ],
        ),
        "author_responses": write_csv(
            output / "author_responses.csv",
            result["responses"],
            [
                "response_id",
                "finding_id",
                "response_status",
                "rationale",
                "changed_scopes",
                "rerun_check_ids",
                "response_evidence_paths",
                "reviewed_claim_sha256",
            ],
        ),
        "reviewed_claims": write_json(
            output / "reviewed_claims.json",
            {"claims": submission.get("reviewed_claims", [])},
        ),
        "changed_file_inventory": write_csv(
            output / "changed_file_inventory.csv",
            result["inventory"],
            [
                "finding_id",
                "change_scope",
                "change_kind",
                "before_sha256",
                "after_sha256",
                "expected_after_sha256",
                "checksum_match",
                "required_rerun_check_ids",
            ],
        ),
        "rerun_results": write_json(
            output / "rerun_results.json",
            {"checks": result["reruns"], "valid": all(item["passed"] for item in result["reruns"])},
        ),
        "re_review_report": write_json(output / "re_review_report.json", result["re_review"]),
    }
    state = build_review_state(
        result["upstream"].get("state", {}),
        report,
        generated,
        Path(review_spec_path),
        Path(review_submission_path),
        result["manifest_sha256"],
    )
    state_path = write_json(output / "capstone_state.json", state)
    generated["capstone_state"] = state_path
    manifest = {
        "version": REVIEW_VERSION,
        "project_id": report.get("project_id"),
        "verification_id": report.get("verification_id"),
        "review_id": report.get("review_id"),
        "status": report["status"],
        "valid": report["valid"],
        "hash_algorithm": "sha256",
        "reviewer_type": report["summary"]["reviewer_type"],
        "reviewer_independence_disclosed": next(
            item["valid"]
            for item in report["checks"]
            if item["id"] == "reviewer_independence_is_disclosed"
        ),
        "upstream_inputs_mutated": False,
        "author_declared_resolution_allowed": False,
        "re_review_pass": result["re_review"]["valid"],
        "final_defense_result_claimed": False,
        "inputs": {
            "upstream_verification_manifest": {
                "path": "upstream-verification-package/verification_manifest.json",
                "sha256": result["manifest_sha256"],
            },
            "review_spec": {"path": "review_spec.json", "sha256": sha256_file(review_spec_path)},
            "review_submission": {
                "path": "review_submission.json",
                "sha256": sha256_file(review_submission_path),
            },
            "review_kit": {
                "path": "phases/18-capstones/06-peer-review/outputs/capstone_peer_review_kit.py",
                "sha256": sha256_file(Path(__file__)),
            },
            "lock_file": {
                "path": "uv.lock",
                "sha256": sha256_file(REPO_ROOT / "uv.lock")
                if (REPO_ROOT / "uv.lock").is_file()
                else None,
            },
        },
        "outputs": {output_id: output_record(path) for output_id, path in generated.items()},
    }
    manifest_path = write_json(output / "review_manifest.json", manifest)
    return {"report": report, "state": state, "manifest": manifest, "manifest_path": manifest_path}


def validate_review_package(package: str | Path) -> list[dict[str, Any]]:
    root = Path(package)
    manifest_path = root / "review_manifest.json"
    if not manifest_path.is_file():
        return [{"field": "review_manifest.json", "reason": "missing"}]
    return validate_manifest_outputs(root, read_json(manifest_path))


def load_upstream_verifier():
    spec = importlib.util.spec_from_file_location(
        "capstone_independent_verifier_for_review", UPSTREAM_VERIFIER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {UPSTREAM_VERIFIER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def reference_review_spec() -> dict[str, Any]:
    return {
        "version": REVIEW_VERSION,
        "project_id": "weekly-retention-decision-core",
        "verification_id": "weekly-retention-core-verification-v1",
        "review_id": "weekly-retention-core-review-v1",
        "allowed_reviewer_types": sorted(REVIEWER_TYPES),
        "allowed_severities": sorted(SEVERITIES),
        "allowed_response_statuses": sorted(RESPONSE_STATUSES),
        "required_self_review_checks": [
            "decision_and_claim_boundary",
            "data_rights_and_privacy",
            "baseline_and_method",
            "verification_and_failure_modes",
            "handoff_and_limitations",
        ],
        "rerun_checks": {
            "sensitivity_analysis": "Re-evaluate the frozen decision and every predeclared flip.",
            "claim_evidence_audit": "Re-check exact evidence and limitations for reviewed claims.",
            "clean_room_rerun_summary": (
                "Re-check what clean-room evidence does and does not prove."
            ),
        },
        "change_check_map": {
            "reviewed_claims.json#claim_id=claim-sensitivity": [
                "sensitivity_analysis",
                "claim_evidence_audit",
            ],
            "reviewed_claims.json#claim_id=claim-clean-room": [
                "clean_room_rerun_summary",
                "claim_evidence_audit",
            ],
            "reviewed_claims.json#claim_id=claim-baseline": [
                "sensitivity_analysis",
                "claim_evidence_audit",
            ],
        },
        "rubric_dimensions": [item[0] for item in RUBRIC_DIMENSIONS],
    }


def reference_review_submission(manifest_sha256: str) -> dict[str, Any]:
    reviewer_id = "independent-review-agent-01"
    proposed_claims = [
        {
            "claim_id": "claim-priority",
            "statement": "The verified candidate ranking places high_touch first.",
            "evidence_path": "claim_evidence_audit.csv#claim_id=implementation-claim-01",
            "limitation": "Observed priority is not an intervention effect.",
            "assertion": {"top_ranked_segment": "high_touch"},
        },
        {
            "claim_id": "claim-sensitivity",
            "statement": "The candidate decision is robust across all predeclared scenarios.",
            "evidence_path": "sensitivity_report.csv#scenario_id=frozen_gate",
            "limitation": "Scenarios cover only the predeclared threshold and capacity changes.",
            "assertion": {"robust_across_scenarios": True, "decision_flip_scenarios": []},
        },
        {
            "claim_id": "claim-clean-room",
            "statement": "The clean-room rerun proves that network access was technically blocked.",
            "evidence_path": "clean_room_rerun.json#network_access_declared",
            "limitation": "The run used the environment recorded by the verifier.",
            "assertion": {"network_access_declared": False, "technical_network_block_proven": True},
        },
    ]
    reviewed_claims = [
        proposed_claims[0],
        {
            "claim_id": "claim-sensitivity",
            "statement": (
                "The frozen gate retains baseline; one lower-threshold scenario flips to candidate."
            ),
            "evidence_path": (
                "sensitivity_report.csv#scenario_id=threshold_minus_practical_improvement"
            ),
            "limitation": (
                "The conclusion is threshold-sensitive and is not robust across all scenarios."
            ),
            "assertion": {
                "robust_across_scenarios": False,
                "decision_flip_scenarios": ["threshold_minus_practical_improvement"],
            },
        },
        {
            "claim_id": "claim-clean-room",
            "statement": (
                "The clean-room rerun declared no network access and reproduced published outputs."
            ),
            "evidence_path": "clean_room_rerun.json#network_access_declared",
            "limitation": (
                "The evidence does not prove that network access was technically blocked."
            ),
            "assertion": {
                "network_access_declared": False,
                "technical_network_block_proven": False,
            },
        },
        {
            "claim_id": "claim-baseline",
            "statement": (
                "The frozen acceptance gate retains baseline because candidate "
                "misses the practical threshold."
            ),
            "evidence_path": "verification_report.json#summary.selected_method",
            "limitation": (
                "A lower post-hoc threshold would change the selection but cannot "
                "replace the frozen gate."
            ),
            "assertion": {"selected_method": "baseline", "frozen_gate_preserved": True},
        },
    ]
    reviewed_by_id = {item["claim_id"]: item for item in reviewed_claims}
    findings = [
        {
            "finding_id": "review-finding-001",
            "severity": "major",
            "title": "Sensitivity claim is broader than the verified scenarios",
            "claim_id": "claim-sensitivity",
            "evidence_path": (
                "sensitivity_report.csv#scenario_id=threshold_minus_practical_improvement"
            ),
            "expected_behavior": (
                "State the frozen selection and disclose the observed decision flip."
            ),
            "verification_method": "Rerun sensitivity_analysis and claim_evidence_audit.",
            "raised_by_reviewer_id": reviewer_id,
        },
        {
            "finding_id": "review-finding-002",
            "severity": "minor",
            "title": "Network isolation wording overstates clean-room evidence",
            "claim_id": "claim-clean-room",
            "evidence_path": "clean_room_rerun.json#network_access_declared",
            "expected_behavior": (
                "Separate a no-network declaration from technical network blocking."
            ),
            "verification_method": "Rerun clean_room_rerun_summary and claim_evidence_audit.",
            "raised_by_reviewer_id": reviewer_id,
        },
        {
            "finding_id": "review-finding-003",
            "severity": "question",
            "title": "Which method survives the frozen acceptance gate?",
            "claim_id": "claim-baseline",
            "evidence_path": "verification_report.json#summary.selected_method",
            "expected_behavior": "Add the retained baseline decision and its threshold limitation.",
            "verification_method": "Rerun sensitivity_analysis and claim_evidence_audit.",
            "raised_by_reviewer_id": reviewer_id,
        },
    ]
    responses = [
        {
            "response_id": "author-response-001",
            "finding_id": "review-finding-001",
            "response_status": "accepted",
            "rationale": (
                "The original wording hid a predeclared decision flip; the claim is narrowed."
            ),
            "changed_scopes": ["reviewed_claims.json#claim_id=claim-sensitivity"],
            "rerun_check_ids": ["sensitivity_analysis", "claim_evidence_audit"],
            "response_evidence_paths": [
                "sensitivity_report.csv#scenario_id=threshold_minus_practical_improvement"
            ],
            "reviewed_claim_sha256": canonical_sha256(reviewed_by_id["claim-sensitivity"]),
        },
        {
            "response_id": "author-response-002",
            "finding_id": "review-finding-002",
            "response_status": "accepted",
            "rationale": (
                "The revised claim reports the declaration and preserves the "
                "missing enforcement limitation."
            ),
            "changed_scopes": ["reviewed_claims.json#claim_id=claim-clean-room"],
            "rerun_check_ids": ["clean_room_rerun_summary", "claim_evidence_audit"],
            "response_evidence_paths": ["clean_room_rerun.json#network_access_declared"],
            "reviewed_claim_sha256": canonical_sha256(reviewed_by_id["claim-clean-room"]),
        },
        {
            "response_id": "author-response-003",
            "finding_id": "review-finding-003",
            "response_status": "accepted",
            "rationale": (
                "The reviewed claim now names baseline and keeps the post-hoc "
                "threshold scenario separate."
            ),
            "changed_scopes": ["reviewed_claims.json#claim_id=claim-baseline"],
            "rerun_check_ids": ["sensitivity_analysis", "claim_evidence_audit"],
            "response_evidence_paths": ["verification_report.json#summary.selected_method"],
            "reviewed_claim_sha256": canonical_sha256(reviewed_by_id["claim-baseline"]),
        },
    ]
    return {
        "version": REVIEW_VERSION,
        "project_id": "weekly-retention-decision-core",
        "verification_id": "weekly-retention-core-verification-v1",
        "review_id": "weekly-retention-core-review-v1",
        "self_review": {
            "author_id": "learner-reference-author",
            "completed_at": "2026-01-13T09:30:00Z",
            "checks": [
                {"check_id": check_id, "completed": True}
                for check_id in reference_review_spec()["required_self_review_checks"]
            ],
        },
        "reviewer": {
            "reviewer_id": reviewer_id,
            "reviewer_type": "independent_agent",
            "is_project_author": False,
            "conflict_of_interest": False,
            "clean_review_context": True,
            "assistance_disclosure": (
                "Independent agent reviewed only the immutable verification package "
                "and this review contract."
            ),
            "reviewed_manifest_sha256": manifest_sha256,
            "review_started_at": "2026-01-13T10:00:00Z",
        },
        "proposed_claims": proposed_claims,
        "findings": findings,
        "author_responses": responses,
        "reviewed_claims": reviewed_claims,
        "re_reviewed_at": "2026-01-13T12:00:00Z",
    }


def write_sample_inputs(root: str | Path) -> dict[str, Path]:
    target = Path(root)
    target.mkdir(parents=True, exist_ok=True)
    verifier = load_upstream_verifier()
    build_inputs_root = target / "_verification_build_inputs"
    upstream_inputs = verifier.write_sample_inputs(build_inputs_root)
    verification_package = target / "upstream-verification-package"
    verifier.build_verification_package(
        upstream_implementation_package=upstream_inputs["upstream_implementation_package"],
        implementation_runner=upstream_inputs["implementation_runner"],
        upstream_baseline_package=upstream_inputs["upstream_baseline_package"],
        verification_spec_path=upstream_inputs["verification_spec_path"],
        output_dir=verification_package,
    )
    shutil.rmtree(build_inputs_root)
    review_spec_path = write_json(target / "review_spec.json", reference_review_spec())
    manifest_sha = sha256_file(verification_package / "verification_manifest.json")
    submission_path = write_json(
        target / "review_submission.json", reference_review_submission(manifest_sha)
    )
    return {
        "upstream_verification_package": verification_package,
        "review_spec_path": review_spec_path,
        "review_submission_path": submission_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an evidence-based capstone peer-review package and re-review gate."
    )
    parser.add_argument("--upstream-verification-package", type=Path)
    parser.add_argument("--review-spec", type=Path)
    parser.add_argument("--review-submission", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--write-example", type=Path)
    parser.add_argument("--fail-on-invalid", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.write_example:
        paths = write_sample_inputs(args.write_example)
    else:
        missing = [
            name
            for name, value in (
                ("--upstream-verification-package", args.upstream_verification_package),
                ("--review-spec", args.review_spec),
                ("--review-submission", args.review_submission),
            )
            if value is None
        ]
        if missing:
            raise SystemExit(f"missing required arguments: {', '.join(missing)}")
        paths = {
            "upstream_verification_package": args.upstream_verification_package,
            "review_spec_path": args.review_spec,
            "review_submission_path": args.review_submission,
        }
    result = build_review_package(
        upstream_verification_package=paths["upstream_verification_package"],
        review_spec_path=paths["review_spec_path"],
        review_submission_path=paths["review_submission_path"],
        output_dir=args.output_dir,
    )
    report = result["report"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "valid": report["valid"],
                "review_id": report["review_id"],
                "findings": report["summary"]["finding_count"],
                "closed_findings": report["summary"]["closed_findings"],
                "provisional_rubric_score": report["summary"]["provisional_rubric_score"],
                "next_stage": report["summary"]["next_stage"],
                "blocking_errors": report["summary"]["blocking_errors"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.fail_on_invalid and not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
