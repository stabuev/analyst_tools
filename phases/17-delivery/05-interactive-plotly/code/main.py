from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "plotly_interactive_appendix.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("plotly_interactive_appendix", ARTIFACT)
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
        sample = builder.write_sample_delivery_package(root / "sample")
        result = builder.build_interactive_appendix(
            delivery_dir=sample["delivery_dir"],
            interactive_spec_path=sample["interactive_spec_path"],
            output_dir=root / "interactive-appendix",
        )
        files = [
            "interactive_spec.json",
            "interactive_appendix.html",
            "plotly_figure_spec.json",
            "static-fallbacks/metric_status.svg",
            "source_table_links.csv",
            "interaction_audit.json",
            "interaction_manifest.json",
        ]
        summary = {
            "valid": result.audit["valid"],
            "readiness_status": result.audit["readiness_status"],
            "blocking_errors": result.audit["summary"]["blocking_errors"],
            "redacted_fields": result.audit["redaction_summary"]["redacted_fields"],
            "renderer_used": builder.read_json(result.manifest_path)["renderer_used"],
            "files": files,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
