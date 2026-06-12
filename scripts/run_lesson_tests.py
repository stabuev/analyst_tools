from __future__ import annotations

import subprocess
import sys

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name


def main() -> None:
    curriculum = load_curriculum()
    completed = 0
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
            print(f"Testing {lesson_root.relative_to(ROOT)}")
            subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=lesson_root,
                check=True,
            )
            completed += 1
    print(f"Completed lesson test suites: {completed}")


if __name__ == "__main__":
    main()
