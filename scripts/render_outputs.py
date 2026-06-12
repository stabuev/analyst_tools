from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name


OUTPUT_INDEX = ROOT / "outputs" / "index.json"


def build_output_index(curriculum: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for phase in curriculum["phases"]:
        phase_dir = phase_dir_name(phase)
        for index, lesson in enumerate(phase["lessons"], start=1):
            if lesson["status"] != "complete":
                continue
            lesson_dir = lesson_dir_name(index, lesson)
            manifest_path = (
                root / "phases" / phase_dir / lesson_dir / "outputs" / "artifact.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifacts.append(
                {
                    **manifest,
                    "phase": phase["number"],
                    "lesson": index,
                    "lesson_title": lesson["title"],
                    "source": str(manifest_path.parent.relative_to(root)),
                }
            )
    return {"version": "1.0.0", "artifacts": artifacts}


def render_output_index(index: dict[str, Any]) -> str:
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"


def write_output_index(root: Path = ROOT) -> None:
    output_path = root / "outputs" / "index.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(
        render_output_index(build_output_index(load_curriculum(root / "curriculum.json"), root)),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the reusable artifact catalog")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render_output_index(build_output_index(load_curriculum()))
    if args.check:
        if not OUTPUT_INDEX.exists() or OUTPUT_INDEX.read_text(encoding="utf-8") != expected:
            raise SystemExit("outputs/index.json is stale.")
        print("Artifact index is up to date.")
        return
    write_output_index()
    print("Rendered outputs/index.json.")


if __name__ == "__main__":
    main()
