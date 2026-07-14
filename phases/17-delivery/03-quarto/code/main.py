from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "quarto_report_packager.py"


def load_packager():
    spec = importlib.util.spec_from_file_location("quarto_report_packager", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    packager = load_packager()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        paths = packager.write_sample_inputs(root / "inputs")
        result = packager.build_quarto_report(
            spec_path=paths["spec_path"],
            metrics_path=paths["metrics_path"],
            evidence_path=paths["evidence_path"],
            workbook_audit_path=paths["workbook_audit_path"],
            memo_audit_path=paths["memo_audit_path"],
            output_dir=root / "quarto-report-package",
        )
        files = [
            "_quarto.yml",
            "params.yml",
            "report.qmd",
            "report.html",
            "figures/guardrail_status.svg",
            "source_links.csv",
            "report_audit.json",
            "rebuild_check.json",
            "render_manifest.json",
        ]
        summary = {
            "valid": result.audit["valid"],
            "readiness_status": result.audit["readiness_status"],
            "blocking_errors": result.audit["summary"]["blocking_errors"],
            "quarto_cli_available": packager.read_json(result.manifest_path)["quarto_cli_available"],
            "files": files,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
