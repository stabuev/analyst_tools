from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ARTIFACT = (
    Path(__file__).resolve().parents[1] / "outputs" / "kernel_diagnostic.py"
)


def load_artifact():
    spec = importlib.util.spec_from_file_location("kernel_diagnostic", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    diagnostic = load_artifact()
    snapshot = diagnostic.runtime_snapshot()
    with tempfile.TemporaryDirectory(prefix="kernel-demo-") as directory:
        kernelspec = Path(directory) / "kernel.json"
        kernelspec.write_text(
            json.dumps(
                {
                    "argv": [
                        snapshot["executable"],
                        "-m",
                        "ipykernel_launcher",
                        "-f",
                        "{connection_file}",
                    ],
                    "display_name": "Python (analytics-demo)",
                    "language": "python",
                }
            ),
            encoding="utf-8",
        )
        report = diagnostic.evaluate(snapshot, diagnostic.load_kernelspec(kernelspec))
        print(diagnostic.render_markdown(report), end="")


if __name__ == "__main__":
    main()
