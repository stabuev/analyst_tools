from __future__ import annotations

import json


def conclusion(observation: str, explanation: str, limitation: str, next_step: str) -> dict:
    return {
        "observation": observation,
        "explanation": explanation,
        "limitation": limitation,
        "next_step": next_step,
    }


def main() -> None:
    print(
        json.dumps(
            conclusion(
                "Activation ниже после релиза.",
                "Channel mix и Android regression являются гипотезами.",
                "Наблюдательные данные не идентифицируют причинный эффект.",
                "Проверить Android 2.4 в технических событиях.",
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
