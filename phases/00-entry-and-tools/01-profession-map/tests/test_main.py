from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import TestCase


def load_advisor():
    path = Path(__file__).resolve().parents[1] / "outputs" / "route_advisor.py"
    spec = importlib.util.spec_from_file_location("route_advisor_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load route advisor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RouteAdvisorTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.advisor = load_advisor()

    def test_data_answers_recommend_analytics_engineer(self) -> None:
        result = self.advisor.build_recommendation(["data"] * 5)
        self.assertEqual(result["recommended"], "Analytics Engineer")
        self.assertEqual(result["scores"]["Analytics Engineer"], 5)

    def test_forecast_answers_recommend_time_series_route(self) -> None:
        result = self.advisor.build_recommendation(["forecast"] * 5)
        self.assertEqual(result["recommended"], "Аналитик временных рядов")
        self.assertEqual(result["path"], "00-09 -> 14 -> 17 -> 18")

    def test_tie_is_visible(self) -> None:
        result = self.advisor.build_recommendation(
            ["product", "data", "product", "data", "basic"]
        )
        self.assertEqual(
            result["tied_routes"],
            ["Продуктовый аналитик", "Analytics Engineer"],
        )

    def test_invalid_answer_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown answer"):
            self.advisor.build_recommendation(
                ["product", "data", "unknown", "ml", "basic"]
            )

    def test_answer_count_is_checked(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected 5 answers"):
            self.advisor.build_recommendation(["product"])
