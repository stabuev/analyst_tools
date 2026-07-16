from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
PLACEHOLDERS = {"", "replace-me", "changeme", "your-value-here", "<required>"}
TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".ipynb",
    ".json",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".yaml",
    ".yml",
}
SENSITIVE_NAMES = {
    ".env",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "service-account.json",
}
SECRET_RULES = (
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    (
        "aws-access-key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "hardcoded-credential",
        re.compile(
            r"""(?ix)
            \b(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|client[_-]?secret|
            password|passwd|private[_-]?key|secret|token)\b
            \s*[:=]\s*
            ["'][^"'\n]{8,}["']
            """
        ),
    ),
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


def normalize_asset_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip().lstrip("./").rstrip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        raise ValueError("asset path must stay inside the repository")
    return normalized


def validate_environment_names(names: list[str]) -> list[str]:
    normalized: list[str] = []
    for name in names:
        candidate = name.strip()
        if not ENV_NAME_PATTERN.fullmatch(candidate):
            raise ValueError(f"invalid environment variable name: {name}")
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def settings_source(required_environment: list[str]) -> str:
    names = ",\n    ".join(repr(name) for name in required_environment)
    if len(required_environment) == 1:
        names += ","
    return (
        "from __future__ import annotations\n\n"
        "import os\n\n\n"
        "REQUIRED_ENVIRONMENT = (\n"
        f"    {names}\n"
        ")\n\n\n"
        "def require_env(name: str) -> str:\n"
        "    try:\n"
        "        value = os.environ[name]\n"
        "    except KeyError as error:\n"
        "        raise RuntimeError(f\"Required environment variable is missing: {name}\") "
        "from error\n"
        "    if not value:\n"
        "        raise RuntimeError(f\"Required environment variable is empty: {name}\")\n"
        "    return value\n\n\n"
        "def load_settings() -> dict[str, str]:\n"
        "    return {name: require_env(name) for name in REQUIRED_ENVIRONMENT}\n"
    )


def merge_gitignore(path: Path) -> bool:
    required = [".env", ".env.*", "!.env.example", "data/raw/"]
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [line for line in required if line not in existing]
    if not missing:
        return False
    lines = existing[:]
    if lines and lines[-1]:
        lines.append("")
    lines.extend(["# Local secrets and restricted extracts", *missing])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True


def write_template(path: Path, content: str, force: bool) -> str:
    if path.exists() and not force:
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "updated" if path.exists() and force else "created"


def initialize_template(
    path: Path,
    owner: str,
    required_environment: list[str],
    force: bool = False,
) -> dict[str, Any]:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project directory does not exist: {root}")
    owner = owner.strip()
    if len(owner) < 3 or owner.casefold() in {"replace-me", "unknown", "todo"}:
        raise ValueError("owner must identify a real team or responsible person")
    required = validate_environment_names(required_environment or ["WAREHOUSE_DSN"])

    policy = {
        "owner": owner,
        "required_environment": required,
        "data_assets": [
            {
                "path": "data/raw/",
                "classification": "restricted",
                "owner": owner,
                "retention_days": 7,
                "allowed_in_git": False,
            },
            {
                "path": "data/sample/",
                "classification": "public",
                "owner": owner,
                "retention_days": 30,
                "allowed_in_git": True,
            },
        ],
    }
    files = {
        ".env.example": "".join(f"{name}=\n" for name in required),
        "config/security-policy.json": json.dumps(
            policy,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        "src/settings.py": settings_source(required),
    }
    changes = {
        relative: write_template(root / relative, content, force)
        for relative, content in files.items()
    }
    changes[".gitignore"] = "updated" if merge_gitignore(root / ".gitignore") else "skipped"
    return {"root": str(root), "changes": changes}


def tracked_files(root: Path) -> list[str]:
    output = run_git(root, "ls-files", "-z").stdout
    return sorted(item for item in output.split("\0") if item)


def is_ignored(root: Path, relative: str) -> bool:
    result = run_git(
        root,
        "check-ignore",
        "--quiet",
        "--no-index",
        "--",
        relative,
        check=False,
    )
    return result.returncode == 0


def is_sensitive_filename(relative: str) -> bool:
    path = Path(relative)
    name = path.name.casefold()
    if name in SENSITIVE_NAMES:
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    return path.suffix.casefold() in {".key", ".p12", ".pfx"}


def parse_env_example(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    errors: list[str] = []
    if not path.is_file():
        return values, [".env.example is missing"]
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            errors.append(f".env.example:{line_number} must use NAME=value")
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not ENV_NAME_PATTERN.fullmatch(name):
            errors.append(f".env.example:{line_number} has invalid variable name")
            continue
        values[name] = value
    return values, errors


def load_policy(root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    path = root / "config" / "security-policy.json"
    if not path.is_file():
        return None, ["config/security-policy.json is missing"]
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return None, [f"security policy is invalid JSON: line {error.lineno}"]
    if not isinstance(policy, dict):
        return None, ["security policy must contain an object"]

    errors: list[str] = []
    owner = policy.get("owner")
    if (
        not isinstance(owner, str)
        or len(owner.strip()) < 3
        or owner.casefold() in {"replace-me", "unknown", "todo"}
    ):
        errors.append("policy owner is missing")

    environment = policy.get("required_environment")
    if not isinstance(environment, list) or not environment:
        errors.append("required_environment must be a non-empty list")
    elif any(
        not isinstance(name, str) or not ENV_NAME_PATTERN.fullmatch(name)
        for name in environment
    ):
        errors.append("required_environment contains an invalid variable name")
    elif len(environment) != len(set(environment)):
        errors.append("required_environment contains duplicates")

    assets = policy.get("data_assets")
    if not isinstance(assets, list) or not assets:
        errors.append("data_assets must be a non-empty list")
    else:
        seen_paths: set[str] = set()
        for index, asset in enumerate(assets, start=1):
            label = f"data_assets[{index}]"
            if not isinstance(asset, dict):
                errors.append(f"{label} must be an object")
                continue
            raw_path = asset.get("path")
            try:
                if not isinstance(raw_path, str):
                    raise ValueError
                asset_path = normalize_asset_path(raw_path)
            except ValueError:
                errors.append(f"{label}.path must stay inside the repository")
                continue
            if asset_path in seen_paths:
                errors.append(f"{label}.path duplicates {asset_path}")
            seen_paths.add(asset_path)
            classification = asset.get("classification")
            if classification not in CLASSIFICATIONS:
                errors.append(f"{label}.classification is invalid")
            asset_owner = asset.get("owner")
            if (
                not isinstance(asset_owner, str)
                or len(asset_owner.strip()) < 3
                or asset_owner.casefold() in {"replace-me", "unknown", "todo"}
            ):
                errors.append(f"{label}.owner is missing")
            retention = asset.get("retention_days")
            if not isinstance(retention, int) or retention <= 0:
                errors.append(f"{label}.retention_days must be positive")
            allowed = asset.get("allowed_in_git")
            if not isinstance(allowed, bool):
                errors.append(f"{label}.allowed_in_git must be boolean")
            elif classification != "public" and allowed:
                errors.append(f"{label} allows non-public data in Git")
    return policy, errors


def scan_tracked_files(root: Path, files: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for relative in files:
        path = root / relative
        if (
            path.is_symlink()
            or path.suffix.casefold() not in TEXT_SUFFIXES
            or relative == "config/security-policy.json"
        ):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, start=1):
            for rule, pattern in SECRET_RULES:
                if pattern.search(line):
                    findings.append(
                        {"path": relative, "line": line_number, "rule": rule}
                    )
    return findings


def evaluate_project(path: Path) -> dict[str, Any]:
    root = resolve_repository(path)
    files = tracked_files(root)
    policy, policy_errors = load_policy(root)

    ignored_failures = [
        relative
        for relative in (".env", ".env.local", "data/raw/customer-export.csv")
        if not is_ignored(root, relative)
    ]
    example_ignored = is_ignored(root, ".env.example")

    example_values, example_errors = parse_env_example(root / ".env.example")
    required_environment = (
        policy.get("required_environment", [])
        if policy is not None and isinstance(policy.get("required_environment"), list)
        else []
    )
    missing_environment = [
        name for name in required_environment if name not in example_values
    ]
    filled_environment = [
        name
        for name, value in example_values.items()
        if value.casefold() not in PLACEHOLDERS
    ]

    tracked_sensitive = [relative for relative in files if is_sensitive_filename(relative)]
    tracked_restricted: list[str] = []
    if policy is not None and isinstance(policy.get("data_assets"), list):
        for asset in policy["data_assets"]:
            if not isinstance(asset, dict) or asset.get("allowed_in_git") is not False:
                continue
            try:
                prefix = normalize_asset_path(str(asset.get("path", "")))
            except ValueError:
                continue
            tracked_restricted.extend(
                relative
                for relative in files
                if relative == prefix or relative.startswith(prefix + "/")
            )
    tracked_restricted = sorted(set(tracked_restricted))
    secret_findings = scan_tracked_files(root, files)

    checks = [
        {
            "id": "gitignore",
            "passed": not ignored_failures and not example_ignored,
            "message": (
                "Local secrets and restricted extracts are ignored; .env.example is visible."
                if not ignored_failures and not example_ignored
                else "Fix ignore rules for: "
                + ", ".join(ignored_failures + ([".env.example"] if example_ignored else []))
            ),
        },
        {
            "id": "policy",
            "passed": not policy_errors,
            "message": (
                "Data classification policy is complete."
                if not policy_errors
                else "; ".join(policy_errors)
            ),
        },
        {
            "id": "env-example",
            "passed": not example_errors and not missing_environment and not filled_environment,
            "message": (
                "Required variable names are documented without values."
                if not example_errors and not missing_environment and not filled_environment
                else "; ".join(
                    [
                        *example_errors,
                        *(
                            ["missing variables: " + ", ".join(missing_environment)]
                            if missing_environment
                            else []
                        ),
                        *(
                            [
                                "values must stay blank or placeholders: "
                                + ", ".join(filled_environment)
                            ]
                            if filled_environment
                            else []
                        ),
                    ]
                )
            ),
        },
        {
            "id": "tracked-sensitive",
            "passed": not tracked_sensitive,
            "message": (
                "No secret-bearing filenames are tracked."
                if not tracked_sensitive
                else "Tracked sensitive paths: " + ", ".join(tracked_sensitive)
            ),
        },
        {
            "id": "data-policy",
            "passed": not tracked_restricted,
            "message": (
                "No non-public data assets are tracked."
                if not tracked_restricted
                else "Tracked non-public assets: " + ", ".join(tracked_restricted)
            ),
        },
        {
            "id": "hardcoded-secrets",
            "passed": not secret_findings,
            "message": (
                "No explicit credential patterns found in tracked code and config files."
                if not secret_findings
                else f"Potential hardcoded credentials: {len(secret_findings)}."
            ),
        },
    ]
    return {
        "root": str(root),
        "ready": all(check["passed"] for check in checks),
        "checks": checks,
        "tracked_files": len(files),
        "required_environment": required_environment,
        "findings": secret_findings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    result = "ready" if report["ready"] else "needs attention"
    lines = [
        "# Secure project check",
        "",
        f"- Repository: `{report['root']}`",
        f"- Tracked files: {report['tracked_files']}",
        f"- Result: **{result}**",
        "",
        "## Checks",
        "",
        "| Check | Result | Details |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"| `{check['id']}` | {status} | {check['message']} |")
    lines.extend(["", "## Potential credential locations", ""])
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(
                f"- `{finding['path']}:{finding['line']}` — `{finding['rule']}`"
            )
    else:
        lines.append("_No explicit patterns found._")
    lines.extend(
        [
            "",
            "> This check is a guardrail, not proof that the project contains no secrets.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize and check a secure analytics project template"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create the security template")
    init_parser.add_argument("path", type=Path)
    init_parser.add_argument("--owner", required=True)
    init_parser.add_argument("--require", action="append", default=[], dest="required")
    init_parser.add_argument("--force", action="store_true")

    check_parser = subparsers.add_parser("check", help="Audit a Git working tree")
    check_parser.add_argument("path", type=Path)
    check_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    check_parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize_template(
                args.path,
                owner=args.owner,
                required_environment=args.required,
                force=args.force,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        report = evaluate_project(args.path)
        rendered = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else render_markdown(report)
        )
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if report["ready"] else 1
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(2, f"secure-project: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
