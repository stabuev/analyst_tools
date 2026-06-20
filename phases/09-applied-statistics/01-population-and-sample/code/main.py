from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "sampling_frame_auditor.py"
SPEC = ROOT / "outputs" / "sampling_spec.json"


def load_auditor():
    module_spec = importlib.util.spec_from_file_location("sampling_frame_auditor", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def manual_missing_from_frame(population: list[dict[str, str]], frame: list[dict[str, str]]) -> list[str]:
    eligible_ids = {
        row["user_id"]
        for row in population
        if row["eligible_for_analysis"] == "true" and row["is_test_user"] == "false"
    }
    frame_ids = {row["user_id"] for row in frame}
    return sorted(eligible_ids - frame_ids)


def main() -> None:
    auditor = load_auditor()
    population = auditor.read_csv(DATA / "population_users.csv")
    frame = auditor.read_csv(DATA / "sampling_frame.csv")
    report = auditor.run(
        DATA / "population_users.csv",
        DATA / "sampling_frame.csv",
        DATA / "sample_observations.csv",
        DATA / "segment_reference.csv",
        SPEC,
    )
    result = {
        "manual_missing_from_frame": manual_missing_from_frame(population, frame),
        "audit_valid": report["valid"],
        "warnings": report["summary"]["estimation_risks"],
        "summary": report["summary"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
