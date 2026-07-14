from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_peer_review_kit.py"


def load_review_kit():
    spec = importlib.util.spec_from_file_location("capstone_peer_review_kit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    review_kit = load_review_kit()
    with TemporaryDirectory() as directory:
        inputs = review_kit.write_sample_inputs(Path(directory) / "input")
        result = review_kit.build_review_package(
            upstream_verification_package=inputs["upstream_verification_package"],
            review_spec_path=inputs["review_spec_path"],
            review_submission_path=inputs["review_submission_path"],
            output_dir=LESSON_ROOT / "outputs",
        )
    report = result["report"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "valid": report["valid"],
                "reviewer_type": report["summary"]["reviewer_type"],
                "findings": report["summary"]["finding_count"],
                "closed_findings": report["summary"]["closed_findings"],
                "provisional_rubric_score": report["summary"]["provisional_rubric_score"],
                "next_stage": report["summary"]["next_stage"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
