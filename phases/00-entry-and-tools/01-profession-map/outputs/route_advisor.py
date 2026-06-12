from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Sequence


ROUTE_ORDER = (
    "Базовый аналитик",
    "Продуктовый аналитик",
    "Analytics Engineer",
    "ML-аналитик",
)

ANSWER_TO_ROUTE = {
    "basic": "Базовый аналитик",
    "product": "Продуктовый аналитик",
    "data": "Analytics Engineer",
    "ml": "ML-аналитик",
}

ROUTE_INFO = {
    "Базовый аналитик": {
        "path": "00-10 -> 17 -> 18",
        "focus": "исследования, проверенные расчеты и доставка выводов",
    },
    "Продуктовый аналитик": {
        "path": "00-10 -> 13 -> 17 -> 18",
        "focus": "метрики, эксперименты и причинные продуктовые решения",
    },
    "Analytics Engineer": {
        "path": "00-07 -> 11-12 -> 17 -> 18",
        "focus": "надежные модели данных, тесты и производительные пайплайны",
    },
    "ML-аналитик": {
        "path": "00-07 -> 09 -> 12 -> 15-18",
        "focus": "честные predictive baselines, интерпретация и доставка моделей",
    },
}

QUESTIONS = (
    "Какой результат вы чаще хотите поставлять?",
    "Какой тип ошибки вам интереснее предотвращать?",
    "Какой вопрос вы хотите получать от заказчика?",
    "Какой артефакт вы хотели бы защищать на ревью?",
    "Какой рабочий день кажется наиболее привлекательным?",
)

OPTION_LABELS = {
    "basic": "отчет, расчет или понятная рекомендация",
    "product": "метрика, эксперимент или исследование поведения",
    "data": "витрина, контракт, lineage или тест данных",
    "ml": "прогноз, pipeline или model card",
}


def score_answers(answers: Sequence[str]) -> dict[str, int]:
    if len(answers) != len(QUESTIONS):
        raise ValueError(f"Expected {len(QUESTIONS)} answers, got {len(answers)}")
    unknown = [answer for answer in answers if answer not in ANSWER_TO_ROUTE]
    if unknown:
        raise ValueError(f"Unknown answer: {unknown[0]}")
    counts = Counter(ANSWER_TO_ROUTE[answer] for answer in answers)
    return {route: counts.get(route, 0) for route in ROUTE_ORDER}


def build_recommendation(answers: Sequence[str]) -> dict[str, object]:
    scores = score_answers(answers)
    maximum = max(scores.values())
    tied_routes = [route for route in ROUTE_ORDER if scores[route] == maximum]
    recommended = tied_routes[0]
    return {
        "recommended": recommended,
        "tied_routes": tied_routes,
        "scores": scores,
        "path": ROUTE_INFO[recommended]["path"],
        "focus": ROUTE_INFO[recommended]["focus"],
    }


def format_recommendation(result: dict[str, object]) -> str:
    lines = [
        f"Рекомендованный маршрут: {result['recommended']}",
        f"Фазы: {result['path']}",
        f"Фокус: {result['focus']}",
        "Баллы:",
    ]
    scores = result["scores"]
    if not isinstance(scores, dict):
        raise TypeError("scores must be a dictionary")
    lines.extend(f"  {route}: {scores[route]}" for route in ROUTE_ORDER)
    tied_routes = result["tied_routes"]
    if isinstance(tied_routes, list) and len(tied_routes) > 1:
        lines.append("Ничья: " + ", ".join(tied_routes))
        lines.append("Выберите основной маршрут по ближайшему рабочему артефакту.")
    return "\n".join(lines)


def ask_answers() -> list[str]:
    answers: list[str] = []
    option_text = ", ".join(f"{key}={label}" for key, label in OPTION_LABELS.items())
    for question in QUESTIONS:
        print(f"\n{question}")
        print(option_text)
        answers.append(input("> ").strip().lower())
    return answers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend an Analyst Tools course route")
    parser.add_argument(
        "--answers",
        help="Five comma-separated answers: basic, product, data, or ml",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    answers = (
        [answer.strip().lower() for answer in args.answers.split(",")]
        if args.answers
        else ask_answers()
    )
    result = build_recommendation(answers)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n" + format_recommendation(result))


if __name__ == "__main__":
    main()
