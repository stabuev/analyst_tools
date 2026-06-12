from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import SkipTest, TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = LESSON_ROOT / "outputs" / "uv_project_check.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("uv_project_test", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load uv project checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_uv(cache: Path, *arguments: str, check: bool = True):
    return subprocess.run(
        [
            "uv",
            *arguments,
            "--offline",
            "--no-python-downloads",
            "--cache-dir",
            str(cache),
        ],
        check=check,
        capture_output=True,
        text=True,
    )


def build_valid_project(root: Path) -> tuple[Path, Path]:
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


class UvProjectCheckTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("uv") is None:
            raise SkipTest("uv is required")
        cls.tool = load_tool()

    def evaluate(self, project: Path, cache: Path, modules=None):
        return self.tool.evaluate_project(
            project,
            modules=modules or [],
            offline=True,
            cache_dir=cache,
        )

    def test_locked_synced_project_with_import_passes(self) -> None:
        with TemporaryDirectory() as directory:
            project, cache = build_valid_project(Path(directory))
            report = self.evaluate(project, cache, ["metric_core"])

        self.assertTrue(report["ready"])
        self.assertEqual(report["lock_packages"], 2)
        self.assertTrue(all(check["passed"] for check in report["checks"]))

    def test_stale_lockfile_fails_without_being_updated(self) -> None:
        with TemporaryDirectory() as directory:
            project, cache = build_valid_project(Path(directory))
            pyproject = project / "pyproject.toml"
            content = pyproject.read_text(encoding="utf-8")
            pyproject.write_text(
                content.replace(
                    "dependencies = [\n",
                    'dependencies = [\n    "missing-course-package>=1",\n',
                ),
                encoding="utf-8",
            )
            before = project.joinpath("uv.lock").read_text(encoding="utf-8")
            report = self.evaluate(project, cache)
            after = project.joinpath("uv.lock").read_text(encoding="utf-8")

        check = next(item for item in report["checks"] if item["id"] == "lock-current")
        self.assertFalse(check["passed"])
        self.assertEqual(before, after)

    def test_missing_environment_fails_but_lock_stays_current(self) -> None:
        with TemporaryDirectory() as directory:
            project, cache = build_valid_project(Path(directory))
            shutil.rmtree(project / ".venv")
            report = self.evaluate(project, cache)

        lock = next(item for item in report["checks"] if item["id"] == "lock-current")
        environment = next(
            item for item in report["checks"] if item["id"] == "environment"
        )
        self.assertTrue(lock["passed"])
        self.assertFalse(environment["passed"])

    def test_locked_sync_recreates_deleted_environment(self) -> None:
        with TemporaryDirectory() as directory:
            project, cache = build_valid_project(Path(directory))
            shutil.rmtree(project / ".venv")
            run_uv(
                cache,
                "sync",
                "--locked",
                "--project",
                str(project),
            )
            report = self.evaluate(project, cache, ["metric_core"])
            environment_exists = project.joinpath(".venv").is_dir()

        self.assertTrue(report["ready"])
        self.assertTrue(environment_exists)

    def test_unignored_environment_fails(self) -> None:
        with TemporaryDirectory() as directory:
            project, cache = build_valid_project(Path(directory))
            project.joinpath(".gitignore").write_text("data/raw/\n", encoding="utf-8")
            report = self.evaluate(project, cache)

        check = next(item for item in report["checks"] if item["id"] == "gitignore")
        self.assertFalse(check["passed"])

    def test_missing_smoke_import_fails(self) -> None:
        with TemporaryDirectory() as directory:
            project, cache = build_valid_project(Path(directory))
            report = self.evaluate(project, cache, ["package_that_is_not_installed"])

        check = next(item for item in report["checks"] if item["id"] == "imports")
        self.assertFalse(check["passed"])
        self.assertFalse(report["ready"])

    def test_missing_lockfile_is_reported(self) -> None:
        with TemporaryDirectory() as directory:
            project, cache = build_valid_project(Path(directory))
            project.joinpath("uv.lock").unlink()
            report = self.evaluate(project, cache)

        check = next(item for item in report["checks"] if item["id"] == "lockfile")
        self.assertFalse(check["passed"])
        self.assertIn("missing", check["message"])
