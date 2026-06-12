from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


REQUIRED_SECTIONS = (
    "Что изменено",
    "Проверка",
    "Решения и ограничения",
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
        raise ValueError(f"not a Git working tree: {candidate}")
    return Path(result.stdout.strip()).resolve()


def verify_ref(root: Path, ref: str) -> str:
    result = run_git(
        root,
        "rev-parse",
        "--verify",
        f"{ref}^{{commit}}",
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"unknown commit or branch: {ref}")
    return result.stdout.strip()


def split_nul(value: str) -> list[str]:
    return [item for item in value.split("\0") if item]


def current_branch(root: Path) -> str | None:
    result = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def parse_sections(markdown: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", markdown, flags=re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[match.group(1).strip()] = markdown[start:end].strip()
    return sections


def meaningful_section(value: str) -> bool:
    without_comments = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    meaningful_lines = []
    for line in without_comments.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("- ["):
            continue
        if stripped in {"```", "```text", "```bash", "```shell"}:
            continue
        meaningful_lines.append(stripped)
    return len(" ".join(meaningful_lines)) >= 20


def commit_list(root: Path, base: str, head: str) -> list[dict[str, str]]:
    output = run_git(
        root,
        "log",
        "--reverse",
        "--format=%h%x1f%s%x1e",
        f"{base}..{head}",
    ).stdout
    commits: list[dict[str, str]] = []
    for record in output.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        commit_hash, subject = record.split("\x1f", 1)
        commits.append({"hash": commit_hash, "subject": subject})
    return commits


def review_questions(files: list[str]) -> list[str]:
    questions = [
        "Соответствует ли изменение заявленной задаче и не расширяет ли scope?",
        "Есть ли проверяемое доказательство результата, а не только успешный запуск?",
        "Можно ли безопасно отменить изменение без скрытых ручных шагов?",
    ]
    suffixes = {Path(path).suffix.casefold() for path in files}
    names = {Path(path).name.casefold() for path in files}
    if ".py" in suffixes or ".ipynb" in suffixes:
        questions.extend(
            [
                "Покрыты ли граничные случаи и не зависит ли результат от скрытого состояния?",
                "Не мутируются ли входные данные и воспроизводимы ли случайные процессы?",
            ]
        )
    if ".sql" in suffixes:
        questions.extend(
            [
                "Названы ли grain, ключи и ожидаемая кардинальность каждого join?",
                "Проверены ли NULL, дубликаты и размножение строк?",
            ]
        )
    if suffixes & {".csv", ".tsv", ".parquet", ".xlsx", ".json"}:
        questions.append(
            "Нужны ли эти данные в Git и не содержат ли они чувствительные поля или ответы?"
        )
    if {"pyproject.toml", "requirements.txt", "uv.lock"} & names:
        questions.append(
            "Обоснованы ли новые зависимости и зафиксирована ли воспроизводимая версия?"
        )
    if suffixes <= {".md", ".txt"} and files:
        questions.append(
            "Запускаются ли команды и существуют ли ссылки, заявленные в документации?"
        )
    return questions


def evaluate_pull_request(
    path: Path,
    base: str,
    head: str = "HEAD",
    body_path: Path | None = None,
) -> dict[str, Any]:
    root = resolve_repository(path)
    base_hash = verify_ref(root, base)
    head_hash = verify_ref(root, head)
    branch = current_branch(root) if head == "HEAD" else head
    merge_base = run_git(root, "merge-base", base, head, check=False)
    merge_base_hash = merge_base.stdout.strip() if merge_base.returncode == 0 else ""
    commits = commit_list(root, base, head) if merge_base_hash else []
    files = (
        split_nul(
            run_git(
                root,
                "diff",
                "--name-only",
                "-z",
                f"{base}...{head}",
            ).stdout
        )
        if merge_base_hash
        else []
    )
    status = split_nul(
        run_git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ).stdout
    )

    body_text = ""
    sections: dict[str, str] = {}
    body_error = ""
    if body_path is None:
        body_error = "PR description path is required."
    else:
        candidate = body_path.expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.is_file():
            body_error = f"PR description does not exist: {candidate}"
        else:
            body_text = candidate.read_text(encoding="utf-8")
            sections = parse_sections(body_text)

    missing_sections = [
        section
        for section in REQUIRED_SECTIONS
        if section not in sections or not meaningful_section(sections[section])
    ]
    diff_stat = (
        run_git(root, "diff", "--shortstat", f"{base}...{head}").stdout.strip()
        if merge_base_hash
        else ""
    )
    ahead = len(commits)
    behind = (
        int(run_git(root, "rev-list", "--count", f"{head}..{base}").stdout.strip())
        if merge_base_hash
        else 0
    )

    checks = [
        {
            "id": "separate-head",
            "passed": base_hash != head_hash and branch not in {None, base},
            "message": (
                f"Head `{branch}` отличается от base `{base}`."
                if base_hash != head_hash and branch not in {None, base}
                else "Head должен быть отдельной именованной веткой с изменениями."
            ),
        },
        {
            "id": "merge-base",
            "passed": bool(merge_base_hash),
            "message": (
                f"Merge base: {merge_base_hash[:12]}."
                if merge_base_hash
                else "У base и head не найден общий предок."
            ),
        },
        {
            "id": "commits",
            "passed": ahead > 0,
            "message": f"Commits в предложении: {ahead}.",
        },
        {
            "id": "changed-files",
            "passed": bool(files),
            "message": f"Изменённых файлов: {len(files)}.",
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
            "id": "description",
            "passed": not body_error and not missing_sections,
            "message": (
                "Описание PR содержит цель, проверку и ограничения."
                if not body_error and not missing_sections
                else body_error
                or "Нужно заполнить разделы: " + ", ".join(missing_sections)
            ),
        },
    ]
    return {
        "repository": str(root),
        "base": base,
        "head": branch or head,
        "merge_base": merge_base_hash,
        "ahead": ahead,
        "behind": behind,
        "diff_stat": diff_stat,
        "ready": all(check["passed"] for check in checks),
        "checks": checks,
        "commits": commits,
        "files": files,
        "working_tree": status,
        "review_questions": review_questions(files),
    }


def markdown_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("`", "'")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Pull request review packet",
        "",
        f"- Repository: `{markdown_escape(report['repository'])}`",
        f"- Range: `{report['base']}...{report['head']}`",
        f"- Commits ahead: {report['ahead']}",
        f"- Base-only commits: {report['behind']}",
        f"- Diff: {report['diff_stat'] or 'empty'}",
        f"- Result: **{'ready for review' if report['ready'] else 'needs work'}**",
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

    lines.extend(["", "## Commits", ""])
    if report["commits"]:
        for commit in report["commits"]:
            lines.append(
                f"- `{commit['hash']}` {markdown_escape(commit['subject'])}"
            )
    else:
        lines.append("- _No proposed commits_")

    lines.extend(["", "## Changed files", ""])
    if report["files"]:
        lines.extend(f"- `{markdown_escape(path)}`" for path in report["files"])
    else:
        lines.append("- _No changed files_")

    lines.extend(["", "## Review checklist", ""])
    lines.extend(f"- [ ] {question}" for question in report["review_questions"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a local pull request packet from a base and head branch"
    )
    parser.add_argument("repository", nargs="?", default=".")
    parser.add_argument("--base", default="main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = evaluate_pull_request(
            Path(args.repository),
            base=args.base,
            head=args.head,
            body_path=args.body,
        )
    except (RuntimeError, ValueError) as error:
        parser.exit(2, f"pr-review-packet: {error}\n")

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
