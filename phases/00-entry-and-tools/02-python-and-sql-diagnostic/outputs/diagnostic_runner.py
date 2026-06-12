from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import ModuleType
from typing import Any


ORDERS = [
    {"order_id": 101, "customer_id": 1, "status": "paid", "amount": 10.0},
    {"order_id": 102, "customer_id": 1, "status": "cancelled", "amount": 99.0},
    {"order_id": 103, "customer_id": 2, "status": "paid", "amount": 7.5},
    {"order_id": 104, "customer_id": 1, "status": "paid", "amount": 15.0},
    {"order_id": 105, "customer_id": 2, "status": "paid", "amount": None},
]

SKILL_LABELS = {
    "python-filtering": "Python: фильтрация и порядок строк",
    "python-aggregation": "Python: функции, словари и пропуски",
    "sql-aggregation": "SQL: фильтрация и агрегация",
    "sql-joins": "SQL: LEFT JOIN, grain и пустые группы",
}

TOPIC_BY_SKILL = {
    "python-filtering": "Повторить условия, списки и сохранение порядка элементов.",
    "python-aggregation": "Повторить функции, словари, накопление значений и None.",
    "sql-aggregation": "Повторить WHERE, GROUP BY, SUM, NULL и порядок выполнения SQL.",
    "sql-joins": "Повторить LEFT JOIN, условия в ON и сохранение строк без фактов.",
}


def check_result(skill: str, passed: bool, message: str) -> dict[str, object]:
    return {"skill": skill, "passed": passed, "message": message}


def load_submission(path: Path) -> ModuleType:
    if not path.is_file():
        raise FileNotFoundError(f"Submission not found: {path}")
    spec = importlib.util.spec_from_file_location("analyst_tools_submission", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load submission: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_python_function(
    module: ModuleType,
    name: str,
    skill: str,
    expected: object,
) -> dict[str, object]:
    function = getattr(module, name, None)
    if not callable(function):
        return check_result(skill, False, f"Не найдена функция {name}.")
    rows = [row.copy() for row in ORDERS]
    original = [row.copy() for row in rows]
    try:
        actual = function(rows)
    except Exception as error:
        return check_result(skill, False, f"{name} завершилась ошибкой: {error}")
    if rows != original:
        return check_result(skill, False, f"{name} изменила входные строки.")
    if actual != expected:
        return check_result(
            skill,
            False,
            f"{name} вернула {actual!r}, ожидалось {expected!r}.",
        )
    return check_result(skill, True, f"{name}: контрольный пример пройден.")


def create_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            amount REAL
        );
        """
    )
    connection.executemany(
        "INSERT INTO customers VALUES (?, ?)",
        [(1, "Ada"), (2, "Linus"), (3, "Grace")],
    )
    connection.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?)",
        [
            (
                row["order_id"],
                row["customer_id"],
                row["status"],
                row["amount"],
            )
            for row in ORDERS
        ],
    )
    return connection


def normalize_sql_rows(rows: list[sqlite3.Row]) -> list[tuple[object, ...]]:
    normalized: list[tuple[object, ...]] = []
    for row in rows:
        normalized.append(
            tuple(round(value, 2) if isinstance(value, float) else value for value in row)
        )
    return normalized


def check_sql(
    module: ModuleType,
    name: str,
    skill: str,
    expected: list[tuple[object, ...]],
) -> dict[str, object]:
    query = getattr(module, name, None)
    if not isinstance(query, str) or not query.strip():
        return check_result(skill, False, f"Не найдена SQL-строка {name}.")
    try:
        with create_database() as connection:
            actual = normalize_sql_rows(connection.execute(query).fetchall())
    except sqlite3.Error as error:
        return check_result(skill, False, f"{name} содержит ошибку SQL: {error}")
    if actual != expected:
        return check_result(
            skill,
            False,
            f"{name} вернул {actual!r}, ожидалось {expected!r}.",
        )
    return check_result(skill, True, f"{name}: контрольный пример пройден.")


def placement_for(score: int, total: int) -> str:
    if score == total:
        return "База Python и SQL подтверждена. Продолжайте фазу 00."
    if score >= total - 1:
        return "Продолжайте курс и закройте один точечный пробел до фазы 02."
    return "Сначала повторите отмеченные темы и пройдите диагностику еще раз."


def evaluate_submission(path: Path) -> dict[str, Any]:
    module = load_submission(path)
    checks = [
        check_python_function(
            module,
            "select_paid_order_ids",
            "python-filtering",
            [101, 103, 104, 105],
        ),
        check_python_function(
            module,
            "revenue_by_customer",
            "python-aggregation",
            {1: 25.0, 2: 7.5},
        ),
        check_sql(
            module,
            "CUSTOMER_REVENUE_SQL",
            "sql-aggregation",
            [(1, 25.0), (2, 7.5)],
        ),
        check_sql(
            module,
            "CUSTOMER_ACTIVITY_SQL",
            "sql-joins",
            [(1, 2, 25.0), (2, 1, 7.5), (3, 0, 0)],
        ),
    ]
    score = sum(bool(check["passed"]) for check in checks)
    failed_skills = [
        str(check["skill"]) for check in checks if not check["passed"]
    ]
    return {
        "submission": str(path),
        "score": score,
        "total": len(checks),
        "placement": placement_for(score, len(checks)),
        "checks": checks,
        "recommended_topics": [TOPIC_BY_SKILL[skill] for skill in failed_skills],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Отчет диагностики Python и SQL",
        "",
        f"**Результат:** {report['score']} из {report['total']}",
        f"**Рекомендация:** {report['placement']}",
        "",
        "## Навыки",
        "",
    ]
    for check in report["checks"]:
        mark = "x" if check["passed"] else " "
        lines.append(f"- [{mark}] {SKILL_LABELS[check['skill']]}: {check['message']}")
    lines.extend(["", "## Что повторить", ""])
    topics = report["recommended_topics"]
    if topics:
        lines.extend(f"- {topic}" for topic in topics)
    else:
        lines.append("- Точечных пробелов на контрольном наборе не найдено.")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the Python and SQL entry diagnostic"
    )
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = evaluate_submission(args.submission)
    text = (
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Отчет сохранен: {args.output}")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
