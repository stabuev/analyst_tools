from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "experiment_decision_packager.py"

MODULE_SPEC = importlib.util.spec_from_file_location("experiment_decision_packager", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PACKAGER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(PACKAGER)


def main() -> None:
    with TemporaryDirectory() as directory:
        package = PACKAGER.build_package(
            PHASE_ROOT,
            ROOT / "outputs" / "decision_policy.json",
            Path(directory) / "experiment-decision-package",
        )
    summary = package["decision_summary"]
    payload = {
        "valid": package["manifest"]["valid"],
        "decision": summary["decision"],
        "launch_allowed": summary["launch_allowed"],
        "rollback_required": summary["rollback_required"],
        "primary_metric": summary["primary_metric"]["metric_id"],
        "raw_absolute_lift": summary["primary_metric"]["raw_absolute_lift"],
        "cuped_adjusted_absolute_lift": summary["primary_metric"]["cuped_adjusted_absolute_lift"],
        "reason_count": len(summary["decision_reasons"]),
        "evidence_items": package["manifest"]["evidence_items"],
        "checksum_algorithm": package["manifest"]["checksum_algorithm"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
