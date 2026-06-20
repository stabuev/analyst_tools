from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
DATA = PHASE / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "confidence_interval_calculator.py"
SPEC = ROOT / "outputs" / "confidence_interval_spec.json"
DISTRIBUTION_CARDS = PHASE / "02-distributions" / "outputs" / "distribution_cards.json"


def load_calculator():
    module_spec = importlib.util.spec_from_file_location("confidence_interval_calculator", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    calculator = load_calculator()
    report = calculator.run(
        DATA / "sample_observations.csv",
        DATA / "population_users.csv",
        SPEC,
        DISTRIBUTION_CARDS,
    )
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "summary": report["summary"],
                "intervals": {
                    item["interval_id"]: {
                        "status": item["status"],
                        "estimate": item["estimate"],
                        "lower": item["lower"],
                        "upper": item["upper"],
                        "coverage_rate": item["coverage_rate"],
                    }
                    for item in report["intervals"]
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
