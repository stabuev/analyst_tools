from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "delivery_cli_runner.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("delivery_cli_runner", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    runner = load_runner()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        sample = runner.write_sample_cli_inputs(root / "sample")
        check_result = runner.run_delivery_cli(
            app_dir=sample["app_dir"],
            cache_state_contract_path=sample["cache_state_contract_path"],
            freshness_policy_path=sample["freshness_policy_path"],
            cli_contract_path=sample["cli_contract_path"],
            output_dir=root / "published-delivery",
            check_mode=True,
            argv=["--check"],
        )
        publish_result = runner.run_delivery_cli(
            app_dir=sample["app_dir"],
            cache_state_contract_path=sample["cache_state_contract_path"],
            freshness_policy_path=sample["freshness_policy_path"],
            cli_contract_path=sample["cli_contract_path"],
            output_dir=root / "published-delivery",
            argv=["--publish"],
        )
        manifest = runner.read_json(publish_result.manifest_path)
        report = runner.read_json(publish_result.report_path)
        summary = {
            "check_status": check_result.status,
            "check_published": check_result.published,
            "publish_status": publish_result.status,
            "publish_exit_code": publish_result.exit_code,
            "publish_published": publish_result.published,
            "renderer_used": manifest["renderer_used"],
            "atomic_strategy": manifest["atomic_publish"]["strategy"],
            "run_report_checks": report["summary"]["check_count"],
            "required_files": [
                "cli_run_report.json",
                "cli_publish_manifest.json",
                "delivery_cli_contract.json",
                "cache_state_manifest.json",
                "freshness_report.json",
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
