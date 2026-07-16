from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


LESSON_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = LESSON_ROOT / "outputs" / "secure_project.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("secure_project_demo", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load secure project tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    tool = load_tool()
    with TemporaryDirectory() as directory:
        project = Path(directory) / "safe-analytics-project"
        project.mkdir()
        git(project, "init", "-q")
        git(project, "config", "user.name", "Course Student")
        git(project, "config", "user.email", "student@example.com")

        tool.initialize_template(
            project,
            owner="analytics-team",
            required_environment=["WAREHOUSE_DSN", "ANALYTICS_API_TOKEN"],
        )
        sample = project / "data" / "sample" / "orders.csv"
        sample.parent.mkdir(parents=True)
        sample.write_text("order_id,amount\n101,120\n", encoding="utf-8")
        local_env = project / ".env"
        local_env.write_text(
            "WAREHOUSE_DSN=local-demo-value\nANALYTICS_API_TOKEN=local-demo-value\n",
            encoding="utf-8",
        )

        git(project, "add", ".gitignore", ".env.example", "config", "src", "data/sample")
        git(project, "commit", "-q", "-m", "Add secure project template")
        report = tool.evaluate_project(project)
        print(tool.render_markdown(report), end="")


if __name__ == "__main__":
    main()
