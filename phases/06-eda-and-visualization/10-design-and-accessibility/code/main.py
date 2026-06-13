from __future__ import annotations

import json


def contrast_ratio(lighter: float, darker: float) -> float:
    return (lighter + 0.05) / (darker + 0.05)


def main() -> None:
    print(
        json.dumps(
            {
                "black_on_white": contrast_ratio(1.0, 0.0),
                "threshold_normal_text": 4.5,
                "color_is_not_only_channel": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
