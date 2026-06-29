from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "did_analyzer.py"


def load_analyzer():
    module_spec = importlib.util.spec_from_file_location("did_analyzer", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    analyzer = load_analyzer()
    paths = analyzer.default_paths()
    report = analyzer.estimate_did(
        paths["data_dir"],
        analyzer.read_json(paths["spec"]),
    )
    summary = {
        "did_valid": report["valid"],
        "panel_rows_n": report["summary"]["panel_rows_n"],
        "treated_region": report["summary"]["treated_region"],
        "control_region": report["summary"]["control_region"],
        "treated_change": round(report["summary"]["treated_change"], 6),
        "control_change": round(report["summary"]["control_change"], 6),
        "did_estimate": round(report["summary"]["did_estimate"], 6),
        "twfe_coefficient": round(report["summary"]["twfe_coefficient"], 6),
        "fake_pre_placebo_did": round(report["summary"]["fake_pre_placebo_did"], 6),
        "pretrend_slope_difference": round(
            report["summary"]["pretrend_slope_difference"],
            12,
        ),
        "sparse_event_times": report["summary"]["sparse_event_times"],
        "effect_claim_allowed": report["summary"]["allowed_effect_claim"],
        "warning_checks": report["summary"]["warning_checks"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
