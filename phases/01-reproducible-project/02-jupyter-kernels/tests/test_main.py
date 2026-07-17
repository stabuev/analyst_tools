from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ARTIFACT = (
    Path(__file__).resolve().parents[1] / "outputs" / "kernel_diagnostic.py"
)
NOTEBOOK = (
    Path(__file__).resolve().parents[1] / "outputs" / "kernel_diagnostic.ipynb"
)
SPEC = importlib.util.spec_from_file_location("kernel_diagnostic", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DIAGNOSTIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTIC)


class KernelDiagnosticTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.python = self.root / "venv" / "bin" / "python"
        self.python.parent.mkdir(parents=True)
        self.python.write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def snapshot(self, executable: Path | None = None) -> dict[str, object]:
        selected = executable or self.python
        return {
            "executable": str(selected),
            "prefix": str(self.root / "venv"),
            "base_prefix": "/usr",
            "python_version": "3.12.0",
            "ipykernel_version": "6.30.0",
            "cwd": str(self.root),
            "virtual_environment": str(self.root / "venv"),
        }

    def kernelspec(self, executable: Path | None = None) -> dict[str, object]:
        selected = executable or self.python
        return {
            "path": str(self.root / "kernel.json"),
            "argv": [
                str(selected),
                "-m",
                "ipykernel_launcher",
                "-f",
                "{connection_file}",
            ],
            "display_name": "Python (analytics)",
            "language": "python",
        }

    def test_matching_runtime_and_kernelspec_pass(self) -> None:
        report = DIAGNOSTIC.evaluate(self.snapshot(), self.kernelspec())

        self.assertTrue(report["ready"])

    def test_display_name_cannot_hide_wrong_python(self) -> None:
        other = self.root / "other" / "bin" / "python"
        other.parent.mkdir(parents=True)
        other.write_text("", encoding="utf-8")

        report = DIAGNOSTIC.evaluate(self.snapshot(), self.kernelspec(other))

        self.assertFalse(report["ready"])
        self.assertFalse(
            next(check for check in report["checks"] if check["id"] == "same-python")[
                "passed"
            ]
        )

    def test_missing_ipykernel_fails(self) -> None:
        snapshot = self.snapshot()
        snapshot["ipykernel_version"] = None

        report = DIAGNOSTIC.evaluate(snapshot, self.kernelspec())

        self.assertFalse(report["ready"])

    def test_expected_prefix_is_checked(self) -> None:
        report = DIAGNOSTIC.evaluate(
            self.snapshot(),
            self.kernelspec(),
            self.root / "different-env",
        )

        self.assertFalse(report["ready"])
        self.assertIn(
            "expected-prefix",
            {check["id"] for check in report["checks"] if not check["passed"]},
        )

    def test_connection_file_placeholder_is_required(self) -> None:
        kernelspec = self.kernelspec()
        kernelspec["argv"] = [str(self.python), "-m", "ipykernel_launcher"]

        report = DIAGNOSTIC.evaluate(self.snapshot(), kernelspec)

        self.assertFalse(report["ready"])

    def test_load_kernelspec_accepts_directory(self) -> None:
        kernel_dir = self.root / "kernel"
        kernel_dir.mkdir()
        (kernel_dir / "kernel.json").write_text(
            json.dumps(self.kernelspec()),
            encoding="utf-8",
        )

        loaded = DIAGNOSTIC.load_kernelspec(kernel_dir)

        self.assertEqual(loaded["display_name"], "Python (analytics)")

    def test_notebook_contains_runtime_evidence(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        source = "\n".join(
            "".join(cell.get("source", []))
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        )

        self.assertIn("sys.executable", source)
        self.assertIn("sys.prefix", source)
        self.assertIn("ipykernel", source)
        self.assertIn("Restart Kernel", json.dumps(notebook, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
