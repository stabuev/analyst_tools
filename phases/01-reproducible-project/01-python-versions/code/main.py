from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


LESSON_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = LESSON_ROOT / "outputs" / "python_version_check.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("python_version_demo", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Python version checker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    tool = load_tool()
    current = sys.version_info
    minimum = f"{current.major}.{current.minor}"
    upper = f"{current.major}.{current.minor + 1}"

    with TemporaryDirectory() as directory:
        project = Path(directory) / "version-lab"
        project.mkdir()
        tool.initialize_contract(
            project,
            project_name="version-lab",
            requires_python=f">={minimum},<{upper}",
            selector=minimum,
        )
        candidates = [
            f"{current.major}.{max(current.minor - 1, 0)}",
            minimum,
            upper,
        ]
        report = tool.evaluate_project(project, candidates=candidates)
        print(tool.render_markdown(report), end="")


if __name__ == "__main__":
    main()
