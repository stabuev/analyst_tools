from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "streamlit_stakeholder_app.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("streamlit_stakeholder_app", ARTIFACT)
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
        sample = builder.write_sample_app_inputs(root / "sample")
        result = builder.build_streamlit_app(
            interactive_dir=sample["interactive_dir"],
            app_contract_path=sample["app_contract_path"],
            output_dir=root / "streamlit-app",
        )
        manifest = builder.read_json(result.manifest_path)
        files = [
            "streamlit_app.py",
            "app_contract.json",
            "app_data/metric_summary.csv",
            "app_data/claim_evidence_matrix.csv",
            "app_data/plotly_figure_spec.json",
            "app_data/static-fallbacks/metric_status.svg",
            "app_data/source_table_links.csv",
            "app_data/interaction_audit.json",
            "filters_audit.json",
            "download_manifest.json",
            "downloads/stakeholder_app_bundle.zip",
            "app_audit.json",
            "app_manifest.json",
            "app_runbook.md",
        ]
        summary = {
            "valid": result.audit["valid"],
            "readiness_status": result.audit["readiness_status"],
            "blocking_errors": result.audit["summary"]["blocking_errors"],
            "renderer_used": manifest["renderer_used"],
            "streamlit_version": manifest["streamlit_version"],
            "download_bundle": str(result.download_bundle_path),
            "files": files,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
