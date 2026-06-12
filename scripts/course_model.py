from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CURRICULUM_PATH = ROOT / "curriculum.json"


def load_curriculum(path: Path = CURRICULUM_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def phase_dir_name(phase: dict[str, Any]) -> str:
    return f"{phase['number']:02d}-{phase['slug']}"


def lesson_dir_name(index: int, lesson: dict[str, Any]) -> str:
    return f"{index:02d}-{lesson['slug']}"

