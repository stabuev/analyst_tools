from __future__ import annotations

import json


def main() -> None:
    brief = {
        "question": "Изменилась ли семидневная активация после релиза?",
        "decision": "Решить, какой сегмент требует отдельной диагностики.",
        "grain": "Один пользователь с полным семидневным окном.",
        "metric": "Доля activated_7d среди observed_days=7.",
        "comparison": "Cohort week до и после 2026-03-02, затем platform и channel.",
        "expected_pattern": "Общий спад может сочетать channel mix и Android regression.",
        "stop_rule": "Не интерпретировать график, пока неполные окна и дубликаты не исключены.",
    }
    required = (
        "question",
        "decision",
        "grain",
        "metric",
        "comparison",
        "expected_pattern",
        "stop_rule",
    )
    report = {
        "ready": all(str(brief[field]).strip() for field in required),
        "brief": brief,
        "missing": [field for field in required if not str(brief[field]).strip()],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
