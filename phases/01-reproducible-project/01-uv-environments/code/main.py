from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = LESSON_ROOT / "outputs" / "revenue_summary.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("revenue_summary_demo", ARTIFACT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the lesson artifact")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    artifact = load_artifact()
    with TemporaryDirectory() as directory:
        sample = Path(directory) / "orders.csv"
        sample.write_text(
            "order_id,status,amount\n"
            "TEST-001,paid,120\n"
            "TEST-002,pending,80\n"
            "TEST-003,paid,75\n",
            encoding="utf-8",
        )
        print(artifact.summarize_paid_orders(sample))


if __name__ == "__main__":
    main()
