from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
DATA = PHASE / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "estimator_runner.py"
SPEC = ROOT / "outputs" / "estimator_spec.json"
SAMPLING_AUDIT = ROOT / "outputs" / "upstream_sampling_audit.json"
DISTRIBUTION_CARDS = PHASE / "02-distributions" / "outputs" / "distribution_cards.json"


def load_runner():
    module_spec = importlib.util.spec_from_file_location("estimator_runner", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    runner = load_runner()
    report = runner.run(DATA / "sample_observations.csv", SPEC, SAMPLING_AUDIT, DISTRIBUTION_CARDS)
    estimates = {estimate["estimator_id"]: estimate["estimate"] for estimate in report["estimates"]}
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "respondent_rows": report["summary"]["respondent_rows"],
                "estimates": estimates,
                "warning_count": report["summary"]["warning_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
