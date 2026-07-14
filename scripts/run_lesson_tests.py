from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name


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
            if working_tree_fingerprint() != initial_tree:
                raise RuntimeError(
                    f"Lesson suite changed the working tree: {lesson_root.relative_to(ROOT)}"
                )
            completed += 1
    print(f"Completed lesson test suites: {completed}")


if __name__ == "__main__":
    main()
