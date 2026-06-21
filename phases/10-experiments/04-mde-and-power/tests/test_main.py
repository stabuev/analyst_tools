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
ARTIFACT = ROOT / "outputs" / "power_planner.py"
POWER_SPEC = ROOT / "outputs" / "power_spec.json"
POWER_PLAN = ROOT / "outputs" / "power_plan.json"
MDE_GRID = ROOT / "outputs" / "mde_grid.csv"
POWER_CURVE = ROOT / "outputs" / "power_curve.png"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
HEALTH = PHASE_ROOT / "03-aa-and-srm" / "outputs" / "randomization_health_report.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("power_planner", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PLANNER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(PLANNER)


def load_examples() -> tuple[dict, list[dict[str, str]], dict, dict]:
    protocol = PLANNER.read_json(PROTOCOL)
    baselines = PLANNER.read_csv(DATA / "metric_baselines.csv")
    health = PLANNER.read_json(HEALTH)
    power_spec = PLANNER.read_json(POWER_SPEC)
    return protocol, baselines, health, power_spec


def metric_plan(plan: dict, metric_id: str) -> dict:
    return next(row for row in plan["metric_plans"] if row["metric_id"] == metric_id)


class PowerPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol, self.baselines, self.health, self.power_spec = load_examples()

    def build(self, health: dict | None = None) -> tuple[dict, list[dict]]:
        return PLANNER.build_plan(self.protocol, self.baselines, self.health if health is None else health, self.power_spec)

    def test_committed_power_plan_matches_calculated_output(self) -> None:
        plan, grid = self.build()
        committed = json.loads(POWER_PLAN.read_text(encoding="utf-8"))
        self.assertEqual(plan, committed)
        self.assertTrue(plan["valid"])
        self.assertEqual(len(grid), 5)
        self.assertEqual(plan["summary"]["metric_statuses"]["activation_rate_7d"], "ready")

    def test_primary_proportion_sizing_matches_protocol_mde(self) -> None:
        plan, _ = self.build()
        primary = metric_plan(plan, "activation_rate_7d")
        self.assertEqual(primary["baseline"], 0.3)
        self.assertEqual(primary["mde_absolute"], 0.03)
        self.assertEqual(primary["mde_relative"], 0.1)
        self.assertEqual(primary["required_n_control"], 2964)
        self.assertEqual(primary["required_n_treatment"], 2964)
        self.assertEqual(primary["runtime_days_unconstrained"], 4)
        self.assertEqual(primary["recommended_runtime_days"], 14)
        self.assertEqual(primary["planned_power"], 0.999609)
        self.assertEqual(primary["simulation_power"], 0.79615)

    def test_mean_metric_uses_standard_deviation_and_ttest_power(self) -> None:
        plan, _ = self.build()
        revenue = metric_plan(plan, "realized_revenue_per_user_7d")
        self.assertEqual(revenue["metric_type"], "mean")
        self.assertEqual(revenue["baseline"], 42.5)
        self.assertEqual(revenue["baseline_standard_deviation"], 120.0)
        self.assertEqual(revenue["mde_absolute"], 5.0)
        self.assertEqual(revenue["required_n_control"], 7123)
        self.assertEqual(revenue["planned_power"], 0.943237)
        self.assertEqual(revenue["simulation_power"], 0.804333)

    def test_mde_grid_is_monotonic_and_matches_committed_csv(self) -> None:
        _, grid = self.build()
        with MDE_GRID.open(encoding="utf-8", newline="") as source:
            committed_rows = list(csv.DictReader(source))
        self.assertEqual([str(row["required_n_control"]) for row in grid], [row["required_n_control"] for row in committed_rows])
        required = [row["required_n_control"] for row in grid]
        self.assertEqual(required, sorted(required, reverse=True))
        self.assertEqual(required, [26210, 6611, 2964, 1681, 1084])
        self.assertEqual(grid[0]["planned_power"], 0.515002)
        self.assertEqual(grid[-1]["planned_power"], 1.0)

    def test_upstream_health_gate_blocks_sizing(self) -> None:
        health = json.loads(json.dumps(self.health))
        health["ready_for_ab_analysis"] = False
        health["summary"]["blocking_failures"] = ["telemetry_loss_by_variant"]
        plan, grid = self.build(health=health)
        self.assertFalse(plan["valid"])
        self.assertFalse(plan["ready_for_sizing"])
        self.assertEqual(grid, [])
        self.assertIn("upstream_randomization_health_not_ready", plan["summary"]["blocking_failures"])
        self.assertEqual(plan["metric_plans"], [])

    def test_low_planned_sample_marks_metric_underpowered(self) -> None:
        protocol = json.loads(json.dumps(self.protocol))
        protocol["sample_size_plan"]["planned_units_per_variant"] = 500
        plan, _ = PLANNER.build_plan(protocol, self.baselines, self.health, self.power_spec)
        self.assertFalse(plan["valid"])
        self.assertEqual(metric_plan(plan, "activation_rate_7d")["status"], "underpowered")
        self.assertFalse(next(check for check in plan["checks"] if check["id"] == "planned_sample_meets_target_power")["valid"])

    def test_code_example_prints_sizing_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["primary_required_n_per_variant"], 2964)
        self.assertEqual(payload["revenue_required_n_per_variant"], 7123)
        self.assertEqual(payload["recommended_runtime_days"], 14)
        self.assertEqual(payload["grid_rows"], 5)

    def test_cli_writes_plan_grid_and_png(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "power_plan.json"
            grid_path = root / "mde_grid.csv"
            figure_path = root / "power_curve.png"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    PROTOCOL,
                    "--metric-baselines",
                    DATA / "metric_baselines.csv",
                    "--health-report",
                    HEALTH,
                    "--power-spec",
                    POWER_SPEC,
                    "--output-plan",
                    plan_path,
                    "--output-grid",
                    grid_path,
                    "--output-figure",
                    figure_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(plan_path.read_text(encoding="utf-8")))
            with grid_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 5)
            self.assertEqual(figure_path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_cli_returns_nonzero_when_health_gate_blocks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            health = json.loads(json.dumps(self.health))
            health["ready_for_ab_analysis"] = False
            health["summary"]["blocking_failures"] = ["assignment_srm_chi_square"]
            health_path = root / "bad_health.json"
            PLANNER.write_json(health_path, health)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    PROTOCOL,
                    "--metric-baselines",
                    DATA / "metric_baselines.csv",
                    "--health-report",
                    health_path,
                    "--power-spec",
                    POWER_SPEC,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
