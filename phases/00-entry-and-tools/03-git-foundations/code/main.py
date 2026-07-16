from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


LESSON_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = LESSON_ROOT / "outputs" / "git_project_check.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("git_project_check_demo", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Git project checker")
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


def commit_files(root: Path, files: dict[str, str], message: str) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(root, "add", "--", *files)
    git(root, "commit", "-q", "-m", message)


def build_demo_repository(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Course Student")
    git(root, "config", "user.email", "student@example.com")
    commit_files(
        root,
        {
            "README.md": "# Revenue project\n",
            ".gitignore": (
                ".venv/\n"
                "__pycache__/\n"
                "*.py[cod]\n"
                ".ipynb_checkpoints/\n"
                ".env\n"
                "data/raw/\n"
                "outputs/local/\n"
            ),
        },
        "Initialize revenue project",
    )
    commit_files(
        root,
        {
            "queries/revenue_by_day.sql": (
                "SELECT\n"
                "    order_date,\n"
                "    SUM(amount) AS revenue\n"
                "FROM orders\n"
                "WHERE status = 'paid'\n"
                "GROUP BY order_date;\n"
            ),
            "docs/metric-definition.md": (
                "# Дневная выручка\n\n"
                "Сумма оплаченных заказов за календарный день.\n"
            ),
        },
        "Add paid revenue calculation",
    )
    raw_extract = root / "data" / "raw" / "orders.csv"
    raw_extract.parent.mkdir(parents=True)
    raw_extract.write_text("order_id,amount\n101,120\n", encoding="utf-8")


def main() -> None:
    checker = load_checker()
    with TemporaryDirectory() as directory:
        repository = Path(directory) / "revenue-project"
        repository.mkdir()
        build_demo_repository(repository)
        report = checker.evaluate_repository(repository)
        print(checker.render_markdown(report))


if __name__ == "__main__":
    main()
