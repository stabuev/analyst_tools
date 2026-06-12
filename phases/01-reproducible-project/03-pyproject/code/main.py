from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


ARTIFACT = (
    Path(__file__).resolve().parents[1] / "outputs" / "pyproject_audit.py"
)


def load_artifact():
    spec = importlib.util.spec_from_file_location("pyproject_audit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    audit = load_artifact()
    with tempfile.TemporaryDirectory(prefix="pyproject-contract-") as directory:
        root = Path(directory)
        audit.initialize_manifest(
            root,
            project_name="analytics-demo",
            description='Учебный проект с "единым контрактом"',
            requires_python=">=3.11,<3.14",
        )
        report = audit.evaluate_manifest(root)
        print(audit.render_markdown(report), end="")


if __name__ == "__main__":
    main()
