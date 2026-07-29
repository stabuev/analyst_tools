from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "sql_mart_builder.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("sql_mart_builder", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_artifact()
    with TemporaryDirectory() as directory:
        package = Path(directory) / "sql-marts"
        manifest = builder.build_package(
            DATA / "users.csv",
            DATA / "orders.csv",
            DATA / "order_items.csv",
            package,
        )

        # DataFrame появляется только после SQL-сборки, на требуемом grain.
        summary = pd.read_csv(
            package / "user_summary.csv",
            dtype={"user_id": "string"},
        )
        result = {
            "quality": manifest["quality"],
            "verification": builder.verify_package(package),
            "pandas_handoff": {
                "grain": ["user_id", "currency"],
                "rows": len(summary),
                "columns": summary.columns.tolist(),
                "preview": summary.head(3).to_dict(orient="records"),
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
