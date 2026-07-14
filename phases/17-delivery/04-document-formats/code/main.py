from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "multi_format_report_renderer.py"


def load_renderer():
    spec = importlib.util.spec_from_file_location("multi_format_report_renderer", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    renderer = load_renderer()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        sample = renderer.write_sample_report_package(root / "sample")
        result = renderer.build_multi_format_report(
            report_dir=sample["report_dir"],
            format_spec_path=sample["format_spec_path"],
            output_dir=root / "multi-format-report",
        )
        files = [
            "report.html",
            "report.pdf",
            "report.docx",
            "format_targets.json",
            "asset_inventory.csv",
            "link_audit.csv",
            "format_qa_report.json",
            "format_manifest.json",
        ]
        summary = {
            "valid": result.qa_report["valid"],
            "readiness_status": result.qa_report["readiness_status"],
            "blocking_errors": result.qa_report["summary"]["blocking_errors"],
            "warnings": result.qa_report["summary"]["warnings"],
            "renderer_used": renderer.read_json(result.manifest_path)["renderer_used"],
            "files": files,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
