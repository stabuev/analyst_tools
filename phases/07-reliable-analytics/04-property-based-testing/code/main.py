from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.property_suite import run_suite


def main() -> None:
    print(json.dumps(run_suite(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
