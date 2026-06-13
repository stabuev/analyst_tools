from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


class BriefError(ValueError):
    """Raised when a visual question specification is incomplete or inconsistent."""


QUESTION_PLANS = {
    "trend": {
        "primary_view": "line with visible observations",
        "alternative_view": "small-multiple dot plots",
        "required_context": [
            "consistent time grain",
            "complete observation windows",
            "sample size or denominator for every period",
            "uncertainty when values are estimates",
        ],
        "avoid": [
            "connecting missing periods as observed values",
            "dual axes for unrelated metrics",
            "interpreting the last incomplete period",
        ],
    },
    "comparison": {
        "primary_view": "sorted dot plot on a common scale",
        "alternative_view": "aligned bars with an honest baseline",
        "required_context": [
            "explicit baseline group",
            "group sample sizes",
            "same metric definition for every group",
            "uncertainty when values are estimates",
        ],
        "avoid": [
            "truncated bar baseline",
            "alphabetical ordering when magnitude is the question",
            "using area or volume for one-dimensional magnitude",
        ],
    },
    "distribution": {
        "primary_view": "ECDF with a documented histogram",
        "alternative_view": "box plot with visible raw or binned observations",
        "required_context": [
            "binning rule when a histogram is used",
            "sample size",
            "missing-value policy",
            "outlier policy and scale choice",
        ],
        "avoid": [
            "deleting outliers only to improve appearance",
            "comparing histograms with different bin edges",
            "reporting only the mean for a skewed distribution",
        ],
    },
    "relationship": {
        "primary_view": "scatter with transparency and grouped summaries",
        "alternative_view": "hexbin or small multiples for dense data",
        "required_context": [
            "units and ranges of both variables",
            "overplotting control",
            "stratified control summaries",
            "warning that association is not causation",
        ],
        "avoid": [
            "fitting a trend without showing observations",
            "hiding segment reversals in one aggregate line",
            "describing association as a causal effect",
        ],
    },
    "composition": {
        "primary_view": "aligned share bars with absolute counts",
        "alternative_view": "small multiples of group shares",
        "required_context": [
            "common denominator",
            "absolute count beside every share",
            "stable category definitions",
            "explicit treatment of missing categories",
        ],
        "avoid": [
            "shares without denominators",
            "too many categories in a pie chart",
            "comparing areas or angles when precise differences matter",
        ],
    },
}

METRIC_KINDS = {"rate", "count", "amount", "duration", "continuous"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
CAUSAL_TERMS = (
    "cause",
    "causal",
    "effect of",
    "impact of",
    "причин",
    "эффект",
    "влияни",
)

EXAMPLE_SPEC = {
    "id": "activation-after-release",
    "question": "Как изменилась семидневная активация после релиза 2026-03-02?",
    "decision": "Определить сегмент для следующей технической и продуктовой диагностики.",
    "question_type": "trend",
    "population": "Новые пользователи подписочного сервиса.",
    "grain": "Один пользователь с полным семидневным окном после регистрации.",
    "metric": {
        "name": "activation_7d",
        "kind": "rate",
        "definition": "Доля пользователей с activated_7d=true среди полных окон.",
        "denominator": "Пользователи с observed_days=7 после удаления дубликатов.",
    },
    "comparison": {
        "dimension": "cohort_week",
        "levels": ["до релиза", "после релиза"],
        "baseline": "до релиза",
        "time_column": "cohort_week",
        "segments": ["platform", "acquisition_channel"],
    },
    "expected_pattern": (
        "Общий спад может сочетать изменение channel mix и отдельное ухудшение Android 2.4."
    ),
    "stop_rule": (
        "Не интерпретировать тренд, пока неполные окна, дубликаты и знаменатель не проверены."
    ),
}


def require_text(value: Any, location: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise BriefError(f"{location} must be text with at least {minimum} characters")
    return value.strip()


def require_mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BriefError(f"{location} must be an object")
    return value


def require_text_list(value: Any, location: str, *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise BriefError(f"{location} must contain at least {minimum} values")
    values = [require_text(item, f"{location}[{index}]") for index, item in enumerate(value)]
    if len(values) != len(set(values)):
        raise BriefError(f"{location} contains duplicate values")
    return values


def normalize_metric(value: Any) -> dict[str, str]:
    metric = require_mapping(value, "metric")
    required = {"name", "kind", "definition"}
    allowed = required | {"denominator"}
    missing = sorted(required - set(metric))
    unexpected = sorted(set(metric) - allowed)
    if missing or unexpected:
        raise BriefError(f"metric fields: missing={missing}, unexpected={unexpected}")
    kind = require_text(metric["kind"], "metric.kind")
    if kind not in METRIC_KINDS:
        raise BriefError(f"metric.kind must be one of {sorted(METRIC_KINDS)}")
    normalized = {
        "name": require_text(metric["name"], "metric.name"),
        "kind": kind,
        "definition": require_text(metric["definition"], "metric.definition", minimum=15),
    }
    if kind == "rate":
        normalized["denominator"] = require_text(
            metric.get("denominator"),
            "metric.denominator",
            minimum=10,
        )
    elif "denominator" in metric:
        normalized["denominator"] = require_text(
            metric["denominator"],
            "metric.denominator",
        )
    return normalized


def normalize_comparison(value: Any, question_type: str) -> dict[str, Any]:
    comparison = require_mapping(value, "comparison")
    required = {"dimension", "levels", "baseline"}
    allowed = required | {"time_column", "segments", "x", "y"}
    missing = sorted(required - set(comparison))
    unexpected = sorted(set(comparison) - allowed)
    if missing or unexpected:
        raise BriefError(f"comparison fields: missing={missing}, unexpected={unexpected}")
    levels = require_text_list(
        comparison["levels"],
        "comparison.levels",
        minimum=2 if question_type in {"trend", "comparison", "composition"} else 1,
    )
    baseline = require_text(comparison["baseline"], "comparison.baseline")
    if baseline not in levels:
        raise BriefError("comparison.baseline must be present in comparison.levels")
    normalized: dict[str, Any] = {
        "dimension": require_text(comparison["dimension"], "comparison.dimension"),
        "levels": levels,
        "baseline": baseline,
    }
    if "segments" in comparison:
        normalized["segments"] = require_text_list(
            comparison["segments"],
            "comparison.segments",
        )
    if question_type == "trend":
        normalized["time_column"] = require_text(
            comparison.get("time_column"),
            "comparison.time_column",
        )
    if question_type == "relationship":
        normalized["x"] = require_text(comparison.get("x"), "comparison.x")
        normalized["y"] = require_text(comparison.get("y"), "comparison.y")
    return normalized


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    required = {
        "id",
        "question",
        "decision",
        "question_type",
        "population",
        "grain",
        "metric",
        "comparison",
        "expected_pattern",
        "stop_rule",
    }
    missing = sorted(required - set(spec))
    unexpected = sorted(set(spec) - required)
    if missing or unexpected:
        raise BriefError(f"top-level fields: missing={missing}, unexpected={unexpected}")
    identifier = require_text(spec["id"], "id")
    if not IDENTIFIER.fullmatch(identifier):
        raise BriefError("id must use lowercase kebab-case")
    question_type = require_text(spec["question_type"], "question_type")
    if question_type not in QUESTION_PLANS:
        raise BriefError(f"question_type must be one of {sorted(QUESTION_PLANS)}")
    return {
        "id": identifier,
        "question": require_text(spec["question"], "question", minimum=20),
        "decision": require_text(spec["decision"], "decision", minimum=20),
        "question_type": question_type,
        "population": require_text(spec["population"], "population", minimum=10),
        "grain": require_text(spec["grain"], "grain", minimum=10),
        "metric": normalize_metric(spec["metric"]),
        "comparison": normalize_comparison(spec["comparison"], question_type),
        "expected_pattern": require_text(
            spec["expected_pattern"],
            "expected_pattern",
            minimum=20,
        ),
        "stop_rule": require_text(spec["stop_rule"], "stop_rule", minimum=20),
    }


def causal_warning(spec: dict[str, Any]) -> list[str]:
    text = " ".join([spec["question"], spec["decision"], spec["expected_pattern"]]).casefold()
    if any(term in text for term in CAUSAL_TERMS):
        return [
            "The wording suggests causality. A visualization can show association, "
            "but identification requires an experiment or an explicit causal design."
        ]
    return []


def build_brief(spec: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_spec(spec)
    plan = deepcopy(QUESTION_PLANS[normalized["question_type"]])
    comparison = normalized["comparison"]
    encodings: dict[str, str] = {"y": normalized["metric"]["name"]}
    if normalized["question_type"] == "trend":
        encodings["x"] = comparison["time_column"]
    elif normalized["question_type"] == "relationship":
        encodings = {"x": comparison["x"], "y": comparison["y"]}
    else:
        encodings["x"] = comparison["dimension"]
    if comparison.get("segments"):
        encodings["facet_or_color"] = ", ".join(comparison["segments"])
    plan["encodings"] = encodings
    checks = [
        {
            "id": "grain",
            "question": f"Does every source row match this grain: {normalized['grain']}?",
        },
        {
            "id": "population",
            "question": f"Does the filtered data represent: {normalized['population']}?",
        },
        {
            "id": "metric",
            "question": (
                "Can the plotted values be reproduced from a control table using: "
                f"{normalized['metric']['definition']}?"
            ),
        },
        {
            "id": "comparison",
            "question": (
                f"Are all levels of {comparison['dimension']} comparable to baseline "
                f"{comparison['baseline']}?"
            ),
        },
        {
            "id": "stop-rule",
            "question": f"Has this stop rule been satisfied: {normalized['stop_rule']}?",
        },
    ]
    return {
        "version": "1.0.0",
        "status": "ready",
        "brief": normalized,
        "chart_plan": plan,
        "required_checks": checks,
        "interpretation_contract": {
            "observation": "State only what the checked values and encodings show.",
            "explanation": "Label explanations as hypotheses unless independently identified.",
            "decision": normalized["decision"],
            "stop_rule": normalized["stop_rule"],
        },
        "warnings": causal_warning(normalized),
    }


def load_spec(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise BriefError(f"cannot read spec: {error}") from error
    except json.JSONDecodeError as error:
        raise BriefError(f"invalid JSON spec: {error.msg}") from error
    if not isinstance(value, dict):
        raise BriefError("spec must contain a JSON object")
    return value


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a visual question and produce a chart plan"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", type=Path, help="Path to a visual question JSON spec")
    source.add_argument("--example", action="store_true", help="Use the built-in phase example")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON brief")
    args = parser.parse_args(argv)
    try:
        spec = deepcopy(EXAMPLE_SPEC) if args.example else load_spec(args.spec)
        report = build_brief(spec)
    except BriefError as error:
        sys.stdout.write(render_json({"error": str(error)}))
        return 2
    content = render_json(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    sys.stdout.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
