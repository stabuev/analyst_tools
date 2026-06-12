from __future__ import annotations

import importlib.util
from pathlib import Path


def load_advisor():
    path = Path(__file__).resolve().parents[1] / "outputs" / "route_advisor.py"
    spec = importlib.util.spec_from_file_location("route_advisor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load route advisor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    advisor = load_advisor()
    answers = ["product", "product", "basic", "product", "data"]
    result = advisor.build_recommendation(answers)
    print(advisor.format_recommendation(result))


if __name__ == "__main__":
    main()
