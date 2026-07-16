from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


PR_REQUIRED_SECTIONS = (
    "Задача",
    "Что изменено",
    "Как проверено",
    "Ограничения",
)
REVIEW_REQUIRED_SECTIONS = (
    "Решение",
    "Файл и строки",
    "Наблюдение",
    "Риск",
    "Что исправить",
    "Как проверить",
)
ALLOWED_REVIEW_DECISIONS = {
    "comment": "Comment",
    "approve": "Approve",
    "request changes": "Request changes",
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


def verify_ref(root: Path, ref: str) -> str:
    result = run_git(root, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
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


def without_comments(value: str) -> str:
    return re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL).strip()


def meaningful_section(value: str) -> bool:
    cleaned = without_comments(value)
    meaningful_lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("- ["):
            continue
        if stripped in {"```", "```text", "```bash", "```shell"}:
            continue
        meaningful_lines.append(stripped)
    return len(" ".join(meaningful_lines)) >= 20


def load_markdown(path: Path | None, label: str) -> tuple[str, str]:
    if path is None:
        return "", f"{label} path is required."
    candidate = path.expanduser().resolve()
    if not candidate.is_file():
        return "", f"{label} does not exist: {candidate}"
    return candidate.read_text(encoding="utf-8"), ""


def missing_meaningful_sections(
    sections: dict[str, str],
    required: tuple[str, ...],
    *,
    short_sections: set[str] | None = None,
) -> list[str]:
    short_sections = short_sections or set()
    missing = []
    for section in required:
        value = sections.get(section, "")
        is_filled = bool(without_comments(value)) if section in short_sections else meaningful_section(value)
        if not is_filled:
            missing.append(section)
    return missing


def review_decision(sections: dict[str, str]) -> str:
    value = without_comments(sections.get("Решение", ""))
    first_line = next((line.strip() for line in value.splitlines() if line.strip()), "")
    normalized = first_line.strip("`*_ .").casefold()
    return ALLOWED_REVIEW_DECISIONS.get(normalized, "")


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


def evaluate_pull_request(
    path: Path,
    base: str,
    head: str = "HEAD",
    body_path: Path | None = None,
    review_path: Path | None = None,
) -> dict[str, Any]:
    root = resolve_repository(path)
    base_hash = verify_ref(root, base)
    head_hash = verify_ref(root, head)
    branch = current_branch(root) if head == "HEAD" else head
    merge_base_result = run_git(root, "merge-base", base, head, check=False)
    merge_base = (
        merge_base_result.stdout.strip() if merge_base_result.returncode == 0 else ""
    )

    commits = commit_list(root, base, head) if merge_base else []
    files = (
        split_nul(
            run_git(root, "diff", "--name-only", "-z", f"{base}...{head}").stdout
        )
        if merge_base
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

    body_text, body_error = load_markdown(body_path, "PR description")
    body_sections = parse_sections(body_text)
    missing_body_sections = missing_meaningful_sections(
        body_sections,
        PR_REQUIRED_SECTIONS,
    )

    review_text, review_error = load_markdown(review_path, "Review")
    review_sections = parse_sections(review_text)
    missing_review_sections = missing_meaningful_sections(
        review_sections,
        REVIEW_REQUIRED_SECTIONS,
        short_sections={"Решение"},
    )
    decision = review_decision(review_sections)

    diff_stat = (
        run_git(root, "diff", "--shortstat", f"{base}...{head}").stdout.strip()
        if merge_base
        else ""
    )
    behind = (
        int(run_git(root, "rev-list", "--count", f"{head}..{base}").stdout.strip())
        if merge_base
        else 0
    )

    separate_head = base_hash != head_hash and branch not in {None, base}
    body_ok = not body_error and not missing_body_sections
    review_ok = not review_error and not missing_review_sections and bool(decision)
    checks = [
        {
            "id": "separate-head",
            "passed": separate_head,
            "message": (
                f"Head `{branch}` отличается от base `{base}`."
                if separate_head
                else "Head должен быть отдельной именованной веткой с изменениями."
            ),
        },
        {
            "id": "merge-base",
            "passed": bool(merge_base),
            "message": (
                f"Merge base: {merge_base[:12]}."
                if merge_base
                else "У base и head не найден общий предок."
            ),
        },
        {
            "id": "commits",
            "passed": bool(commits),
            "message": f"Коммитов в предложении: {len(commits)}.",
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
            "id": "pr-description",
            "passed": body_ok,
            "message": (
                "Описание PR связывает задачу, изменение, проверку и ограничения."
                if body_ok
                else body_error
                or "Нужно заполнить разделы: " + ", ".join(missing_body_sections)
            ),
        },
        {
            "id": "review",
            "passed": review_ok,
            "message": (
                f"Ревью заполнено; решение: {decision}."
                if review_ok
                else review_error
                or "Нужно заполнить разделы: " + ", ".join(missing_review_sections)
                if missing_review_sections
                else "Решение должно быть Comment, Approve или Request changes."
            ),
        },
    ]

    return {
        "repository": str(root),
        "base": base,
        "head": branch or head,
        "merge_base": merge_base,
        "ahead": len(commits),
        "behind": behind,
        "diff_stat": diff_stat,
        "ready": all(check["passed"] for check in checks),
        "checks": checks,
        "commits": commits,
        "files": files,
        "working_tree": status,
        "pr_sections": list(body_sections),
        "review_sections": list(review_sections),
        "review_decision": decision,
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
        f"- Review decision: **{report['review_decision'] or 'not set'}**",
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
            f"| `{check['id']}` | {result} | {markdown_escape(check['message'])} |"
        )

    lines.extend(["", "## Commits", ""])
    if report["commits"]:
        for commit in report["commits"]:
            lines.append(f"- `{commit['hash']}` {markdown_escape(commit['subject'])}")
    else:
        lines.append("- _No proposed commits_")

    lines.extend(["", "## Changed files", ""])
    if report["files"]:
        lines.extend(f"- `{markdown_escape(path)}`" for path in report["files"])
    else:
        lines.append("- _No changed files_")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a branch, PR description, and analytical review"
    )
    parser.add_argument("repository", nargs="?", default=".")
    parser.add_argument("--base", default="main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = evaluate_pull_request(
            Path(args.repository),
            base=args.base,
            head=args.head,
            body_path=args.body,
            review_path=args.review,
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
