from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
ARTIFACT = ROOT / "outputs" / "robust_evidence_packager.py"


def load_packager():
    module_spec = importlib.util.spec_from_file_location("robust_evidence_packager", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    packager = load_packager()
    with TemporaryDirectory() as directory:
        report = packager.build_package(PHASE, Path(directory) / "statistical-evidence-report")
        print(
            json.dumps(
                {
                    "valid": report["valid"],
                    "files": report["summary"]["files"],
                    "robust_estimates": report["summary"]["robust_estimates"],
                    "has_manifest": "manifest.json" not in report["manifest"]["files"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
