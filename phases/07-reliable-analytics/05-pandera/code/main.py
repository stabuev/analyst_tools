from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.dataframe_contract import load_frames, validate_frames


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    data_dir = lesson_root.parent / "data" / "tiny"
    print(json.dumps(validate_frames(load_frames(data_dir)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
