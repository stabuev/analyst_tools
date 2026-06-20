from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


BUILDER_VERSION = "1.0.0"
DEFAULT_PHASE_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_DECISIONS = ["continue", "rollback", "investigate", "run_experiment"]
FORBIDDEN_CAUSAL_PATTERNS = [
    " caused ",
    " caused_by ",
    "caused by",
    "causal effect",
    "вызвал",
    "вызвала",
    "вызвало",
    "привел к",
    "привела к",
    "привело к",
    "из-за релиза",
]
SOURCE_TARGETS = {
    "metric-tree.json": ("01-metric-tree", "metric_tree.json"),
    "metric-specs.json": ("01-metric-tree", "metric_specs.json"),
    "tracking-plan.json": ("02-event-model", "tracking_plan.json"),
    "metrics/activity.csv": ("03-activity", "activity.csv"),
    "metrics/funnel.csv": ("04-funnels", "funnel.csv"),
    "metrics/cohorts.csv": ("05-cohorts", "cohorts.csv"),
    "metrics/retention.csv": ("06-retention", "retention.csv"),
    "metrics/monetization.csv": ("07-monetization", "monetization.csv"),
    "metrics/segments.csv": ("08-segmentation", "segments.csv"),
    "metrics/guardrails.csv": ("09-guardrails", "guardrails.csv"),
    "metrics/anomalies.json": ("10-anomalies", "anomalies.json"),
}


@dataclass(frozen=True)
class BuildResult:
    package_root: Path
    report: dict[str, Any]


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_text(path: str | Path, value: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(value, encoding="utf-8")


def read_csv(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    with Path(path).open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_paths(phase_root: Path) -> dict[str, Path]:
    return {
        target: phase_root / lesson / "outputs" / filename
        for target, (lesson, filename) in SOURCE_TARGETS.items()
    }


def copy_sources(phase_root: Path, package_root: Path) -> dict[str, dict[str, Any]]:
    copied: dict[str, dict[str, Any]] = {}
    for target, source in source_paths(phase_root).items():
        if not source.is_file():
            raise FileNotFoundError(f"missing source artifact: {source}")
        destination = package_root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        copied[target] = {
            "source": source.relative_to(phase_root).as_posix(),
            "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
        }
    return copied


def csv_row_count(path: Path) -> int:
    rows, _columns = read_csv(path)
    return len(rows)


def assessment_rows(package_root: Path) -> list[dict[str, str]]:
    rows, _columns = read_csv(package_root / "metrics" / "guardrails.csv")
    return [row for row in rows if row["row_type"] == "assessment"]


def segment_decomposition_rows(package_root: Path) -> list[dict[str, str]]:
    rows, _columns = read_csv(package_root / "metrics" / "segments.csv")
    return [row for row in rows if row["row_type"] == "decomposition"]


def final_funnel_rows(package_root: Path) -> list[dict[str, str]]:
    rows, _columns = read_csv(package_root / "metrics" / "funnel.csv")
    final_by_funnel: dict[str, dict[str, str]] = {}
    for row in rows:
        current = final_by_funnel.get(row["funnel_id"])
        if current is None or int(row["step_index"]) > int(current["step_index"]):
            final_by_funnel[row["funnel_id"]] = row
    return list(final_by_funnel.values())


def latest_complete_activity_7d(package_root: Path) -> dict[str, str] | None:
    rows, _columns = read_csv(package_root / "metrics" / "activity.csv")
    candidates = [
        row
        for row in rows
        if row["window_days"] == "7" and row["is_complete_window"] == "true"
    ]
    return max(candidates, key=lambda row: row["activity_date"]) if candidates else None


def metric_ids(package_root: Path) -> set[str]:
    ids: set[str] = set()
    metric_specs = read_json(package_root / "metric-specs.json")
    ids.update(metric["metric_id"] for metric in metric_specs.get("metrics", []))
    for row in assessment_rows(package_root):
        ids.add(row["metric_id"])
    for row in segment_decomposition_rows(package_root):
        ids.add(row["metric_id"])
    anomalies = read_json(package_root / "metrics" / "anomalies.json")
    ids.update(candidate["metric_id"] for candidate in anomalies.get("candidates", []))
    ids.add("__data_quality__")
    return ids


def build_brief(package_root: Path) -> str:
    metric_tree = read_json(package_root / "metric-tree.json")
    return f"""# Brief: product problem investigation

## Product question

{metric_tree["product_question"]}

## Decision options

{", ".join(f"`{option}`" for option in metric_tree["decision_options"])}

## Decision boundary

The package can recommend `continue`, `rollback`, `investigate` or `run_experiment`.
It must not claim that the release caused the observed movement: phase 08 is diagnostic
product analytics on observational data, not an experiment or causal design.
"""


def build_event_quality_audit(package_root: Path) -> dict[str, Any]:
    anomalies = read_json(package_root / "metrics" / "anomalies.json")
    return {
        "valid": bool(anomalies["quality_gates_passed"]),
        "source": "metrics/anomalies.json",
        "summary": anomalies["summary"],
        "checks": anomalies["quality_gates"],
    }


def build_recommendation(package_root: Path) -> dict[str, Any]:
    guardrails = assessment_rows(package_root)
    anomalies = read_json(package_root / "metrics" / "anomalies.json")
    breached = [
        row
        for row in guardrails
        if row["decision_status"] == "breached" and row["threshold_breached"] == "true"
    ]
    product_signals = [
        candidate
        for candidate in anomalies["candidates"]
        if candidate["classification"] == "product_signal"
    ]
    composition = [
        candidate
        for candidate in anomalies["candidates"]
        if candidate["classification"] == "composition"
    ]
    calendar = [
        candidate
        for candidate in anomalies["candidates"]
        if candidate["classification"] == "calendar_effect"
    ]
    if anomalies["quality_gates_passed"] and breached:
        decision = "investigate"
    elif anomalies["quality_gates_passed"]:
        decision = "continue"
    else:
        decision = "investigate"
    return {
        "version": BUILDER_VERSION,
        "allowed_decisions": ALLOWED_DECISIONS,
        "decision": decision,
        "decision_label": "Investigate before continuing rollout",
        "causal_claims_allowed": False,
        "rationale": (
            "Quality gates passed, but guardrail risks breached. The package recommends "
            "pausing automatic rollout and investigating support, cancellation and refund "
            "signals with Android release context before choosing continue or rollback."
        ),
        "options": [
            {
                "option_id": "continue",
                "status": "rejected",
                "reason": "Breached guardrails make automatic continuation too risky.",
            },
            {
                "option_id": "rollback",
                "status": "not_enough_evidence",
                "reason": "Diagnostics are observational and do not prove a release effect.",
            },
            {
                "option_id": "investigate",
                "status": "recommended",
                "reason": "Risk metrics and anomaly context agree on a product-risk investigation.",
            },
            {
                "option_id": "run_experiment",
                "status": "next_after_investigation",
                "reason": "Use an experiment after the instrumentation and rollout context are clean.",
            },
        ],
        "claims": [
            {
                "claim_id": "quality-gates-passed",
                "statement": "Freshness, duplicate, late-arrival and tracking completeness gates passed for the observation slice.",
                "metric_ids": ["__data_quality__"],
                "artifact_paths": ["metrics/anomalies.json", "audits/event-quality.json"],
                "limitation": "Passing gates means the slice is interpretable; it does not prove a product mechanism.",
                "supports_decision": True,
            },
            {
                "claim_id": "guardrails-breached",
                "statement": f"{len(breached)} guardrail metrics breached with risk direction up_is_bad.",
                "metric_ids": [row["metric_id"] for row in breached],
                "artifact_paths": ["metrics/guardrails.csv", "metrics/anomalies.json"],
                "limitation": "A guardrail breach is a risk decision rule, not a causal estimate.",
                "supports_decision": True,
            },
            {
                "claim_id": "anomaly-product-signals",
                "statement": f"{len(product_signals)} anomaly candidates are classified as product_signal after gates passed.",
                "metric_ids": [candidate["metric_id"] for candidate in product_signals],
                "artifact_paths": ["metrics/anomalies.json"],
                "limitation": "The class allows investigation of product behavior, not attribution to a release.",
                "supports_decision": True,
            },
            {
                "claim_id": "composition-context",
                "statement": f"{len(composition)} composition candidate points to mix or segment contribution.",
                "metric_ids": [candidate["metric_id"] for candidate in composition],
                "artifact_paths": ["metrics/segments.csv", "metrics/anomalies.json"],
                "limitation": "Composition explains where the aggregate moved, not why users changed behavior.",
                "supports_decision": True,
            },
            {
                "claim_id": "calendar-context",
                "statement": f"{len(calendar)} calendar candidate coincides with the comparison period.",
                "metric_ids": [candidate["metric_id"] for candidate in calendar],
                "artifact_paths": ["metrics/anomalies.json"],
                "limitation": "Calendar coincidence is context for investigation, not proof.",
                "supports_decision": True,
            },
        ],
        "next_steps": [
            {
                "step_id": "inspect-android-paywall-release",
                "owner": "product + mobile",
                "success_signal": "Support ticket rate and paywall complaints are split by platform, app_version and release cohort.",
            },
            {
                "step_id": "review-cancellations-and-refunds",
                "owner": "monetization",
                "success_signal": "Cancellation/refund reasons reconcile to subscription and order grains.",
            },
            {
                "step_id": "prepare-experiment-if-clean",
                "owner": "analytics",
                "success_signal": "A follow-up experiment or rollout holdout has explicit outcome, guardrails and decision rule.",
            },
        ],
    }


def validate_recommendation(
    recommendation: dict[str, Any],
    package_root: Path,
    known_metric_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    known = metric_ids(package_root) if known_metric_ids is None else known_metric_ids
    checks: list[dict[str, Any]] = []
    decision = recommendation.get("decision")
    checks.append({
        "id": "decision_allowed",
        "valid": decision in recommendation.get("allowed_decisions", []),
        "observed": decision,
        "expected": recommendation.get("allowed_decisions", []),
    })
    options = recommendation.get("options", [])
    checks.append({
        "id": "recommended_option_present",
        "valid": any(option.get("option_id") == decision and option.get("status") == "recommended" for option in options),
        "observed": [option.get("option_id") for option in options if option.get("status") == "recommended"],
        "expected": decision,
    })
    claims = recommendation.get("claims", [])
    checks.append({
        "id": "claims_present",
        "valid": bool(claims),
        "observed": len(claims),
        "expected": ">= 1",
    })
    missing_paths: list[str] = []
    unknown_metrics: list[str] = []
    uncited_claims: list[str] = []
    causal_claims: list[str] = []
    for claim in claims:
        claim_id = claim.get("claim_id", "")
        paths = claim.get("artifact_paths", [])
        if not paths:
            uncited_claims.append(claim_id)
        for path in paths:
            if not (package_root / path).is_file():
                missing_paths.append(path)
        for metric_id in claim.get("metric_ids", []):
            if metric_id not in known:
                unknown_metrics.append(metric_id)
        statement = f" {claim.get('statement', '').lower()} "
        if not recommendation.get("causal_claims_allowed", False):
            if any(pattern in statement for pattern in FORBIDDEN_CAUSAL_PATTERNS):
                causal_claims.append(claim_id)
    checks.extend(
        [
            {
                "id": "claim_artifacts_exist",
                "valid": not missing_paths,
                "observed": sorted(set(missing_paths)),
                "expected": "all artifact paths exist inside package",
            },
            {
                "id": "claim_metrics_resolve",
                "valid": not unknown_metrics,
                "observed": sorted(set(unknown_metrics)),
                "expected": sorted(known),
            },
            {
                "id": "claims_are_cited",
                "valid": not uncited_claims,
                "observed": uncited_claims,
                "expected": "each claim has at least one artifact path",
            },
            {
                "id": "no_unsupported_causal_claims",
                "valid": not causal_claims,
                "observed": causal_claims,
                "expected": "no causal wording without experiment or causal design",
            },
        ]
    )
    return checks


def build_metric_quality_audit(package_root: Path, recommendation: dict[str, Any]) -> dict[str, Any]:
    row_counts = {
        "activity": csv_row_count(package_root / "metrics" / "activity.csv"),
        "funnel": csv_row_count(package_root / "metrics" / "funnel.csv"),
        "cohorts": csv_row_count(package_root / "metrics" / "cohorts.csv"),
        "retention": csv_row_count(package_root / "metrics" / "retention.csv"),
        "monetization": csv_row_count(package_root / "metrics" / "monetization.csv"),
        "segments": csv_row_count(package_root / "metrics" / "segments.csv"),
        "guardrails": csv_row_count(package_root / "metrics" / "guardrails.csv"),
    }
    required_files = [
        "brief.md",
        "metric-tree.json",
        "metric-specs.json",
        "tracking-plan.json",
        "metrics/activity.csv",
        "metrics/funnel.csv",
        "metrics/cohorts.csv",
        "metrics/retention.csv",
        "metrics/monetization.csv",
        "metrics/segments.csv",
        "metrics/guardrails.csv",
        "metrics/anomalies.json",
        "figures/metric-trend.png",
        "figures/segment-decomposition.png",
        "report.md",
        "recommendation.json",
    ]
    checks = [
        {
            "id": "required_files_present",
            "valid": all((package_root / path).is_file() for path in required_files),
            "observed": [path for path in required_files if not (package_root / path).is_file()],
            "expected": [],
        },
        {
            "id": "metric_tables_non_empty",
            "valid": all(count > 0 for count in row_counts.values()),
            "observed": row_counts,
            "expected": "all metric tables have rows",
        },
    ]
    checks.extend(validate_recommendation(recommendation, package_root))
    return {
        "valid": all(check["valid"] for check in checks),
        "source": "product_problem_builder.py",
        "row_counts": row_counts,
        "checks": checks,
    }


def build_metric_trend_figure(package_root: Path) -> None:
    guardrails = assessment_rows(package_root)
    labels = [row["metric_id"].replace("_rate", "\nrate") for row in guardrails]
    baseline = [float(row["baseline_value"]) for row in guardrails]
    comparison = [float(row["comparison_value"]) for row in guardrails]
    positions = list(range(len(labels)))
    width = 0.35
    figure, axis = plt.subplots(figsize=(8, 4.5), layout="constrained")
    axis.bar([position - width / 2 for position in positions], baseline, width=width, label="baseline", color="#64748b")
    axis.bar([position + width / 2 for position in positions], comparison, width=width, label="comparison", color="#dc2626")
    axis.set(
        title="Guardrail rates: baseline vs comparison",
        ylabel="Rate",
        ylim=(0, 0.8),
        xticks=positions,
        xticklabels=labels,
    )
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    figure.savefig(package_root / "figures" / "metric-trend.png", dpi=120, metadata={"Software": "analyst-tools-course"})
    plt.close(figure)


def build_segment_decomposition_figure(package_root: Path) -> None:
    rows = segment_decomposition_rows(package_root)
    labels = [f"{row['dimension']}={row['segment_value']}" for row in rows]
    values = [float(row["total_delta_contribution"]) for row in rows]
    colors = ["#dc2626" if value < 0 else "#2563eb" for value in values]
    figure, axis = plt.subplots(figsize=(8, 4.5), layout="constrained")
    axis.bar(labels, values, color=colors)
    axis.axhline(0, color="#111827", linewidth=1)
    axis.set(
        title="Activation decomposition by platform",
        ylabel="Total delta contribution",
        xlabel="Segment",
    )
    axis.grid(axis="y", alpha=0.2)
    figure.savefig(package_root / "figures" / "segment-decomposition.png", dpi=120, metadata={"Software": "analyst-tools-course"})
    plt.close(figure)


def report_markdown(package_root: Path, recommendation: dict[str, Any]) -> str:
    metric_tree = read_json(package_root / "metric-tree.json")
    anomalies = read_json(package_root / "metrics" / "anomalies.json")
    guardrails = assessment_rows(package_root)
    final_funnels = final_funnel_rows(package_root)
    activity = latest_complete_activity_7d(package_root)
    guardrail_lines = "\n".join(
        f"- `{row['metric_id']}`: baseline `{row['baseline_value']}`, comparison `{row['comparison_value']}`, delta `{row['absolute_delta']}`, status `{row['decision_status']}`"
        for row in guardrails
    )
    funnel_lines = "\n".join(
        f"- `{row['metric_id']}` final step `{row['event_name']}`: conversion_from_start `{row['conversion_from_start']}` on `{row['units']}` units"
        for row in final_funnels
    )
    claim_rows = "\n".join(
        "| `{claim_id}` | {statement} | `{artifacts}` | {limitation} |".format(
            claim_id=claim["claim_id"],
            statement=claim["statement"],
            artifacts="`, `".join(claim["artifact_paths"]),
            limitation=claim["limitation"],
        )
        for claim in recommendation["claims"]
    )
    next_steps = "\n".join(
        f"1. `{step['step_id']}` ({step['owner']}): {step['success_signal']}"
        for step in recommendation["next_steps"]
    )
    activity_line = "No complete 7-day activity row found."
    if activity is not None:
        activity_line = (
            f"Latest complete 7-day active audience row is `{activity['activity_date']}`: "
            f"`{activity['active_users']}/{activity['eligible_users']}` users, rate `{activity['activity_rate']}`."
        )
    return f"""# Product problem investigation

## Question

{metric_tree["product_question"]}

## Recommendation

Recommended decision: `{recommendation["decision"]}`.

Pause automatic rollout and investigate the product-risk signals before choosing between
`continue` and `rollback`. The evidence supports a risk investigation, but it does not
prove a release effect.

## What We Know

{activity_line}

Final funnel checkpoints:

{funnel_lines}

Guardrail assessment:

{guardrail_lines}

Anomaly summary:

- quality gates passed: `{anomalies["quality_gates_passed"]}`
- product signal candidates: `{anomalies["summary"]["by_classification"]["product_signal"]}`
- composition candidates: `{anomalies["summary"]["by_classification"]["composition"]}`
- calendar-effect candidates: `{anomalies["summary"]["by_classification"]["calendar_effect"]}`

## Evidence Map

| Claim | Statement | Artifacts | Limitation |
|---|---|---|---|
{claim_rows}

## What We Cannot Say

- We cannot say that release `R002` produced the risk movement from these observational diagnostics alone.
- We cannot choose rollback solely from the calendar match; the package needs release notes, platform rollout details and support/cancel/refund inspection.
- We cannot ignore guardrails just because activation-related inputs look useful.

## Next Steps

{next_steps}

## Package Contents

- `brief.md` - decision question and boundary.
- `metric-tree.json`, `metric-specs.json`, `tracking-plan.json` - contracts.
- `metrics/` - tables and anomaly report from phase lessons.
- `audits/` - event and metric quality checks for this package.
- `figures/` - static figures for guardrails and decomposition.
- `recommendation.json` - machine-readable decision, options, claims and next steps.
- `manifest.json` - SHA-256 manifest for every delivered file.
"""


def manifest_for(package_root: Path, copied_sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    files = {}
    for path in sorted(package_root.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative = path.relative_to(package_root).as_posix()
            files[relative] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return {
        "version": BUILDER_VERSION,
        "package": "product-problem-investigation",
        "source_artifacts": copied_sources,
        "files": files,
    }


def verify_manifest(package_root: Path) -> list[dict[str, Any]]:
    manifest = read_json(package_root / "manifest.json")
    checks = []
    for relative, expected in manifest["files"].items():
        path = package_root / relative
        checks.append(
            {
                "path": relative,
                "valid": path.is_file()
                and path.stat().st_size == expected["bytes"]
                and sha256_file(path) == expected["sha256"],
            }
        )
    return checks


def build_package(phase_root: str | Path, output: str | Path) -> BuildResult:
    phase_root = Path(phase_root).resolve()
    package_root = Path(output).resolve()
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)
    (package_root / "audits").mkdir()
    (package_root / "figures").mkdir()
    copied_sources = copy_sources(phase_root, package_root)
    write_text(package_root / "brief.md", build_brief(package_root))
    build_metric_trend_figure(package_root)
    build_segment_decomposition_figure(package_root)
    recommendation = build_recommendation(package_root)
    write_json(package_root / "recommendation.json", recommendation)
    write_text(package_root / "report.md", report_markdown(package_root, recommendation))
    write_json(package_root / "audits" / "event-quality.json", build_event_quality_audit(package_root))
    metric_quality = build_metric_quality_audit(package_root, recommendation)
    write_json(package_root / "audits" / "metric-quality.json", metric_quality)
    manifest = manifest_for(package_root, copied_sources)
    write_json(package_root / "manifest.json", manifest)
    report = {
        "valid": metric_quality["valid"] and all(item["valid"] for item in verify_manifest(package_root)),
        "package_root": str(package_root),
        "decision": recommendation["decision"],
        "files": len(manifest["files"]) + 1,
        "manifest": "manifest.json",
    }
    return BuildResult(package_root=package_root, report=report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the phase 08 product problem investigation package.")
    parser.add_argument("--phase-root", default=str(DEFAULT_PHASE_ROOT))
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_package(args.phase_root, args.output)
    print(json.dumps(result.report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
