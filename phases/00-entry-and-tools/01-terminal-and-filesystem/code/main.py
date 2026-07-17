from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

LESSON_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_SCRIPT = LESSON_ROOT / "outputs" / "folder_summary.sh"


def main() -> None:
    with TemporaryDirectory() as directory:
        folder = Path(directory) / "client files"
        folder.mkdir()
        (folder / "orders.csv").write_text("order_id,amount\n1,100\n", encoding="utf-8")
        (folder / "notes.md").write_text("Check the grain.\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(SUMMARY_SCRIPT), str(folder)],
            check=True,
            capture_output=True,
            text=True,
        )
        print(result.stdout, end="")


if __name__ == "__main__":
    main()
