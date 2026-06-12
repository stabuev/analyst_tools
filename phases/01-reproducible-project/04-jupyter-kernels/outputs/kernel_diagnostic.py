from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


def normalized_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def runtime_snapshot() -> dict[str, Any]:
    return {
        "executable": str(normalized_path(sys.executable)),
        "prefix": str(normalized_path(sys.prefix)),
        "base_prefix": str(normalized_path(sys.base_prefix)),
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "ipykernel_version": package_version("ipykernel"),
        "cwd": str(Path.cwd().resolve()),
        "virtual_environment": os.environ.get("VIRTUAL_ENV"),
    }


def load_kernelspec(path: Path) -> dict[str, Any]:
    kernelspec = path.expanduser().resolve()
    if kernelspec.is_dir():
        kernelspec = kernelspec / "kernel.json"
    if not kernelspec.is_file():
        raise ValueError(f"kernel.json does not exist: {kernelspec}")
    try:
        data = json.loads(kernelspec.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid kernel.json: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("kernel.json must contain an object")
    return {"path": str(kernelspec), **data}


def resolve_kernel_executable(argv: Any, search_path: str | None = None) -> Path | None:
    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        return None
    command = argv[0]
    if "{" in command or "}" in command:
        return None
    candidate = Path(command).expanduser()
    if candidate.is_absolute():
        return candidate.resolve() if candidate.exists() else None
    located = shutil.which(command, path=search_path)
    return Path(located).resolve() if located else None


def evaluate(
    snapshot: dict[str, Any],
    kernelspec: dict[str, Any],
    expected_prefix: Path | None = None,
) -> dict[str, Any]:
    argv = kernelspec.get("argv")
    kernel_executable = resolve_kernel_executable(argv)
    current_executable = normalized_path(snapshot["executable"])
    current_prefix = normalized_path(snapshot["prefix"])
    checks = [
        {
            "id": "runtime-python",
            "passed": current_executable.is_file(),
            "message": f"running Python: {current_executable}",
        },
        {
            "id": "ipykernel",
            "passed": bool(snapshot.get("ipykernel_version")),
            "message": (
                f"ipykernel {snapshot['ipykernel_version']}"
                if snapshot.get("ipykernel_version")
                else "ipykernel is not installed in the running environment"
            ),
        },
        {
            "id": "kernelspec-language",
            "passed": str(kernelspec.get("language", "")).casefold() == "python",
            "message": f"language: {kernelspec.get('language') or 'missing'}",
        },
        {
            "id": "connection-file",
            "passed": isinstance(argv, list)
            and any("{connection_file}" in item for item in argv if isinstance(item, str)),
            "message": "argv must contain {connection_file}",
        },
        {
            "id": "kernelspec-python",
            "passed": kernel_executable is not None,
            "message": (
                f"kernelspec Python: {kernel_executable}"
                if kernel_executable
                else "kernelspec executable cannot be resolved"
            ),
        },
        {
            "id": "same-python",
            "passed": kernel_executable == current_executable,
            "message": (
                "kernelspec and running Python match"
                if kernel_executable == current_executable
                else f"running {current_executable}; kernelspec starts {kernel_executable}"
            ),
        },
    ]
    if expected_prefix is not None:
        expected = expected_prefix.expanduser().resolve()
        checks.append(
            {
                "id": "expected-prefix",
                "passed": current_prefix == expected,
                "message": f"running prefix {current_prefix}; expected {expected}",
            }
        )
    return {
        "ready": all(check["passed"] for check in checks),
        "runtime": snapshot,
        "kernelspec": {
            "path": kernelspec.get("path"),
            "display_name": kernelspec.get("display_name"),
            "language": kernelspec.get("language"),
            "argv": argv,
            "resolved_executable": str(kernel_executable) if kernel_executable else None,
        },
        "checks": checks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Jupyter kernel diagnostic",
        "",
        f"- Running Python: `{report['runtime']['executable']}`",
        f"- Environment prefix: `{report['runtime']['prefix']}`",
        f"- Python: `{report['runtime']['python_version']}`",
        f"- ipykernel: `{report['runtime']['ipykernel_version'] or 'missing'}`",
        f"- Kernelspec: `{report['kernelspec']['display_name'] or 'unnamed'}`",
        f"- Result: **{'MATCH' if report['ready'] else 'MISMATCH'}**",
        "",
        "| Check | Result | Details |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        lines.append(
            f"| `{check['id']}` | {'PASS' if check['passed'] else 'FAIL'} | "
            f"{check['message']} |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare the running Python process with a Jupyter kernelspec"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    current = subparsers.add_parser("current")
    current.add_argument("--format", choices=("json", "markdown"), default="json")
    check = subparsers.add_parser("check")
    check.add_argument("kernelspec", type=Path)
    check.add_argument("--expected-prefix", type=Path)
    check.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    snapshot = runtime_snapshot()
    if args.command == "current":
        if args.format == "markdown":
            print(
                "\n".join(f"- {key}: `{value}`" for key, value in snapshot.items())
            )
        else:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    try:
        report = evaluate(
            snapshot,
            load_kernelspec(args.kernelspec),
            args.expected_prefix,
        )
    except ValueError as error:
        print(f"kernel-diagnostic: {error}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
