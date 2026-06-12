from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


class BroadcastingError(ValueError):
    """Raised when shapes or normalization parameters violate the contract."""


def validate_shape(shape: tuple[int, ...]) -> tuple[int, ...]:
    if any(isinstance(length, bool) or not isinstance(length, int) for length in shape):
        raise BroadcastingError("shape lengths must be integers")
    if any(length < 0 for length in shape):
        raise BroadcastingError("shape lengths cannot be negative")
    return shape


def broadcast_shape(*shapes: tuple[int, ...]) -> tuple[int, ...]:
    if not shapes:
        return ()
    result: tuple[int, ...] = ()
    for raw_shape in shapes:
        shape = validate_shape(tuple(raw_shape))
        width = max(len(result), len(shape))
        left = (1,) * (width - len(result)) + result
        right = (1,) * (width - len(shape)) + shape
        merged: list[int] = []
        for left_length, right_length in zip(left, right, strict=True):
            if left_length == right_length or left_length == 1 or right_length == 1:
                merged.append(max(left_length, right_length))
            else:
                raise BroadcastingError(
                    f"shapes {result} and {shape} conflict at {left_length} versus {right_length}"
                )
        result = tuple(merged)
    return result


def as_parameter(
    value: object,
    *,
    name: str,
    feature_count: int,
) -> np.ndarray:
    parameter = np.asarray(value, dtype=float)
    allowed = {(feature_count,), (1, feature_count)}
    if parameter.shape not in allowed:
        raise BroadcastingError(f"{name} shape {parameter.shape} must be one of {sorted(allowed)}")
    return parameter


def standardize_features(
    matrix: object,
    *,
    center: object | None = None,
    scale: object | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features = np.asarray(matrix, dtype=float)
    if features.ndim != 2 or features.shape[0] == 0 or features.shape[1] == 0:
        raise BroadcastingError("matrix must be a non-empty two-dimensional array")
    if not np.isfinite(features).all():
        raise BroadcastingError("matrix must contain only finite values")

    feature_count = features.shape[1]
    centers = (
        features.mean(axis=0)
        if center is None
        else as_parameter(center, name="center", feature_count=feature_count)
    )
    scales = (
        features.std(axis=0)
        if scale is None
        else as_parameter(scale, name="scale", feature_count=feature_count)
    )
    if np.any(scales == 0):
        raise BroadcastingError("scale contains zero; constant features cannot normalize")

    expected = features.shape
    if broadcast_shape(features.shape, centers.shape, scales.shape) != expected:
        raise BroadcastingError("parameters do not broadcast back to matrix shape")
    normalized = (features - centers) / scales
    return normalized, np.asarray(centers), np.asarray(scales)


def build_report(matrix: object) -> dict[str, Any]:
    features = np.asarray(matrix, dtype=float)
    normalized, centers, scales = standardize_features(features)
    return {
        "input_shape": list(features.shape),
        "center_shape": list(centers.shape),
        "scale_shape": list(scales.shape),
        "output_shape": list(normalized.shape),
        "centers": centers.tolist(),
        "scales": scales.tolist(),
        "normalized": normalized.tolist(),
        "column_means": normalized.mean(axis=0).tolist(),
        "column_stds": normalized.std(axis=0).tolist(),
    }


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise BroadcastingError("matrix must be valid JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize features with broadcasting")
    parser.add_argument("--matrix", default="[[1, 10], [3, 14], [5, 18]]")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = build_report(parse_json(args.matrix))
    except BroadcastingError as error:
        parser.exit(2, f"feature-normalization: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
