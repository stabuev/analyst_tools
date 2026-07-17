from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "notebook_audit.py"
NOTEBOOK = ROOT / "outputs" / "reproducible_analysis.ipynb"
SPEC = importlib.util.spec_from_file_location("notebook_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class NotebookAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.notebook = AUDIT.load_notebook(NOTEBOOK)

    def check(self, check_id: str, notebook=None) -> dict[str, object]:
        report = AUDIT.audit_notebook(notebook or self.notebook)
        return next(check for check in report["checks"] if check["id"] == check_id)

    def code_cells(self, notebook=None) -> list[dict[str, object]]:
        source = notebook or self.notebook
        return [cell for cell in source["cells"] if cell["cell_type"] == "code"]

    def test_artifact_is_clean_and_ready(self) -> None:
        report = AUDIT.audit_notebook(self.notebook, NOTEBOOK)

        self.assertTrue(report["ready"])
        self.assertEqual(report["storage_mode"], "clean")

    def test_mixed_clean_and_executed_state_fails(self) -> None:
        notebook = copy.deepcopy(self.notebook)
        self.code_cells(notebook)[0]["execution_count"] = 1

        self.assertFalse(self.check("execution-state", notebook)["passed"])

    def test_non_monotonic_execution_counts_fail(self) -> None:
        notebook = copy.deepcopy(self.notebook)
        for count, cell in zip((2, 1, 3), self.code_cells(notebook), strict=True):
            cell["execution_count"] = count

        self.assertFalse(self.check("execution-state", notebook)["passed"])

    def test_stored_traceback_fails(self) -> None:
        notebook = copy.deepcopy(self.notebook)
        self.code_cells(notebook)[0]["outputs"] = [
            {
                "output_type": "error",
                "ename": "NameError",
                "evalue": "missing",
                "traceback": [],
            }
        ]

        self.assertFalse(self.check("outputs", notebook)["passed"])

    def test_use_before_definition_is_detected(self) -> None:
        notebook = copy.deepcopy(self.notebook)
        self.code_cells(notebook)[0]["source"] = ["print(hidden_value)\n"]

        check = self.check("top-down-code", notebook)

        self.assertFalse(check["passed"])
        self.assertIn("hidden_value", check["message"])

    def test_absolute_local_path_is_detected(self) -> None:
        notebook = copy.deepcopy(self.notebook)
        self.code_cells(notebook)[0]["source"] = ['data = "/Users/me/data.csv"\n']

        self.assertFalse(self.check("top-down-code", notebook)["passed"])

    def test_clean_removes_outputs_counts_and_execution_metadata(self) -> None:
        notebook = copy.deepcopy(self.notebook)
        first = self.code_cells(notebook)[0]
        first["execution_count"] = 7
        first["outputs"] = [{"output_type": "stream", "name": "stdout", "text": "ok"}]
        first["metadata"]["execution"] = {"iopub.status.busy": "timestamp"}

        cleaned = AUDIT.clean_notebook(notebook)
        cleaned_first = self.code_cells(cleaned)[0]

        self.assertIsNone(cleaned_first["execution_count"])
        self.assertEqual(cleaned_first["outputs"], [])
        self.assertNotIn("execution", cleaned_first["metadata"])
        self.assertTrue(AUDIT.audit_notebook(cleaned)["ready"])

    def test_duplicate_cell_ids_fail(self) -> None:
        notebook = copy.deepcopy(self.notebook)
        notebook["cells"][1]["id"] = notebook["cells"][0]["id"]

        self.assertFalse(self.check("structure", notebook)["passed"])


if __name__ == "__main__":
    unittest.main()
