from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


REQUIRED_IGNORED_PATHS = (
    ".env",
    "data/raw/orders.csv",
    "outputs/local/report.html",
)
PROTECTED_TRACKED_PATHS = (
    ".env",
    "data/raw/",
    "outputs/local/",
)


def run_git(
    root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "--no-pager", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise RuntimeError(message)
    return result


def resolve_repository(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.exists():
        raise ValueError(f"path does not exist: {candidate}")
    result = run_git(candidate, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        raise ValueError(f"not a Git repository: {candidate}")
    return Path(result.stdout.strip()).resolve()


def split_nul(value: str) -> list[str]:
    return [item for item in value.split("\0") if item]


def commit_history(root: Path) -> list[dict[str, str]]:
    has_commit = run_git(
        root,
        "rev-parse",
        "--verify",
        "HEAD",
        check=False,
    ).returncode == 0
    if not has_commit:
        return []

    result = run_git(root, "log", "--reverse", "--format=%h%x1f%s%x1e")
    history: list[dict[str, str]] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        short_hash, subject = record.split("\x1f", 1)
        history.append({"hash": short_hash, "subject": subject})
    return history


def is_ignored(root: Path, relative_path: str) -> bool:
    result = run_git(
        root,
        "check-ignore",
        "--no-index",
        "--quiet",
        "--",
        relative_path,
        check=False,
    )
    return result.returncode == 0


def is_protected_path(path: str) -> bool:
    for protected in PROTECTED_TRACKED_PATHS:
        if protected.endswith("/") and path.startswith(protected):
            return True
        if path == protected:
            return True
    return False


def evaluate_repository(path: Path, min_commits: int = 2) -> dict[str, Any]:
    if min_commits < 1:
        raise ValueError("min_commits must be positive")

    root = resolve_repository(path)
    history = commit_history(root)
    status = split_nul(
        run_git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ).stdout
    )
    tracked = split_nul(run_git(root, "ls-files", "-z").stdout)
    protected_tracked = [item for item in tracked if is_protected_path(item)]
    ignore_results = {
        relative_path: is_ignored(root, relative_path)
        for relative_path in REQUIRED_IGNORED_PATHS
    }
    gitignore_tracked = ".gitignore" in tracked

    missing_ignore_rules = [
        path for path, ignored in ignore_results.items() if not ignored
    ]
    checks = [
        {
            "id": "history",
            "passed": len(history) >= min_commits,
            "message": (
                f"Коммитов в истории: {len(history)}; требуется минимум {min_commits}."
            ),
        },
        {
            "id": "clean-tree",
            "passed": not status,
            "message": (
                "Рабочая папка и staging area не содержат незавершённых изменений."
                if not status
                else f"Незавершённых путей: {len(status)}. Проверьте git status."
            ),
        },
        {
            "id": "gitignore-tracked",
            "passed": gitignore_tracked,
            "message": (
                ".gitignore хранится в репозитории."
                if gitignore_tracked
                else ".gitignore не отслеживается Git."
            ),
        },
        {
            "id": "ignore-rules",
            "passed": not missing_ignore_rules,
            "message": (
                "Локальная конфигурация, сырые данные и локальные отчёты игнорируются."
                if not missing_ignore_rules
                else "Не покрыты ignore-правилом: " + ", ".join(missing_ignore_rules)
            ),
        },
        {
            "id": "protected-paths",
            "passed": not protected_tracked,
            "message": (
                "Защищаемые локальные пути не отслеживаются."
                if not protected_tracked
                else "В истории находятся локальные пути: "
                + ", ".join(protected_tracked)
            ),
        },
    ]
    return {
        "repository": str(root),
        "ready": all(check["passed"] for check in checks),
        "checks": checks,
        "history": history,
        "working_tree": status,
        "protected_tracked": protected_tracked,
        "ignore_results": ignore_results,
    }


def markdown_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("`", "'")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Git project check",
        "",
        f"- Repository: `{markdown_escape(report['repository'])}`",
        f"- Result: **{'ready' if report['ready'] else 'needs work'}**",
        "",
        "## Checks",
        "",
        "| Check | Result | Details |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        result = "PASS" if check["passed"] else "FAIL"
        lines.append(
            f"| `{check['id']}` | {result} | "
            f"{markdown_escape(check['message'])} |"
        )

    lines.extend(
        [
            "",
            "## History for human review",
            "",
            "| Commit | Subject |",
            "|---|---|",
        ]
    )
    if report["history"]:
        for commit in report["history"]:
            lines.append(
                f"| `{commit['hash']}` | {markdown_escape(commit['subject'])} |"
            )
    else:
        lines.append("| - | _No commits_ |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check the basic safety of a learning analytics Git repository"
    )
    parser.add_argument("repository", nargs="?", default=".")
    parser.add_argument("--min-commits", type=int, default=2)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = evaluate_repository(
            Path(args.repository),
            min_commits=args.min_commits,
        )
    except (RuntimeError, ValueError) as error:
        parser.exit(2, f"git-project-check: {error}\n")

    rendered = (
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
