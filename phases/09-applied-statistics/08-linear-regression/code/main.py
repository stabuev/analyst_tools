from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
DATA = PHASE / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "ols_inference_runner.py"
SPEC = ROOT / "outputs" / "model_spec.json"


def load_runner():
    module_spec = importlib.util.spec_from_file_location("ols_inference_runner", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    runner = load_runner()
    report = runner.fit_model(DATA / "sample_observations.csv", SPEC)
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "summary": report["summary"],
                "coefficients": {
                    row["term"]: {
                        "coefficient": row["coefficient"],
                        "standard_error": row["standard_error"],
                        "ci": [row["ci_lower"], row["ci_upper"]],
                    }
                    for row in report["coefficients"]
                },
                "claim_type": report["claim"]["allowed_claim_type"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
