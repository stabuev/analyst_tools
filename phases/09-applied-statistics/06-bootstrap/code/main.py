from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
DATA = PHASE / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "bootstrap_interval_builder.py"
SPEC = ROOT / "outputs" / "bootstrap_spec.json"
DISTRIBUTION_CARDS = PHASE / "02-distributions" / "outputs" / "distribution_cards.json"


def load_builder():
    module_spec = importlib.util.spec_from_file_location("bootstrap_interval_builder", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_builder()
    report = builder.run(DATA / "sample_observations.csv", SPEC, DISTRIBUTION_CARDS)
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "resampling_manifest": report["resampling_manifest"],
                "intervals": {
                    item["statistic_id"]: {
                        "method": item["method"],
                        "observed": item["observed_statistic"],
                        "lower": item["lower"],
                        "upper": item["upper"],
                        "status": item["status"],
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
