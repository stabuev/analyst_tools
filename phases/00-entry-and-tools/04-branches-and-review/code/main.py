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


def build_demo_repository(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Course Student")
    git(root, "config", "user.email", "student@example.com")
    write_file(
        root,
        ".gitignore",
        ".DS_Store\n.venv/\n__pycache__/\ndata/raw/*\n!data/raw/.gitkeep\n",
    )
    write_file(
        root,
        "README.md",
        "# Revenue project\n\nУчебный расчёт дневной выручки.\n",
    )
    write_file(root, "data/raw/.gitkeep", "")
    commit(
        root,
        "Initialize revenue project",
        ".gitignore",
        "README.md",
        "data/raw/.gitkeep",
    )
    write_file(
        root,
        "queries/revenue_by_day.sql",
        (
            "SELECT\n"
            "    order_date,\n"
            "    SUM(amount) AS revenue\n"
            "FROM orders\n"
            "WHERE status = 'paid'\n"
            "GROUP BY order_date;\n"
        ),
    )
    write_file(
        root,
        "docs/metric-definition.md",
        "# Дневная выручка\n\nСумма оплаченных заказов по календарным дням.\n",
    )
    commit(
        root,
        "Add daily revenue calculation",
        "queries/revenue_by_day.sql",
        "docs/metric-definition.md",
    )
    git(root, "branch", "-M", "main")

    git(root, "switch", "-q", "-c", "feature/paid-order-count")
    write_file(
        root,
        "queries/revenue_by_day.sql",
        (
            "SELECT\n"
            "    order_date,\n"
            "    SUM(amount) AS revenue,\n"
            "    COUNT(*) AS paid_order_count\n"
            "FROM orders\n"
            "WHERE status = 'paid'\n"
            "GROUP BY order_date;\n"
        ),
    )
    write_file(
        root,
        "docs/metric-definition.md",
        (
            "# Дневная выручка\n\n"
            "Grain результата — один календарный день.\n\n"
            "`paid_order_count` считает строки оплаченных заказов. "
            "Источник должен содержать одну строку на `order_id`.\n"
        ),
    )
    commit(
        root,
        "Add paid order count to daily revenue",
        "queries/revenue_by_day.sql",
        "docs/metric-definition.md",
    )


def write_pull_request(path: Path) -> None:
    path.write_text(
        (
            "## Задача\n\n"
            "Добавить число оплаченных заказов к дневному отчёту по выручке.\n\n"
            "## Что изменено\n\n"
            "В SQL добавлен paid_order_count, а в документации зафиксирован grain.\n\n"
            "## Как проверено\n\n"
            "Просмотрен полный diff ветки и рассчитан контрольный пример из трёх заказов.\n\n"
            "## Ограничения\n\n"
            "Корректность зависит от одной строки на order_id в исходной таблице.\n"
        ),
        encoding="utf-8",
    )


def write_review(path: Path) -> None:
    path.write_text(
        (
            "## Решение\n\nRequest changes\n\n"
            "## Файл и строки\n\n"
            "review_case.sql, SUM(orders.amount) после соединения с товарами.\n\n"
            "## Наблюдение\n\n"
            "Заказ повторяется по числу товаров, поэтому его сумма учитывается несколько раз.\n\n"
            "## Риск\n\n"
            "Контрольная выручка 195 превращается в 315 и искажает дневной отчёт.\n\n"
            "## Что исправить\n\n"
            "Сначала агрегировать товары до одной строки на заказ, затем выполнять JOIN.\n\n"
            "## Как проверить\n\n"
            "Сверить результат с независимой суммой заказов и случаем из двух товаров.\n"
        ),
        encoding="utf-8",
    )


def main() -> None:
    packet_builder = load_packet_builder()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "revenue-project"
        repository.mkdir()
        body = root / "pull-request.md"
        review = root / "review.md"
        build_demo_repository(repository)
        write_pull_request(body)
        write_review(review)
        report = packet_builder.evaluate_pull_request(
            repository,
            base="main",
            body_path=body,
            review_path=review,
        )
        print(packet_builder.render_markdown(report))


if __name__ == "__main__":
    main()
