from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "scheduled_delivery_workflow.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("scheduled_delivery_workflow", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
WORKFLOW = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = WORKFLOW
SPEC.loader.exec_module(WORKFLOW)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_sample(root: Path):
    sample = WORKFLOW.write_sample_schedule_inputs(root / "sample")
    result = WORKFLOW.run_scheduled_delivery(
        app_dir=sample["app_dir"],
        cache_state_contract_path=sample["cache_state_contract_path"],
        freshness_policy_path=sample["freshness_policy_path"],
        cli_contract_path=sample["cli_contract_path"],
        schedule_contract_path=sample["schedule_contract_path"],
        output_dir=root / "scheduled-package",
        argv=["test-success"],
    )
    return sample, result


class ScheduledDeliveryWorkflowTest(unittest.TestCase):
    def test_sample_schedule_writes_required_files_and_publishes_delivery_package(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertEqual(result.status, "success")
            self.assertEqual(result.exit_code, WORKFLOW.SCHEDULE_EXIT_CODE_POLICY["success"])
            for relative in [
                "schedule_contract.json",
                "schedule_workflow.yml",
                "run_history.csv",
                "schedule_freshness_report.json",
                "schedule_run_report.json",
                "last_success_marker.json",
                "failure_notification_mock.json",
                "scheduled_publish_manifest.json",
                "published-delivery/cli_publish_manifest.json",
                "published-delivery/freshness_report.json",
            ]:
                self.assertTrue((result.output_dir / relative).is_file(), relative)

    def test_schedule_contract_declares_cron_utc_owner_history_marker_and_notifications(self) -> None:
        contract = WORKFLOW.default_schedule_contract()

        self.assertEqual(WORKFLOW.schedule_contract_errors(contract), [])
        self.assertEqual(contract["timezone"], "UTC")
        self.assertEqual(contract["cron"], "17 6 * * 1")
        self.assertTrue(contract["github_actions_constraints"]["default_branch_required"])
        self.assertTrue(contract["github_actions_constraints"]["workflow_dispatch_enabled"])
        self.assertTrue(contract["run_policy"]["write_run_history"])
        self.assertTrue(contract["run_policy"]["write_last_success_marker"])
        self.assertTrue(contract["run_policy"]["write_failure_notification_mock"])

    def test_generated_workflow_uses_schedule_manual_dispatch_and_explicit_cli_args(self) -> None:
        workflow_text = WORKFLOW.build_github_actions_workflow(WORKFLOW.default_schedule_contract())

        self.assertEqual(WORKFLOW.workflow_marker_errors(workflow_text), [])
        self.assertIn('cron: "17 6 * * 1"', workflow_text)
        self.assertIn("workflow_dispatch:", workflow_text)
        self.assertIn("--cache-state-contract", workflow_text)
        self.assertIn("--freshness-policy", workflow_text)
        self.assertIn("--cli-contract", workflow_text)

    def test_run_history_records_cli_status_exit_code_freshness_and_report_paths(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            rows = WORKFLOW.read_history_rows(result.history_path)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "success")
            self.assertEqual(rows[0]["exit_code"], "0")
            self.assertEqual(rows[0]["published"], "true")
            self.assertEqual(rows[0]["freshness_state"], "fresh")
            self.assertIn("cli_run_report.json", rows[0]["cli_report_path"])
            self.assertIn("cli_publish_manifest.json", rows[0]["cli_manifest_path"])

    def test_last_success_marker_updates_only_on_fresh_success(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, first = build_sample(root)
            first_marker = read_json(first.last_success_marker_path)
            sentinel = first.published_delivery_dir / "sentinel.txt"
            sentinel.write_text("keep previous package", encoding="utf-8")
            app_audit_path = sample["app_dir"] / "app_audit.json"
            app_audit = read_json(app_audit_path)
            app_audit["valid"] = False
            app_audit["summary"]["blocking_errors"] = ["app_contract_tampered_for_schedule"]
            write_json(app_audit_path, app_audit)

            second = WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=sample["schedule_contract_path"],
                output_dir=first.output_dir,
                run_id="scheduled-2026-01-12T06-17-00Z",
                scheduled_for_utc="2026-01-12T06:17:00Z",
                started_at_utc="2026-01-12T06:18:10Z",
                finished_at_utc="2026-01-12T06:18:40Z",
                argv=["test-failed-second-run"],
            )
            second_marker = read_json(first.last_success_marker_path)
            rows = WORKFLOW.read_history_rows(second.history_path)

            self.assertEqual(second.status, "data_quality_block")
            self.assertEqual(second_marker, first_marker)
            self.assertTrue(sentinel.is_file())
            self.assertEqual(rows[-1]["notification_sent"], "true")
            self.assertEqual(rows[-1]["last_success_utc"], first_marker["last_success_utc"])

    def test_stale_run_without_allow_freshness_warning_notifies_and_does_not_publish(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = WORKFLOW.write_sample_schedule_inputs(root / "sample")
            result = WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=sample["schedule_contract_path"],
                output_dir=root / "scheduled-package",
                checked_at_utc="2026-01-05T08:30:00Z",
                argv=["test-stale"],
            )
            notification = read_json(result.notification_path)
            freshness = read_json(result.freshness_report_path)

            self.assertEqual(result.status, "freshness_warning")
            self.assertEqual(result.exit_code, WORKFLOW.SCHEDULE_EXIT_CODE_POLICY["freshness_warning"])
            self.assertFalse((result.output_dir / "published-delivery" / "cli_publish_manifest.json").exists())
            self.assertIsNone(result.last_success_marker_path)
            self.assertTrue(notification["should_notify"])
            self.assertEqual(notification["severity"], "warning")
            self.assertEqual(freshness["freshness_state"], "stale")

    def test_stale_run_can_publish_with_warning_but_does_not_update_last_success(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = WORKFLOW.write_sample_schedule_inputs(root / "sample")
            result = WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=sample["schedule_contract_path"],
                output_dir=root / "scheduled-package",
                checked_at_utc="2026-01-05T08:30:00Z",
                allow_freshness_warning=True,
                argv=["test-stale-allowed"],
            )
            delivery_freshness = read_json(result.published_delivery_dir / "freshness_report.json")

            self.assertEqual(result.status, "freshness_warning")
            self.assertTrue((result.published_delivery_dir / "cli_publish_manifest.json").is_file())
            self.assertTrue(delivery_freshness["stale"])
            self.assertIsNone(result.last_success_marker_path)

    def test_data_quality_block_keeps_previous_published_output_and_marker(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, first = build_sample(root)
            previous_manifest = read_json(first.published_delivery_dir / "cli_publish_manifest.json")
            app_audit_path = sample["app_dir"] / "app_audit.json"
            app_audit = read_json(app_audit_path)
            app_audit["valid"] = False
            app_audit["summary"]["blocking_errors"] = ["scheduled_quality_gate_failed"]
            write_json(app_audit_path, app_audit)

            second = WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=sample["schedule_contract_path"],
                output_dir=first.output_dir,
                argv=["quality-block"],
            )
            current_manifest = read_json(first.published_delivery_dir / "cli_publish_manifest.json")
            notification = read_json(second.notification_path)

            self.assertEqual(second.status, "data_quality_block")
            self.assertEqual(current_manifest, previous_manifest)
            self.assertTrue(notification["should_notify"])
            self.assertIn("upstream_app_audit_is_valid", notification["reason_codes"])

    def test_invalid_schedule_contract_blocks_before_cli_and_writes_notification(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = WORKFLOW.write_sample_schedule_inputs(root / "sample")
            contract = WORKFLOW.default_schedule_contract()
            contract["timezone"] = "Europe/Moscow"
            contract["run_policy"]["write_run_history"] = False
            bad_contract_path = root / "bad_schedule_contract.json"
            write_json(bad_contract_path, contract)

            result = WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=bad_contract_path,
                output_dir=root / "scheduled-package",
                argv=["bad-contract"],
            )
            report = read_json(result.run_report_path)
            notification = read_json(result.notification_path)

            self.assertEqual(result.status, "schedule_contract_block")
            self.assertEqual(result.exit_code, WORKFLOW.SCHEDULE_EXIT_CODE_POLICY["schedule_contract_block"])
            self.assertFalse(result.published_delivery_dir.exists())
            self.assertIn("schedule_timezone_must_be_utc", report["summary"]["schedule_contract_errors"])
            self.assertTrue(notification["should_notify"])

    def test_cron_minimum_interval_and_top_of_hour_are_checked(self) -> None:
        every_minute = WORKFLOW.default_schedule_contract()
        every_minute["cron"] = "*/1 * * * *"
        top_of_hour = WORKFLOW.default_schedule_contract()
        top_of_hour["cron"] = "0 6 * * 1"

        self.assertEqual(WORKFLOW.cron_minimum_interval_minutes("*/5 * * * *"), 5)
        self.assertIn("cron_minimum_interval_must_be_at_least_five_minutes", WORKFLOW.schedule_contract_errors(every_minute))
        self.assertIn("cron_should_avoid_top_of_hour", WORKFLOW.schedule_contract_errors(top_of_hour))

    def test_source_inputs_are_not_mutated_by_scheduled_run(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = WORKFLOW.write_sample_schedule_inputs(root / "sample")
            before = WORKFLOW.hash_tree(sample["app_dir"])

            WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=sample["schedule_contract_path"],
                output_dir=root / "scheduled-package",
                argv=["source-mutation-check"],
            )
            after = WORKFLOW.hash_tree(sample["app_dir"])

            self.assertEqual(after, before)

    def test_manifest_hashes_inputs_outputs_and_workflow(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            self.assertEqual(manifest["renderer_used"], "scheduled_delivery_workflow")
            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(len(manifest["outputs"]["schedule_workflow_yml"]["sha256"]), 64)
            self.assertEqual(len(manifest["outputs"]["schedule_run_report_json"]["sha256"]), 64)
            self.assertEqual(len(manifest["outputs"]["run_history_csv"]["sha256"]), 64)
            self.assertIn("delivery_cli_contract", manifest["inputs"])

    def test_freshness_report_marks_last_success_overdue(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, first = build_sample(root)
            app_audit_path = sample["app_dir"] / "app_audit.json"
            app_audit = read_json(app_audit_path)
            app_audit["valid"] = False
            app_audit["summary"]["blocking_errors"] = ["late_failure"]
            write_json(app_audit_path, app_audit)

            second = WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=sample["schedule_contract_path"],
                output_dir=first.output_dir,
                run_id="scheduled-2026-01-19T06-17-00Z",
                scheduled_for_utc="2026-01-19T06:17:00Z",
                started_at_utc="2026-01-19T06:18:10Z",
                finished_at_utc="2026-01-19T06:18:40Z",
                argv=["late-failure"],
            )
            freshness = read_json(second.freshness_report_path)

            self.assertTrue(freshness["last_success_marker_present"])
            self.assertTrue(freshness["last_success_overdue"])
            self.assertGreater(freshness["last_success_age_seconds"], freshness["last_success_max_age_seconds"])

    def test_check_mode_validates_without_publishing_delivery_or_marker(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = WORKFLOW.write_sample_schedule_inputs(root / "sample")
            result = WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=sample["schedule_contract_path"],
                output_dir=root / "scheduled-package",
                check_mode=True,
                argv=["--check"],
            )
            report = read_json(result.run_report_path)

            self.assertEqual(result.status, "success")
            self.assertFalse(result.published_delivery_dir.exists())
            self.assertIsNone(result.last_success_marker_path)
            self.assertTrue(all(item["valid"] for item in report["checks"]))

    def test_notification_payload_names_owner_reason_and_run_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = WORKFLOW.write_sample_schedule_inputs(root / "sample")
            result = WORKFLOW.run_scheduled_delivery(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                schedule_contract_path=sample["schedule_contract_path"],
                output_dir=root / "scheduled-package",
                checked_at_utc="2026-01-05T08:30:00Z",
                argv=["notify-stale"],
            )
            notification = read_json(result.notification_path)

            self.assertEqual(notification["recipient"], "support_lead")
            self.assertEqual(notification["channel"], "tracker_comment_mock")
            self.assertIn("freshness_report_is_not_stale", notification["reason_codes"])
            self.assertEqual(notification["run_report_path"], str(result.run_report_path))
            self.assertIn("workflow_dispatch", notification["next_manual_action"])

    def test_cli_help_names_schedule_arguments(self) -> None:
        process = subprocess.run(
            [sys.executable, str(ARTIFACT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(process.returncode, 0)
        self.assertIn("--schedule-contract", process.stdout)
        self.assertIn("--scheduled-for", process.stdout)
        self.assertIn("--allow-freshness-warning", process.stdout)
        self.assertIn("--write-example", process.stdout)

    def test_cli_missing_app_dir_prints_json_without_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            process = subprocess.run(
                [sys.executable, str(ARTIFACT), "--output-dir", str(Path(directory) / "out")],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, WORKFLOW.SCHEDULE_EXIT_CODE_POLICY["system_error"])
            self.assertEqual(payload["status"], "system_error")
            self.assertEqual(payload["error"]["code"], "missing_app_dir")
            self.assertNotIn("Traceback", process.stderr)

    def test_cli_write_example_builds_scheduled_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "scheduled-package"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(payload["status"], "success")
            self.assertTrue((root / "scheduled-package" / "schedule_workflow.yml").is_file())
            self.assertTrue((root / "scheduled-package" / "published-delivery" / "cli_publish_manifest.json").is_file())

    def test_code_example_runs_and_reports_schedule_summary(self) -> None:
        process = subprocess.run(
            [sys.executable, str(CODE)],
            check=False,
            capture_output=True,
            text=True,
        )
        payload = json.loads(process.stdout)

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(payload["success_status"], "success")
        self.assertEqual(payload["success_exit_code"], 0)
        self.assertTrue(payload["last_success_marker_written"])
        self.assertEqual(payload["stale_status"], "freshness_warning")
        self.assertTrue(payload["stale_notification"])
        self.assertEqual(payload["workflow_renderer"], "scheduled_delivery_workflow")


if __name__ == "__main__":
    unittest.main()
