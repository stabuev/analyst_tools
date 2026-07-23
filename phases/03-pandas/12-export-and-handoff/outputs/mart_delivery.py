from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

if __package__:
    from .mart_contracts import (
        BUILDER_NAME,
        BUILDER_VERSION,
        DATASET_SCHEMA_VERSION,
        MANIFEST_VERSION,
        OUTPUT_COLUMNS,
        OUTPUT_SCHEMA,
        SOURCE_NAMES,
        MartContractError,
        assert_unique_nonblank,
    )
else:
    from mart_contracts import (
        BUILDER_NAME,
        BUILDER_VERSION,
        DATASET_SCHEMA_VERSION,
        MANIFEST_VERSION,
        OUTPUT_COLUMNS,
        OUTPUT_SCHEMA,
        SOURCE_NAMES,
        MartContractError,
        assert_unique_nonblank,
    )


def sha256(path: Path) -> str:
    """Return a SHA-256 digest for the exact bytes stored at path."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_source_paths(source_paths: dict[str, Path]) -> dict[str, Path]:
    if set(source_paths) != set(SOURCE_NAMES):
        raise MartContractError(
            f"export_delivery: expected source paths {list(SOURCE_NAMES)}"
        )
    normalized = {name: Path(source_paths[name]) for name in SOURCE_NAMES}
    for name, path in normalized.items():
        if not path.is_file():
            raise MartContractError(
                f"export_delivery: source file does not exist: {name}={path}"
            )
    return normalized


def _validate_publish_gate(quality: dict[str, Any]) -> None:
    if not isinstance(quality, dict):
        raise MartContractError("export_delivery: quality report is missing")
    status = quality.get("publish_status")
    if status not in {"passed", "passed_with_warnings"}:
        raise MartContractError(
            f"export_delivery: publish gate is not open: {status!r}"
        )
    checks = quality.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise MartContractError("export_delivery: quality checks are missing")
    invalid_statuses = [
        check.get("status")
        for check in checks.values()
        if check.get("status") not in {"pass", "warning"}
    ]
    if invalid_statuses:
        raise MartContractError(
            "export_delivery: invalid check statuses: "
            f"{sorted(repr(value) for value in invalid_statuses)}"
        )
    expected_status = (
        "passed_with_warnings"
        if any(check["status"] == "warning" for check in checks.values())
        else "passed"
    )
    if status != expected_status:
        raise MartContractError(
            "export_delivery: publish status is inconsistent with checks"
        )


def export_delivery(
    mart: pd.DataFrame,
    quality: dict[str, Any],
    output_dir: Path,
    source_paths: dict[str, Path],
    *,
    business_timezone: str,
) -> dict[str, Any]:
    """Write a deterministic CSV and versioned manifest, then verify the package."""

    _validate_publish_gate(quality)
    if mart.columns.tolist() != OUTPUT_COLUMNS:
        raise MartContractError(
            "export_delivery: mart columns do not match order_mart/v1"
        )
    assert_unique_nonblank(mart, ["order_id"], stage="export_delivery")
    if mart["order_id"].tolist() != sorted(mart["order_id"].tolist()):
        raise MartContractError("export_delivery: mart order is not deterministic")
    grain_check = quality["checks"].get("grain")
    rows_check = quality["checks"].get("rows_equal_orders")
    if (
        not isinstance(grain_check, dict)
        or grain_check.get("expected") != ["order_id"]
        or grain_check.get("rows") != len(mart)
        or grain_check.get("unique") is not True
    ):
        raise MartContractError(
            "export_delivery: grain check does not describe the mart"
        )
    if (
        not isinstance(rows_check, dict)
        or rows_check.get("observed") != len(mart)
    ):
        raise MartContractError(
            "export_delivery: row-count check does not describe the mart"
        )
    normalized_sources = _validate_source_paths(source_paths)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    mart_path = output_dir / "order_mart.csv"
    manifest_path = output_dir / "manifest.json"
    mart.to_csv(
        mart_path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        na_rep="",
        date_format="%Y-%m-%dT%H:%M:%SZ",
        float_format="%.10g",
    )

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "builder": {
            "name": BUILDER_NAME,
            "version": BUILDER_VERSION,
        },
        "parameters": {
            "business_timezone": business_timezone,
            "unknown_user_policy": "keep_and_flag",
            "amount_mismatch_policy": "block",
        },
        "publish_status": quality["publish_status"],
        "dataset": {
            "name": "order_mart",
            "grain": ["order_id"],
            "rows": len(mart),
            "schema": OUTPUT_SCHEMA,
        },
        "quality": quality,
        "artifact": {
            "path": mart_path.name,
            "format": "csv",
            "encoding": "utf-8",
            "delimiter": ",",
            "line_terminator": "LF",
            "na_rep": "",
            "sha256": sha256(mart_path),
        },
        "sources": {
            name: {
                "path": str(path),
                "sha256": sha256(path),
            }
            for name, path in normalized_sources.items()
        },
    }
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    verify_delivery(output_dir)
    return manifest


def verify_delivery(output_dir: Path) -> dict[str, Any]:
    """Verify the delivery package from a recipient's point of view."""

    output_dir = Path(output_dir)
    manifest_path = output_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MartContractError(
            f"verify_delivery: cannot read manifest: {error}"
        ) from error

    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise MartContractError("verify_delivery: unsupported manifest version")
    if manifest.get("dataset_schema_version") != DATASET_SCHEMA_VERSION:
        raise MartContractError("verify_delivery: unsupported dataset schema version")
    if manifest.get("publish_status") not in {
        "passed",
        "passed_with_warnings",
    }:
        raise MartContractError("verify_delivery: package was not published")

    parameters = manifest.get("parameters")
    if (
        not isinstance(parameters, dict)
        or not isinstance(parameters.get("business_timezone"), str)
        or not parameters["business_timezone"].strip()
        or parameters.get("unknown_user_policy") != "keep_and_flag"
        or parameters.get("amount_mismatch_policy") != "block"
    ):
        raise MartContractError("verify_delivery: build parameters are invalid")

    artifact = manifest.get("artifact")
    if not isinstance(artifact, dict):
        raise MartContractError("verify_delivery: artifact metadata is missing")
    if (
        artifact.get("format") != "csv"
        or artifact.get("encoding") != "utf-8"
        or artifact.get("delimiter") != ","
        or artifact.get("line_terminator") != "LF"
        or artifact.get("na_rep") != ""
    ):
        raise MartContractError("verify_delivery: CSV representation is invalid")
    artifact_name = artifact.get("path")
    if not isinstance(artifact_name, str) or Path(artifact_name).name != artifact_name:
        raise MartContractError("verify_delivery: artifact path must be a file name")
    mart_path = output_dir / artifact_name
    if not mart_path.is_file():
        raise MartContractError("verify_delivery: artifact file is missing")
    actual_digest = sha256(mart_path)
    if actual_digest != artifact.get("sha256"):
        raise MartContractError("verify_delivery: artifact checksum mismatch")

    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict):
        raise MartContractError("verify_delivery: dataset contract is missing")
    if dataset.get("name") != "order_mart" or dataset.get("grain") != ["order_id"]:
        raise MartContractError("verify_delivery: dataset identity or grain is invalid")
    schema = dataset.get("schema")
    if schema != OUTPUT_SCHEMA:
        raise MartContractError("verify_delivery: dataset schema is invalid")

    try:
        delivered = pd.read_csv(
            mart_path,
            dtype="string",
            keep_default_na=False,
            encoding=artifact.get("encoding", "utf-8"),
        )
    except (OSError, ValueError) as error:
        raise MartContractError(
            f"verify_delivery: cannot read artifact: {error}"
        ) from error
    if delivered.columns.tolist() != OUTPUT_COLUMNS:
        raise MartContractError("verify_delivery: CSV columns differ from manifest")
    if len(delivered) != dataset.get("rows"):
        raise MartContractError("verify_delivery: CSV row count differs from manifest")

    order_id = delivered["order_id"].str.strip()
    if order_id.eq("").any() or order_id.duplicated().any():
        raise MartContractError("verify_delivery: delivered grain is invalid")
    if order_id.tolist() != sorted(order_id.tolist()):
        raise MartContractError("verify_delivery: delivered order is not deterministic")

    quality = manifest.get("quality")
    if not isinstance(quality, dict) or quality.get("publish_status") != manifest.get(
        "publish_status"
    ):
        raise MartContractError("verify_delivery: quality status is inconsistent")
    try:
        _validate_publish_gate(quality)
    except MartContractError as error:
        raise MartContractError(
            f"verify_delivery: quality report is invalid: {error}"
        ) from error
    grain_check = quality["checks"].get("grain")
    rows_check = quality["checks"].get("rows_equal_orders")
    if (
        not isinstance(grain_check, dict)
        or grain_check.get("rows") != len(delivered)
        or grain_check.get("expected") != ["order_id"]
        or grain_check.get("unique") is not True
        or not isinstance(rows_check, dict)
        or rows_check.get("observed") != len(delivered)
    ):
        raise MartContractError(
            "verify_delivery: quality evidence differs from delivered data"
        )

    return {
        "valid": True,
        "manifest_version": manifest["manifest_version"],
        "dataset_schema_version": manifest["dataset_schema_version"],
        "publish_status": manifest["publish_status"],
        "rows": len(delivered),
        "grain": ["order_id"],
        "artifact_sha256": actual_digest,
    }
