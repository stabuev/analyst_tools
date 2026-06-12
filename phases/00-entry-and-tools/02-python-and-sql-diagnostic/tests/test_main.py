from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]


def load_runner():
    path = LESSON_ROOT / "outputs" / "diagnostic_runner.py"
    spec = importlib.util.spec_from_file_location("diagnostic_runner_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load diagnostic runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DiagnosticRunnerTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_runner()

    def test_reference_submission_passes_all_checks(self) -> None:
        report = self.runner.evaluate_submission(LESSON_ROOT / "code" / "main.py")
        self.assertEqual(report["score"], 4)
        self.assertEqual(report["recommended_topics"], [])

    def test_missing_answers_become_targeted_recommendations(self) -> None:
        with TemporaryDirectory() as directory:
            submission = Path(directory) / "partial.py"
            submission.write_text(
                "def select_paid_order_ids(orders):\n"
                "    return [row['order_id'] for row in orders "
                "if row['status'] == 'paid']\n",
                encoding="utf-8",
            )
            report = self.runner.evaluate_submission(submission)
        self.assertEqual(report["score"], 1)
        self.assertEqual(len(report["recommended_topics"]), 3)
        self.assertIn("GROUP BY", " ".join(report["recommended_topics"]))

    def test_mutating_input_fails_python_check(self) -> None:
        with TemporaryDirectory() as directory:
            submission = Path(directory) / "mutating.py"
            submission.write_text(
                "def select_paid_order_ids(orders):\n"
                "    orders.pop()\n"
                "    return [101, 103, 104, 105]\n",
                encoding="utf-8",
            )
            report = self.runner.evaluate_submission(submission)
        first_check = report["checks"][0]
        self.assertFalse(first_check["passed"])
        self.assertIn("изменила входные строки", first_check["message"])

    def test_inner_join_does_not_pass_activity_check(self) -> None:
        with TemporaryDirectory() as directory:
            submission = Path(directory) / "inner_join.py"
            submission.write_text(
                "CUSTOMER_ACTIVITY_SQL = '''\n"
                "SELECT c.customer_id, COUNT(o.order_id), SUM(o.amount)\n"
                "FROM customers c JOIN orders o ON c.customer_id = o.customer_id\n"
                "WHERE o.status = 'paid' AND o.amount IS NOT NULL\n"
                "GROUP BY c.customer_id ORDER BY c.customer_id\n"
                "'''\n",
                encoding="utf-8",
            )
            report = self.runner.evaluate_submission(submission)
        join_check = next(
            check for check in report["checks"] if check["skill"] == "sql-joins"
        )
        self.assertFalse(join_check["passed"])
        self.assertIn("(3, 0, 0)", join_check["message"])

    def test_markdown_report_contains_score_and_skills(self) -> None:
        report = self.runner.evaluate_submission(LESSON_ROOT / "code" / "main.py")
        markdown = self.runner.render_markdown(report)
        self.assertIn("**Результат:** 4 из 4", markdown)
        self.assertIn("SQL: LEFT JOIN", markdown)
