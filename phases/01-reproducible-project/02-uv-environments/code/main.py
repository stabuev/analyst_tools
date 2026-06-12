from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


LESSON_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = LESSON_ROOT / "outputs" / "uv_project_check.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("uv_project_demo", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load uv project checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_uv(cache: Path, *arguments: str) -> None:
    subprocess.run(
        [
            "uv",
            *arguments,
            "--offline",
            "--no-python-downloads",
            "--cache-dir",
            str(cache),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def build_project(root: Path) -> tuple[Path, Path]:
    cache = root / "cache"
    dependency = root / "metric-core"
    project = root / "analytics-app"
    run_uv(
        cache,
        "init",
        "--lib",
        str(dependency),
        "--name",
        "metric-core",
        "--python",
        sys.executable,
        "--vcs",
        "none",
        "--no-workspace",
    )
    run_uv(
        cache,
        "init",
        "--bare",
        str(project),
        "--name",
        "analytics-app",
        "--python",
        sys.executable,
        "--vcs",
        "none",
        "--no-workspace",
    )
    project.joinpath(".gitignore").write_text(".venv/\n", encoding="utf-8")
    project.joinpath(".python-version").write_text(
        f"{sys.version_info.major}.{sys.version_info.minor}\n",
        encoding="utf-8",
    )
    run_uv(
        cache,
        "add",
        "--editable",
        str(dependency),
        "--project",
        str(project),
    )
    return project, cache


def main() -> None:
    if shutil.which("uv") is None:
        raise SystemExit("uv is required for this lesson")
    tool = load_tool()
    with TemporaryDirectory() as directory:
        project, cache = build_project(Path(directory))
        report = tool.evaluate_project(
            project,
            modules=["metric_core"],
            offline=True,
            cache_dir=cache,
        )
        print(tool.render_markdown(report), end="")


if __name__ == "__main__":
    main()
