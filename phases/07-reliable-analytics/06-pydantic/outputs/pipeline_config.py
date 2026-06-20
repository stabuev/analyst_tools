import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CONFIG_VERSION = "1.0.0"


class QualityThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    freshness_hours: int = Field(gt=0, le=168)
    min_orders: int = Field(ge=0)
    max_orders: int = Field(gt=0)
    max_null_rate: float = Field(ge=0, le=1)
    max_duplicate_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered_volume_bounds(self) -> Self:
        if self.min_orders > self.max_orders:
            raise ValueError("min_orders must not exceed max_orders")
        return self


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    config_version: Literal["1.0.0"]
    input_dir: Path
    output_dir: Path
    timezone: str
    batch_date: date
    schema_version: Literal["1.0.0"]
    thresholds: QualityThresholds

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("unknown IANA timezone") from error
        return value

    @model_validator(mode="after")
    def distinct_paths(self) -> Self:
        if self.input_dir == self.output_dir:
            raise ValueError("input_dir and output_dir must differ")
        return self


def error_report(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "location": ".".join(str(part) for part in item["loc"]),
            "type": item["type"],
            "message": item["msg"],
            "input": item.get("input"),
        }
        for item in error.errors(include_url=False)
    ]


def validate_json(text: str) -> dict[str, Any]:
    try:
        config = PipelineConfig.model_validate_json(text)
    except ValidationError as error:
        return {
            "config_version": CONFIG_VERSION,
            "valid": False,
            "errors": error_report(error),
        }
    return {
        "config_version": CONFIG_VERSION,
        "valid": True,
        "config": config.model_dump(mode="json"),
        "errors": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate reliable pipeline configuration")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate_json(args.config.read_text(encoding="utf-8"))
    except OSError as error:
        report = {
            "config_version": CONFIG_VERSION,
            "valid": False,
            "errors": [
                {
                    "location": "config",
                    "type": "input_error",
                    "message": str(error),
                    "input": str(args.config),
                }
            ],
        }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
