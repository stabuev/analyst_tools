from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name


def lesson_practice_mode(lesson_root: Path) -> str:
    metadata = json.loads((lesson_root / "lesson.json").read_text(encoding="utf-8"))
    practice = metadata.get("practice")
    if practice is None:
        return "executable"
    return practice.get("mode", "") if isinstance(practice, dict) else ""


def working_tree_fingerprint() -> bytes:
    tracked = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary", "HEAD", "--"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    payload = bytearray(tracked)
    for raw_path in sorted(path for path in untracked.split(b"\0") if path):
        path = Path(raw_path.decode("utf-8"))
        payload.extend(b"\0")
        payload.extend(raw_path)
        payload.extend(b"\0")
        payload.extend((ROOT / path).read_bytes())
    return bytes(payload)


def main() -> None:
    curriculum = load_curriculum()
    initial_tree = working_tree_fingerprint()
    tested = 0
    skipped = 0
    for phase in curriculum["phases"]:
        for index, lesson in enumerate(phase["lessons"], start=1):
            if lesson["status"] != "complete":
                continue
            lesson_root = (
                ROOT
                / "phases"
                / phase_dir_name(phase)
                / lesson_dir_name(index, lesson)
            )
            tests_root = lesson_root / "tests"
            if lesson_practice_mode(lesson_root) == "guided-artifact":
                print(
                    f"Skipping {lesson_root.relative_to(ROOT)}: "
                    "rubric-verified practice"
                )
                skipped += 1
                continue
            if not tests_root.is_dir() or not any(tests_root.rglob("test*.py")):
                raise RuntimeError(
                    "Executable lesson has no behavioral tests: "
                    f"{lesson_root.relative_to(ROOT)}"
                )
            print(f"Testing {lesson_root.relative_to(ROOT)}")
            subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=lesson_root,
                check=True,
            )
            if working_tree_fingerprint() != initial_tree:
                raise RuntimeError(
                    f"Lesson suite changed the working tree: {lesson_root.relative_to(ROOT)}"
                )
            tested += 1
    print(f"Completed lesson test suites: {tested}; rubric-verified lessons: {skipped}")


if __name__ == "__main__":
    main()
