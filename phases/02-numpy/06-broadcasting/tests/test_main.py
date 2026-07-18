from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "feature_normalization.py"
SPEC = importlib.util.spec_from_file_location("feature_normalization", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
NORMALIZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NORMALIZE)


class FeatureNormalizationTest(unittest.TestCase):
    def test_manual_broadcast_shape_matches_numpy(self) -> None:
        cases = [
            ((3, 4), (4,)),
            ((5, 1), (1, 6)),
            ((8, 1, 6, 1), (7, 1, 5)),
            ((), (2, 3)),
        ]
        for left, right in cases:
            self.assertEqual(
                NORMALIZE.broadcast_shape(left, right),
                np.broadcast_shapes(left, right),
            )

    def test_incompatible_shapes_are_rejected(self) -> None:
        with self.assertRaisesRegex(NORMALIZE.BroadcastingError, "conflict"):
            NORMALIZE.broadcast_shape((4, 3), (4,))

    def test_standardization_has_zero_means_and_unit_scales(self) -> None:
        normalized, centers, scales = NORMALIZE.standardize_features([[1, 10], [3, 14], [5, 18]])
        np.testing.assert_allclose(normalized.mean(axis=0), [0, 0], atol=1e-12)
        np.testing.assert_allclose(normalized.std(axis=0), [1, 1], atol=1e-12)
        np.testing.assert_allclose(centers, [3, 14])
        self.assertEqual(scales.shape, (2,))

    def test_explicit_row_parameters_are_supported(self) -> None:
        normalized, _, _ = NORMALIZE.standardize_features(
            [[1, 10], [3, 14]],
            center=[[1, 10]],
            scale=[[2, 4]],
        )
        np.testing.assert_allclose(normalized, [[0, 0], [1, 1]])

    def test_column_parameter_is_rejected_as_wrong_semantics(self) -> None:
        with self.assertRaisesRegex(NORMALIZE.BroadcastingError, "center shape"):
            NORMALIZE.standardize_features(
                [[1, 10], [3, 14]],
                center=[[1], [3]],
                scale=[1, 1],
            )

    def test_constant_feature_is_rejected(self) -> None:
        with self.assertRaisesRegex(NORMALIZE.BroadcastingError, "zero"):
            NORMALIZE.standardize_features([[1, 10], [1, 14], [1, 18]])

    def test_cli_returns_normalization_report(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--matrix", "[[1, 10], [3, 14], [5, 18]]"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["output_shape"], [3, 2])
        np.testing.assert_allclose(report["column_means"], [0, 0], atol=1e-12)

    def test_cli_failure_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--matrix", "[[1, 10], [1, 14]]"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
