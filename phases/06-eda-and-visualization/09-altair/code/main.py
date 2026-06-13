from __future__ import annotations

import json


def encoding(field: str, semantic_type: str) -> dict[str, str]:
    return {"field": field, "type": semantic_type}


def main() -> None:
    spec = {
        "mark": "point",
        "encoding": {
            "x": encoding("sessions_7d", "quantitative"),
            "y": encoding("onboarding_seconds", "quantitative"),
            "color": encoding("platform", "nominal"),
        },
    }
    print(json.dumps(spec, indent=2))


if __name__ == "__main__":
    main()
