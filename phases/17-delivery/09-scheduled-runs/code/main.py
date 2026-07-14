from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "scheduled_delivery_workflow.py"


def load_workflow():
    spec = importlib.util.spec_from_file_location("scheduled_delivery_workflow", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    workflow = load_workflow()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        sample = workflow.write_sample_schedule_inputs(root / "sample")
        success = workflow.run_scheduled_delivery(
            app_dir=sample["app_dir"],
            cache_state_contract_path=sample["cache_state_contract_path"],
            freshness_policy_path=sample["freshness_policy_path"],
            cli_contract_path=sample["cli_contract_path"],
            schedule_contract_path=sample["schedule_contract_path"],
            output_dir=root / "scheduled-package",
            argv=["example-success"],
        )
        stale = workflow.run_scheduled_delivery(
            app_dir=sample["app_dir"],
            cache_state_contract_path=sample["cache_state_contract_path"],
            freshness_policy_path=sample["freshness_policy_path"],
            cli_contract_path=sample["cli_contract_path"],
            schedule_contract_path=sample["schedule_contract_path"],
            output_dir=root / "stale-package",
            checked_at_utc="2026-01-05T08:30:00Z",
            run_id="scheduled-2026-01-05T08-30-00Z",
            scheduled_for_utc="2026-01-05T08:17:00Z",
            started_at_utc="2026-01-05T08:18:10Z",
            finished_at_utc="2026-01-05T08:18:40Z",
            argv=["example-stale"],
        )
        success_freshness = workflow.read_json(success.freshness_report_path)
        stale_notification = workflow.read_json(stale.notification_path)
        history_rows = workflow.read_history_rows(success.history_path)
        manifest = workflow.read_json(success.manifest_path)
        summary = {
            "success_status": success.status,
            "success_exit_code": success.exit_code,
            "success_history_rows": len(history_rows),
            "last_success_marker_written": bool(success.last_success_marker_path),
            "next_expected_run_utc": success_freshness["next_expected_run_utc"],
            "stale_status": stale.status,
            "stale_notification": stale_notification["should_notify"],
            "workflow_renderer": manifest["renderer_used"],
            "workflow_files": [
                "schedule_contract.json",
                "schedule_workflow.yml",
                "run_history.csv",
                "schedule_freshness_report.json",
                "last_success_marker.json",
                "failure_notification_mock.json",
                "scheduled_publish_manifest.json",
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
