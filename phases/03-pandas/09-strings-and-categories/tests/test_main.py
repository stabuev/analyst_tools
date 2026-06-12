from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "text_categories.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("text_categories", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
TEXT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TEXT)


class TextCategoriesTest(unittest.TestCase):
    def test_normalize_text_strips_case_and_separators(self) -> None:
        result = TEXT.normalize_text(pd.Series([" Add-On ", "PREMIUM PLAN"]))
        self.assertEqual(result.tolist(), ["add_on", "premium_plan"])

    def test_aliases_collapse_synonyms(self) -> None:
        result = TEXT.normalize_text(
            pd.Series(["addon", "add-on"]),
            aliases={"addon": "add_on"},
        )
        self.assertEqual(result.tolist(), ["add_on", "add_on"])

    def test_unknown_category_can_fail(self) -> None:
        with self.assertRaisesRegex(TEXT.CategoryContractError, "unknown categories"):
            TEXT.as_category(
                pd.Series(["known", "new"], dtype="string"),
                categories=["known"],
            )

    def test_unknown_category_can_map_to_other(self) -> None:
        result = TEXT.as_category(
            pd.Series(["known", "new"], dtype="string"),
            categories=["known"],
            unknown="other",
        )
        self.assertEqual(result.astype("string").tolist(), ["known", "other"])

    def test_missing_category_remains_missing(self) -> None:
        result = TEXT.as_category(
            pd.Series(["known", None], dtype="string"),
            categories=["known"],
        )
        self.assertTrue(pd.isna(result.iloc[1]))

    def test_users_get_normalized_country_and_plan(self) -> None:
        users = TEXT.normalize_users(pd.read_csv(DATA / "users.csv"))
        self.assertIn("KZ", users["country"].dropna().tolist())
        self.assertEqual(str(users["plan"].dtype), "category")

    def test_item_synonyms_share_category(self) -> None:
        items = TEXT.normalize_items(pd.read_csv(DATA / "order_items.csv"))
        order = items.loc[items["order_id"] == "O1001", "category"]
        self.assertEqual(order.astype("string").tolist(), ["add_on", "add_on"])

    def test_cli_prints_category_vocabularies(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                DATA / "users.csv",
                "--items",
                DATA / "order_items.csv",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("add_on", json.loads(result.stdout)["item_categories"]["categories"])


if __name__ == "__main__":
    unittest.main()
