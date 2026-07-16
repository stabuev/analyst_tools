from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


LESSON_ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = LESSON_ROOT / "outputs" / "pr_review_packet.py"


def load_packet_builder():
    spec = importlib.util.spec_from_file_location("pr_review_packet_demo", PACKET_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load pull request packet builder")
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


def write_file(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(root: Path, message: str, *paths: str) -> None:
    git(root, "add", "--", *paths)
    git(root, "commit", "-q", "-m", message)


def build_demo_repository(root: Path, body: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Course Student")
    git(root, "config", "user.email", "student@example.com")
    write_file(root, "README.md", "# Activation metric\n")
    write_file(root, ".gitignore", "__pycache__/\n")
    commit(root, "Initialize activation project", "README.md", ".gitignore")
    git(root, "branch", "-M", "main")

    git(root, "switch", "-q", "-c", "feature/activation-check")
    write_file(
        root,
        "src/activation.py",
        (
            "def activation_rate(activated: int, eligible: int) -> float:\n"
            "    if eligible <= 0:\n"
            "        raise ValueError('eligible must be positive')\n"
            "    return activated / eligible\n"
        ),
    )
    write_file(
        root,
        "tests/test_activation.py",
        (
            "from src.activation import activation_rate\n\n"
            "def test_activation_rate():\n"
            "    assert activation_rate(25, 100) == 0.25\n"
        ),
    )
    commit(
        root,
        "Add activation rate validation",
        "src/activation.py",
        "tests/test_activation.py",
    )
    body.write_text(
        (
            "## Что изменено\n\n"
            "Добавлен расчет activation rate с явной проверкой знаменателя.\n\n"
            "## Проверка\n\n"
            "Запущен тест контрольного примера 25 из 100.\n\n"
            "## Решения и ограничения\n\n"
            "Функция ожидает уже подготовленные агрегированные количества.\n"
        ),
        encoding="utf-8",
    )


def main() -> None:
    packet_builder = load_packet_builder()
    with TemporaryDirectory() as directory:
        repository = Path(directory) / "activation-project"
        repository.mkdir()
        body = Path(directory) / "activation-pr.md"
        build_demo_repository(repository, body)
        report = packet_builder.evaluate_pull_request(
            repository,
            base="main",
            body_path=body,
        )
        print(packet_builder.render_markdown(report))


if __name__ == "__main__":
    main()
