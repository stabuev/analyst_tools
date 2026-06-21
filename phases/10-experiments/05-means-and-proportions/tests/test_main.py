from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DATA = PHASE_ROOT / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "experiment_effect_calculator.py"
EFFECT_SPEC = ROOT / "outputs" / "effect_spec.json"
OBSERVATIONS = ROOT / "outputs" / "metric_observations.csv"
EFFECTS = ROOT / "outputs" / "effect_results.csv"
ASSUMPTIONS = ROOT / "outputs" / "assumption_checks.json"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
METRIC_SPECS = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "metric_specs.json"
HEALTH = PHASE_ROOT / "03-aa-and-srm" / "outputs" / "randomization_health_report.json"
POWER_PLAN = PHASE_ROOT / "04-mde-and-power" / "outputs" / "power_plan.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("experiment_effect_calculator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CALCULATOR)


def load_examples() -> tuple[dict, dict, dict, dict, dict, list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    return (
        CALCULATOR.read_json(PROTOCOL),
        CALCULATOR.read_json(METRIC_SPECS),
        CALCULATOR.read_json(EFFECT_SPEC),
        CALCULATOR.read_json(HEALTH),
        CALCULATOR.read_json(POWER_PLAN),
        CALCULATOR.read_csv(DATA / "users.csv"),
        CALCULATOR.read_csv(DATA / "assignments.csv"),
        CALCULATOR.read_csv(DATA / "exposures.csv"),
        CALCULATOR.read_csv(DATA / "events.csv"),
        CALCULATOR.read_csv(DATA / "orders.csv"),
        CALCULATOR.read_csv(DATA / "subscriptions.csv"),
        CALCULATOR.read_csv(DATA / "support_tickets.csv"),
    )


def effect_by_metric(rows: list[dict], metric_id: str) -> dict:
    return next(row for row in rows if row["metric_id"] == metric_id)


def observation(rows: list[dict], user_id: str, metric_id: str) -> dict:
    return next(row for row in rows if row["user_id"] == user_id and row["metric_id"] == metric_id)


class ExperimentEffectCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        (
            self.protocol,
            self.metric_specs,
            self.effect_spec,
            self.health,
            self.power_plan,
            self.users,
            self.assignments,
            self.exposures,
            self.events,
            self.orders,
            self.subscriptions,
            self.support_tickets,
        ) = load_examples()

    def build(self, health: dict | None = None) -> tuple[list[dict], list[dict], dict]:
        return CALCULATOR.build_analysis(
            self.protocol,
            self.metric_specs,
            self.effect_spec,
            self.health if health is None else health,
            self.power_plan,
            self.users,
            self.assignments,
            self.exposures,
            self.events,
            self.orders,
            self.subscriptions,
            self.support_tickets,
        )

    def test_committed_outputs_match_calculated_analysis(self) -> None:
        observations, effects, assumptions = self.build()
        with OBSERVATIONS.open(encoding="utf-8", newline="") as source:
            committed_observations = list(csv.DictReader(source))
        with EFFECTS.open(encoding="utf-8", newline="") as source:
            committed_effects = list(csv.DictReader(source))
        committed_assumptions = json.loads(ASSUMPTIONS.read_text(encoding="utf-8"))
        self.assertEqual(len(observations), len(committed_observations))
        self.assertEqual([row["metric_id"] for row in effects], [row["metric_id"] for row in committed_effects])
        self.assertEqual(assumptions, committed_assumptions)
        self.assertTrue(assumptions["valid"])
        self.assertFalse(assumptions["ready_for_decision"])

    def test_metric_observations_use_exposure_window_and_user_level_grain(self) -> None:
        observations, _, _ = self.build()
        self.assertEqual(len(observations), 30)
        self.assertEqual(observation(observations, "U001", "activation_rate_7d")["value"], 1.0)
        self.assertEqual(observation(observations, "U002", "activation_rate_7d")["value"], 0.0)
        self.assertEqual(observation(observations, "U002", "realized_revenue_per_user_7d")["value"], 249.0)
        self.assertIsNone(observation(observations, "U001", "refund_rate_7d")["value"])
        refund_control = observation(observations, "U003", "refund_rate_7d")
        self.assertEqual(refund_control["numerator"], 1.0)
        self.assertEqual(refund_control["denominator"], 1.0)
        cancellation_without_subscription = observation(observations, "U004", "subscription_cancel_rate_14d")
        self.assertEqual(cancellation_without_subscription["denominator"], 0.0)
        self.assertIsNone(cancellation_without_subscription["value"])

    def test_primary_metric_effect_is_not_a_launch_signal(self) -> None:
        _, effects, assumptions = self.build()
        primary = effect_by_metric(effects, "activation_rate_7d")
        self.assertEqual(primary["role"], "primary")
        self.assertEqual(primary["metric_type"], "proportion")
        self.assertEqual(primary["control_value"], 0.666667)
        self.assertEqual(primary["treatment_value"], 0.0)
        self.assertEqual(primary["absolute_lift"], -0.666667)
        self.assertEqual(primary["relative_lift"], -1.0)
        self.assertEqual(primary["p_value"], 0.931981)
        self.assertEqual(primary["practical_status"], "missed_primary_direction")
        self.assertEqual(primary["decision_status"], "not_launch_ready")
        self.assertIn("missed_primary_direction", assumptions["summary"]["decision_blockers"])

    def test_secondary_metrics_cannot_replace_the_primary_gate(self) -> None:
        _, effects, _ = self.build()
        trial = effect_by_metric(effects, "paywall_to_trial_conversion_7d")
        revenue = effect_by_metric(effects, "realized_revenue_per_user_7d")
        self.assertEqual(trial["absolute_lift"], 1.0)
        self.assertEqual(trial["relative_lift"], "inf")
        self.assertEqual(trial["p_value"], 0.012674)
        self.assertTrue(trial["statistically_significant"])
        self.assertEqual(trial["decision_role"], "diagnostic_only")
        self.assertEqual(trial["decision_status"], "diagnostic_only")
        self.assertEqual(revenue["method"], "welch_ttest")
        self.assertEqual(revenue["control_value"], 0.0)
        self.assertEqual(revenue["treatment_value"], 199.0)
        self.assertEqual(revenue["absolute_lift"], 199.0)
        self.assertEqual(revenue["p_value"], 0.078355)
        self.assertEqual(revenue["practical_status"], "secondary_positive_but_uncertain")

    def test_guardrails_are_watch_when_harm_is_not_ruled_out(self) -> None:
        _, effects, assumptions = self.build()
        support = effect_by_metric(effects, "support_ticket_rate_7d")
        cancellation = effect_by_metric(effects, "subscription_cancel_rate_14d")
        refund = effect_by_metric(effects, "refund_rate_7d")
        self.assertEqual(support["absolute_lift"], -0.666667)
        self.assertEqual(support["ci_high"], 0.1353)
        self.assertEqual(support["guardrail_status"], "watch")
        self.assertEqual(cancellation["guardrail_status"], "watch")
        self.assertEqual(refund["metric_type"], "ratio")
        self.assertEqual(refund["guardrail_status"], "watch")
        self.assertEqual(
            assumptions["summary"]["guardrail_statuses"],
            {
                "support_ticket_rate_7d": "watch",
                "subscription_cancel_rate_14d": "watch",
                "refund_rate_7d": "watch",
            },
        )

    def test_assumption_report_preserves_power_and_small_sample_warnings(self) -> None:
        _, _, assumptions = self.build()
        warnings = assumptions["summary"]["warning_checks"]
        self.assertIn("activation_rate_7d:observed_sample_meets_power_plan", warnings)
        self.assertIn("activation_rate_7d:normal_approximation_cell_counts", warnings)
        self.assertIn("realized_revenue_per_user_7d:observed_sample_meets_power_plan", warnings)
        self.assertIn("realized_revenue_per_user_7d:mean_variance_positive", warnings)
        self.assertIn("observed_sample_below_power_plan", assumptions["summary"]["decision_blockers"])
        self.assertEqual(assumptions["summary"]["blocking_failures"], [])

    def test_upstream_health_gate_blocks_effect_calculation(self) -> None:
        health = json.loads(json.dumps(self.health))
        health["ready_for_ab_analysis"] = False
        health["summary"]["blocking_failures"] = ["assignment_srm_chi_square"]
        observations, effects, assumptions = self.build(health=health)
        self.assertEqual(observations, [])
        self.assertEqual(effects, [])
        self.assertFalse(assumptions["valid"])
        self.assertIn("upstream_randomization_health_not_ready", assumptions["summary"]["blocking_failures"])

    def test_code_example_prints_effect_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["ready_for_decision"])
        self.assertEqual(payload["observation_rows"], 30)
        self.assertEqual(payload["primary_absolute_lift"], -0.666667)
        self.assertEqual(payload["primary_status"], "missed_primary_direction")
        self.assertEqual(payload["trial_absolute_lift"], 1.0)

    def test_cli_writes_observations_effects_and_assumptions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            observations_path = root / "metric_observations.csv"
            effects_path = root / "effect_results.csv"
            assumptions_path = root / "assumption_checks.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    PROTOCOL,
                    "--metric-specs",
                    METRIC_SPECS,
                    "--effect-spec",
                    EFFECT_SPEC,
                    "--health-report",
                    HEALTH,
                    "--power-plan",
                    POWER_PLAN,
                    "--users",
                    DATA / "users.csv",
                    "--assignments",
                    DATA / "assignments.csv",
                    "--exposures",
                    DATA / "exposures.csv",
                    "--events",
                    DATA / "events.csv",
                    "--orders",
                    DATA / "orders.csv",
                    "--subscriptions",
                    DATA / "subscriptions.csv",
                    "--support-tickets",
                    DATA / "support_tickets.csv",
                    "--output-observations",
                    observations_path,
                    "--output-effects",
                    effects_path,
                    "--output-assumptions",
                    assumptions_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(assumptions_path.read_text(encoding="utf-8")))
            with observations_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 30)
            with effects_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 6)


if __name__ == "__main__":
    unittest.main()
