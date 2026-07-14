from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_portfolio_builder.py"


def load_portfolio_builder():
    spec = importlib.util.spec_from_file_location("capstone_portfolio_builder", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_portfolio_builder()
    with TemporaryDirectory() as directory:
        inputs = builder.write_sample_inputs(Path(directory) / "input")
        result = builder.build_portfolio_package(
            packages=inputs["packages"],
            capstone_brief_path=inputs["capstone_brief_path"],
            implementation_runner=inputs["implementation_runner"],
            defense_spec_path=inputs["defense_spec_path"],
            defense_submission_path=inputs["defense_submission_path"],
            output_dir=LESSON_ROOT / "outputs",
        )
    report = result["report"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "valid": result["valid"],
                "rubric_score": report["summary"]["rubric_score"],
                "rubric_max": report["summary"]["rubric_max"],
                "blocking_errors": report["summary"]["blocking_errors"],
                "challenge_classes": report["summary"]["challenge_classes"],
                "live_rerun_match": report["summary"]["live_rerun_match"],
                "package_dir": str(result["package_dir"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
