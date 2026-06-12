from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


LESSON_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = LESSON_ROOT / "outputs" / "file_audit.sh"


def build_demo_tree(root: Path) -> None:
    files = {
        "data/orders.csv": "order_id,amount\n101,120\n102,75\n",
        "data/customers.csv": "customer_id,segment\n1,new\n2,returning\n",
        "notes/analysis plan.md": "# Analysis plan\n\nCheck the grain first.\n",
        "README": "Demo analytical project\n",
        ".git/config": "[core]\nrepositoryformatversion = 0\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_audit(root: Path, top: int = 5) -> str:
    result = subprocess.run(
        ["bash", str(AUDIT_SCRIPT), "--top", str(top), str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> None:
    with TemporaryDirectory() as directory:
        project = Path(directory) / "terminal lab"
        project.mkdir()
        build_demo_tree(project)
        print(run_audit(project))


if __name__ == "__main__":
    main()
