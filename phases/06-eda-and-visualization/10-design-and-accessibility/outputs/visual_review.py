from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

PALETTE_TYPES = {"sequential", "diverging", "categorical"}

EXAMPLE_REVIEW = {
    "id": "activation-overview",
    "chart_type": "line",
    "title": "Семидневная активация снизилась после мартовского релиза",
    "purpose": "Выбрать сегмент для следующей технической диагностики.",
    "source": "user_journeys, полные семидневные окна, дубликаты удалены",
    "data_download": "control-table.csv",
    "alt_text": (
        "Линия семидневной активации по неделям регистрации снижается после 2 марта; "
        "размер каждой когорты показан в соседней панели."
    ),
    "axes": {
        "x_label": "Неделя регистрации",
        "y_label": "Доля пользователей",
        "y_domain": [0, 1],
        "baseline": 0,
    },
    "color": {
        "palette_type": "categorical",
        "palette": ["#2563eb", "#dc2626", "#059669"],
        "color_only": False,
        "redundant_channel": "facet labels and direct text",
    },
    "text": {"minimum_font_pt": 12},
    "order": "chronological",
    "estimate": True,
    "uncertainty": {
        "shown": True,
        "semantics": "95% percentile bootstrap interval by user",
        "sample_size_shown": True,
    },
}


def text(value: Any, minimum: int) -> bool:
    return isinstance(value, str) and len(value.strip()) >= minimum


def check(check_id: str, passed: bool, message: str) -> dict[str, Any]:
    return {"id": check_id, "status": "pass" if passed else "fail", "message": message}


def audit_review(review: dict[str, Any]) -> dict[str, Any]:
    axes = review.get("axes") if isinstance(review.get("axes"), dict) else {}
    color = review.get("color") if isinstance(review.get("color"), dict) else {}
    uncertainty = review.get("uncertainty") if isinstance(review.get("uncertainty"), dict) else {}
    font = review.get("text") if isinstance(review.get("text"), dict) else {}
    y_domain = axes.get("y_domain")
    baseline_ok = True
    if review.get("chart_type") == "bar":
        baseline_ok = axes.get("baseline") == 0
    rate_domain_ok = True
    if axes.get("y_label") == "Доля пользователей":
        focused_rate_domain = (
            review.get("chart_type") in {"line", "point"}
            and isinstance(y_domain, list)
            and len(y_domain) == 2
            and all(isinstance(value, (int, float)) for value in y_domain)
            and 0 <= y_domain[0] < y_domain[1] <= 1
            and axes.get("domain_policy") == "focused"
            and axes.get("full_domain_reference") is True
            and text(axes.get("scale_note"), 12)
        )
        rate_domain_ok = y_domain == [0, 1] or focused_rate_domain
    uncertainty_ok = True
    if review.get("estimate"):
        uncertainty_ok = (
            uncertainty.get("shown") is True
            and text(uncertainty.get("semantics"), 12)
            and uncertainty.get("sample_size_shown") is True
        )
    color_ok = color.get("color_only") is False and text(
        color.get("redundant_channel"),
        5,
    )
    checks = [
        check("title", text(review.get("title"), 12), "Title states a specific message."),
        check("purpose", text(review.get("purpose"), 20), "Decision purpose is explicit."),
        check("source", text(review.get("source"), 15), "Source and filters are named."),
        check(
            "data-download",
            text(review.get("data_download"), 4),
            "Underlying data has a downloadable path.",
        ),
        check(
            "alt-text",
            text(review.get("alt_text"), 40),
            "Alternative text states chart form and main pattern.",
        ),
        check(
            "axis-labels",
            text(axes.get("x_label"), 3) and text(axes.get("y_label"), 3),
            "Both axes have semantic labels.",
        ),
        check("baseline", baseline_ok, "Bar charts start from zero."),
        check(
            "rate-domain",
            rate_domain_ok,
            "Rate axis is full [0, 1] or a disclosed focused line/point scale "
            "with a full-domain reference.",
        ),
        check(
            "palette",
            color.get("palette_type") in PALETTE_TYPES
            and isinstance(color.get("palette"), list)
            and len(color["palette"]) >= 2,
            "Palette type and colors are explicit.",
        ),
        check(
            "redundant-channel",
            color_ok,
            "Color meaning is repeated by text, shape or structure.",
        ),
        check(
            "font-size",
            isinstance(font.get("minimum_font_pt"), (int, float)) and font["minimum_font_pt"] >= 12,
            "Minimum text size is at least 12 pt.",
        ),
        check(
            "order",
            text(review.get("order"), 4),
            "Category or time ordering is intentional.",
        ),
        check(
            "uncertainty",
            uncertainty_ok,
            "Estimates show interval semantics and sample size.",
        ),
    ]
    failures = [item["id"] for item in checks if item["status"] == "fail"]
    return {
        "version": "1.0.0",
        "id": review.get("id"),
        "valid": not failures,
        "checks": checks,
        "failure_ids": failures,
    }


def load_review(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read review: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("review must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit visual design and accessibility")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--review", type=Path)
    source.add_argument("--example", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        review = deepcopy(EXAMPLE_REVIEW) if args.example else load_review(args.review)
        report = audit_review(review)
    except ValueError as error:
        sys.stdout.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        return 2
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    sys.stdout.write(content)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
