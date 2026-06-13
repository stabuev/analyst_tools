from __future__ import annotations

import json

import pandas as pd


def main() -> None:
    frame = pd.DataFrame(
        {
            "platform": ["web", "web", "android", "android"],
            "period": ["до", "после", "до", "после"],
            "activated": [0.7, 0.6, 0.68, 0.48],
        }
    )
    control = frame.pivot(index="platform", columns="period", values="activated")
    print(json.dumps(control.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
