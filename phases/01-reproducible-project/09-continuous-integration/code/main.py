from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "outputs" / "ci_project"
ARTIFACT = PROJECT / "tools" / "workflow_audit.py"
WORKFLOW = PROJECT / ".github" / "workflows" / "quality.yml"


def load_artifact():
    spec = importlib.util.spec_from_file_location("workflow_audit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    audit = load_artifact()
    report = audit.evaluate(audit.load_workflow(WORKFLOW))
    print(audit.render_markdown(report), end="")


if __name__ == "__main__":
    main()
