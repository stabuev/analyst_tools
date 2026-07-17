from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "pytest_gate.py"
PROJECT = ROOT / "outputs" / "pytest_project"


def load_artifact():
    spec = importlib.util.spec_from_file_location("pytest_gate", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    gate = load_artifact()
    report = gate.evaluate(PROJECT)
    print(gate.render_markdown(report), end="")


if __name__ == "__main__":
    main()
