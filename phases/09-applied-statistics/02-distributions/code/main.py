from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "distribution_card_builder.py"
SPEC_PATH = ROOT / "outputs" / "distribution_spec.json"


def load_builder():
    module_spec = importlib.util.spec_from_file_location("distribution_card_builder", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_builder()
    report = builder.run(DATA / "sample_observations.csv", SPEC_PATH)
    families = {
        card["metric_id"]: card["distribution"]["family"]
        for card in report["cards"]
    }
    warning_ids = sorted(
        check["id"]
        for check in report["checks"]
        if check["severity"] == "warning" and not check["valid"]
    )
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "metric_families": families,
                "warning_ids": warning_ids,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
