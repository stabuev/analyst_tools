from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.defect_factory import materialize_defect, matrix_report


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    baseline = lesson_root.parent / "data" / "tiny"
    with TemporaryDirectory() as directory:
        example = materialize_defect(baseline, "item_total_mismatch", directory)
    print(
        json.dumps(
            {"matrix": matrix_report(), "materialized_example": example},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
