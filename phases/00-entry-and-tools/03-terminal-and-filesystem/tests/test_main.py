from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = LESSON_ROOT / "outputs" / "file_audit.sh"


def run_audit(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(AUDIT_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class FileAuditTest(TestCase):
    def test_artifact_is_executable(self) -> None:
        self.assertTrue(os.access(AUDIT_SCRIPT, os.X_OK))

    def test_report_counts_files_and_excludes_git(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "project with spaces"
            (root / "data").mkdir(parents=True)
            (root / "notes").mkdir()
            (root / ".git").mkdir()
            (root / "data" / "orders.csv").write_bytes(b"1234567890")
            (root / "notes" / "analysis plan.md").write_bytes(b"12345")
            (root / "README").write_bytes(b"123")
            (root / ".git" / "config").write_bytes(b"x" * 100)

            result = run_audit("--top", "2", str(root))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- Files: 3", result.stdout)
        self.assertIn("- Bytes: 18", result.stdout)
        self.assertIn("data/orders.csv", result.stdout)
        self.assertIn(r"notes/analysis\ plan.md", result.stdout)
        self.assertNotIn(".git", result.stdout)
        self.assertIn("| `csv` | 1 |", result.stdout)
        self.assertIn("| `[none]` | 1 |", result.stdout)

    def test_output_inside_root_is_not_counted_on_repeat_runs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.txt").write_text("sample", encoding="utf-8")
            output = root / "audit.md"

            first = run_audit("--output", str(output), str(root))
            first_report = output.read_text(encoding="utf-8")
            second = run_audit("--output", str(output), str(root))
            second_report = output.read_text(encoding="utf-8")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first_report, second_report)
        self.assertIn("- Files: 1", second_report)

    def test_unusual_file_name_stays_on_one_report_line(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "line\nbreak.txt").write_text("value", encoding="utf-8")

            result = run_audit(str(root))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(r"\n", result.stdout)
        self.assertNotIn("line\nbreak.txt", result.stdout)

    def test_invalid_arguments_return_usage_error(self) -> None:
        with TemporaryDirectory() as directory:
            invalid_top = run_audit("--top", "0", directory)
            directory_output = run_audit("--output", directory, directory)

        self.assertEqual(invalid_top.returncode, 2)
        self.assertIn("--top", invalid_top.stderr)
        self.assertEqual(directory_output.returncode, 2)
        self.assertIn("is a directory", directory_output.stderr)
