from __future__ import annotations

import argparse
import ast
import builtins
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
KNOWN_NAMES = set(dir(builtins)) | {"__name__", "__file__", "__package__"}


def source_text(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    if isinstance(source, str):
        return source
    if isinstance(source, list) and all(isinstance(line, str) for line in source):
        return "".join(source)
    return ""


class TopLevelNames(ast.NodeVisitor):
    def __init__(self) -> None:
        self.loaded: set[str] = set()
        self.defined: set[str] = set()
        self.absolute_paths: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loaded.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.defined.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.defined.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.defined.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        self.defined.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.defined.add(node.name)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and (
            node.value.startswith("/") or WINDOWS_ABSOLUTE.match(node.value)
        ):
            self.absolute_paths.add(node.value)


def analyze_source(source: str) -> tuple[set[str], set[str], set[str], str | None]:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return set(), set(), set(), f"{error.msg} at line {error.lineno}"
    visitor = TopLevelNames()
    visitor.visit(tree)
    return visitor.loaded, visitor.defined, visitor.absolute_paths, None


def load_notebook(path: Path) -> dict[str, Any]:
    notebook = path.expanduser().resolve()
    if not notebook.is_file():
        raise ValueError(f"notebook does not exist: {notebook}")
    try:
        data = json.loads(notebook.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid notebook JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("notebook must contain a JSON object")
    return data


def audit_notebook(data: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    cells = data.get("cells")
    structure_errors: list[str] = []
    if data.get("nbformat") != 4:
        structure_errors.append("nbformat must be 4")
    if not isinstance(cells, list):
        structure_errors.append("cells must be a list")
        cells = []

    ids: list[str] = []
    code_cells: list[tuple[int, dict[str, Any]]] = []
    for index, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict):
            structure_errors.append(f"cell {index} must be an object")
            continue
        cell_id = cell.get("id")
        if not isinstance(cell_id, str) or not cell_id:
            structure_errors.append(f"cell {index} has no id")
        else:
            ids.append(cell_id)
        if cell.get("cell_type") == "code" and source_text(cell).strip():
            code_cells.append((index, cell))
    if len(ids) != len(set(ids)):
        structure_errors.append("cell ids must be unique")

    counts = [cell.get("execution_count") for _, cell in code_cells]
    outputs = [cell.get("outputs", []) for _, cell in code_cells]
    clean = all(count is None for count in counts) and all(not output for output in outputs)
    executed = (
        bool(counts)
        and all(isinstance(count, int) and count > 0 for count in counts)
        and counts == sorted(counts)
        and len(counts) == len(set(counts))
    )
    state_errors: list[str] = []
    if code_cells and not (clean or executed):
        state_errors.append(
            "code cells must be fully clean or have unique increasing execution counts"
        )

    output_errors: list[str] = []
    for index, cell in code_cells:
        for output in cell.get("outputs", []):
            if isinstance(output, dict) and output.get("output_type") == "error":
                output_errors.append(
                    f"cell {index} stores {output.get('ename', 'an error')} traceback"
                )

    static_errors: list[str] = []
    defined = set(KNOWN_NAMES)
    for index, cell in code_cells:
        source = source_text(cell)
        if source.lstrip().startswith(("%", "!")):
            static_errors.append(f"cell {index} starts with unsupported magic or shell code")
            continue
        loaded, created, absolute_paths, syntax_error = analyze_source(source)
        if syntax_error:
            static_errors.append(f"cell {index}: {syntax_error}")
            continue
        missing = sorted(loaded - defined - created)
        if missing:
            static_errors.append(
                f"cell {index} may use names before definition: {', '.join(missing)}"
            )
        if absolute_paths:
            static_errors.append(
                f"cell {index} contains absolute paths: {', '.join(sorted(absolute_paths))}"
            )
        defined.update(created)

    kernelspec = data.get("metadata", {}).get("kernelspec", {})
    metadata_errors: list[str] = []
    if not isinstance(kernelspec, dict) or not kernelspec.get("name"):
        metadata_errors.append("metadata.kernelspec.name is missing")

    sections = {
        "structure": structure_errors,
        "execution-state": state_errors,
        "outputs": output_errors,
        "top-down-code": static_errors,
        "metadata": metadata_errors,
    }
    checks = [
        {
            "id": name,
            "passed": not errors,
            "message": "valid" if not errors else "; ".join(errors),
        }
        for name, errors in sections.items()
    ]
    return {
        "path": str(path.expanduser().resolve()) if path else None,
        "ready": all(check["passed"] for check in checks),
        "storage_mode": "clean" if clean else "executed" if executed else "mixed",
        "cell_count": len(cells),
        "code_cell_count": len(code_cells),
        "checks": checks,
    }


def clean_notebook(data: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(data)
    for cell in cleaned.get("cells", []):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        cell["execution_count"] = None
        cell["outputs"] = []
        metadata = cell.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("execution", None)
    return cleaned


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Notebook reproducibility audit",
        "",
        f"- Notebook: `{report['path'] or 'in-memory'}`",
        f"- Cells: {report['cell_count']}",
        f"- Code cells: {report['code_cell_count']}",
        f"- Storage mode: `{report['storage_mode']}`",
        f"- Result: **{'READY' if report['ready'] else 'NEEDS ATTENTION'}**",
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
    parser = argparse.ArgumentParser(description="Audit stored Jupyter notebook state")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("notebook", type=Path)
    check.add_argument("--format", choices=("markdown", "json"), default="markdown")
    clean = subparsers.add_parser("clean")
    clean.add_argument("notebook", type=Path)
    clean.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        data = load_notebook(args.notebook)
    except ValueError as error:
        print(f"notebook-audit: {error}", file=sys.stderr)
        return 2
    if args.command == "clean":
        output = args.output or args.notebook
        output.write_text(
            json.dumps(clean_notebook(data), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        print(output)
        return 0
    report = audit_notebook(data, args.notebook)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
