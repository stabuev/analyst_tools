from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


GENERIC_SUBJECTS = {
    "change",
    "changes",
    "commit",
    "fix",
    "test",
    "update",
    "wip",
    "изменения",
    "обновление",
    "правки",
    "фикс",
}


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
        raise ValueError(f"not a Git working tree: {candidate}")
    return Path(result.stdout.strip()).resolve()


def split_nul(value: str) -> list[str]:
    return [item for item in value.split("\0") if item]


def normalized_subject(subject: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", " ", subject.casefold()).strip()


def commit_history(root: Path) -> list[dict[str, Any]]:
    result = run_git(
        root,
        "log",
        "--reverse",
        "--format=%H%x1f%h%x1f%s%x1e",
    )
    history: list[dict[str, Any]] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        commit_hash, short_hash, subject = record.split("\x1f", 2)
        changed = split_nul(
            run_git(
                root,
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                commit_hash,
            ).stdout
        )
        history.append(
            {
                "hash": short_hash,
                "subject": subject,
                "files": changed,
                "file_count": len(changed),
            }
        )
    return history


def evaluate_repository(
    path: Path,
    min_commits: int = 3,
    max_files_per_commit: int = 4,
) -> dict[str, Any]:
    if min_commits < 1:
        raise ValueError("min_commits must be positive")
    if max_files_per_commit < 1:
        raise ValueError("max_files_per_commit must be positive")

    root = resolve_repository(path)
    has_head = run_git(root, "rev-parse", "--verify", "HEAD", check=False).returncode == 0
    history = commit_history(root) if has_head else []
    status = split_nul(
        run_git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ).stdout
    )
    tracked_ignore = (
        run_git(root, "ls-files", "--error-unmatch", ".gitignore", check=False).returncode
        == 0
    )
    tracked_ignored = split_nul(
        run_git(
            root,
            "ls-files",
            "-ci",
            "-z",
            "--exclude-standard",
        ).stdout
    )

    bad_subjects = [
        commit
        for commit in history
        if (
            len(commit["subject"].strip()) < 8
            or len(commit["subject"]) > 72
            or normalized_subject(commit["subject"]) in GENERIC_SUBJECTS
        )
    ]
    wide_commits = [
        commit
        for commit in history
        if commit["file_count"] > max_files_per_commit
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
                "Рабочее дерево чистое."
                if not status
                else f"Незакоммиченных записей: {len(status)}."
            ),
        },
        {
            "id": "gitignore",
            "passed": tracked_ignore,
            "message": (
                ".gitignore отслеживается Git."
                if tracked_ignore
                else ".gitignore отсутствует в index."
            ),
        },
        {
            "id": "tracked-ignored",
            "passed": not tracked_ignored,
            "message": (
                "Игнорируемые пути не отслеживаются."
                if not tracked_ignored
                else "Уже отслеживаются игнорируемые пути: "
                + ", ".join(tracked_ignored)
            ),
        },
        {
            "id": "subjects",
            "passed": not bad_subjects,
            "message": (
                "Сообщения коммитов описывают изменения."
                if not bad_subjects
                else "Нужно уточнить сообщения: "
                + ", ".join(
                    f"{commit['hash']} {commit['subject']!r}"
                    for commit in bad_subjects
                )
            ),
        },
        {
            "id": "focus",
            "passed": not wide_commits,
            "message": (
                f"Каждый коммит меняет не более {max_files_per_commit} файлов."
                if not wide_commits
                else "Слишком широкие коммиты для учебного проекта: "
                + ", ".join(
                    f"{commit['hash']} ({commit['file_count']} файлов)"
                    for commit in wide_commits
                )
            ),
        },
    ]
    return {
        "repository": str(root),
        "ready": all(check["passed"] for check in checks),
        "checks": checks,
        "history": history,
        "working_tree": status,
        "tracked_ignored": tracked_ignored,
        "policy": {
            "min_commits": min_commits,
            "max_files_per_commit": max_files_per_commit,
        },
    }


def markdown_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("`", "'")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Git history audit",
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
            "## History",
            "",
            "| Commit | Subject | Files |",
            "|---|---|---:|",
        ]
    )
    if report["history"]:
        for commit in report["history"]:
            lines.append(
                f"| `{commit['hash']}` | "
                f"{markdown_escape(commit['subject'])} | "
                f"{commit['file_count']} |"
            )
    else:
        lines.append("| - | _No commits_ | 0 |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit a small learning repository for a focused Git history"
    )
    parser.add_argument("repository", nargs="?", default=".")
    parser.add_argument("--min-commits", type=int, default=3)
    parser.add_argument("--max-files-per-commit", type=int, default=4)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = evaluate_repository(
            Path(args.repository),
            min_commits=args.min_commits,
            max_files_per_commit=args.max_files_per_commit,
        )
    except (RuntimeError, ValueError) as error:
        parser.exit(2, f"git-history-check: {error}\n")

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
