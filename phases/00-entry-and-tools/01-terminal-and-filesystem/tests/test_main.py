from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = LESSON_ROOT / "outputs" / "folder_summary.sh"
SUMMARY_SCRIPT = Path(
    os.environ.get("FOLDER_SUMMARY_SCRIPT", str(DEFAULT_SCRIPT))
).expanduser().resolve()


def run_summary(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SUMMARY_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class FolderSummaryTest(TestCase):
    def test_counts_files_and_lists_sorted_csv_paths(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "client files"
            folder.mkdir()
            (folder / "orders.csv").write_text("order_id\n1\n", encoding="utf-8")
            (folder / "customers.csv").write_text("customer_id\n1\n", encoding="utf-8")
            (folder / "analysis plan.md").write_text("Check grain.\n", encoding="utf-8")

            result = run_summary(str(folder))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Files: 3\n", result.stdout)
        customers = result.stdout.index("customers.csv")
        orders = result.stdout.index("orders.csv")
        self.assertLess(customers, orders)
        self.assertNotIn("analysis plan.md", result.stdout)

    def test_empty_folder_has_zero_files(self) -> None:
        with TemporaryDirectory() as directory:
            result = run_summary(directory)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Files: 0\n", result.stdout)
        self.assertTrue(result.stdout.endswith("CSV files:\n"))

    def test_output_is_deterministic_for_unchanged_folder(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "sample.csv").write_text("value\n1\n", encoding="utf-8")

            first = run_summary(str(folder))
            second = run_summary(str(folder))

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_invalid_arguments_return_clear_error(self) -> None:
        no_argument = run_summary()
        missing_folder = run_summary("missing-folder")

        self.assertEqual(no_argument.returncode, 2)
        self.assertIn("usage:", no_argument.stderr)
        self.assertEqual(missing_folder.returncode, 2)
        self.assertIn("directory does not exist", missing_folder.stderr)
        self.assertIsNone(re.search(r"Files:", missing_folder.stdout))
