from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "streamlit_cache_state_auditor.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("streamlit_cache_state_auditor", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_builder()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        sample = builder.write_sample_cache_state_inputs(root / "sample")
        result = builder.build_cache_state_package(
            app_dir=sample["app_dir"],
            cache_state_contract_path=sample["cache_state_contract_path"],
            freshness_policy_path=sample["freshness_policy_path"],
            output_dir=root / "cache-state-app",
        )
        manifest = builder.read_json(result.manifest_path)
        freshness = builder.read_json(result.freshness_report_path)
        files = [
            "streamlit_app.py",
            "cache_state_contract.json",
            "freshness_policy.json",
            "freshness_report.json",
            "cache_state_audit.json",
            "cache_state_manifest.json",
            "cache_state_runbook.md",
            "app_contract.json",
            "app_data/metric_summary.csv",
            "app_data/claim_evidence_matrix.csv",
            "app_data/plotly_figure_spec.json",
            "downloads/stakeholder_app_bundle.zip",
        ]
        summary = {
            "valid": result.audit["valid"],
            "readiness_status": result.audit["readiness_status"],
            "blocking_errors": result.audit["summary"]["blocking_errors"],
            "input_digest": freshness["input_digest"],
            "input_age_seconds": freshness["input_age_seconds"],
            "stale": freshness["stale"],
            "renderer_used": manifest["renderer_used"],
            "streamlit_version": manifest["streamlit_version"],
            "files": files,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
