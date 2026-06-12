from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "notebook_audit.py"
NOTEBOOK = ROOT / "outputs" / "reproducible_analysis.ipynb"


def load_artifact():
    spec = importlib.util.spec_from_file_location("notebook_audit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    audit = load_artifact()
    report = audit.audit_notebook(audit.load_notebook(NOTEBOOK), NOTEBOOK)
    print(audit.render_markdown(report), end="")


if __name__ == "__main__":
    main()
