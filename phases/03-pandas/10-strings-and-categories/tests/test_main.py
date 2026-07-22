from __future__ import annotations

import importlib.util
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
    def test_normalize_text_handles_unicode_case_and_separators(self) -> None:
        source = pd.Series([" Ａdd‑On ", "Straße", "STRASSE"], dtype="string")
        result = TEXT.normalize_text(source)
        self.assertEqual(result.tolist(), ["add_on", "strasse", "strasse"])

    def test_normalize_text_maps_blank_to_missing(self) -> None:
        result = TEXT.normalize_text(pd.Series(["", " \u00a0 ", None], dtype="string"))
        self.assertTrue(result.isna().all())

    def test_normalize_text_applies_aliases_after_technical_normalization(self) -> None:
        result = TEXT.normalize_text(
            pd.Series(["Addon", "add-on", " SERVICE "], dtype="string"),
            aliases={"ADDON": "add_on"},
        )
        self.assertEqual(result.tolist(), ["add_on", "add_on", "service"])

    def test_conflicting_normalized_aliases_fail(self) -> None:
        with self.assertRaisesRegex(TEXT.CategoryContractError, "conflicting alias"):
            TEXT.normalize_text(
                pd.Series(["add-on"], dtype="string"),
                aliases={"ADD-ON": "add_on", "add_on": "service"},
            )

    def test_normalize_text_preserves_labels_name_and_source(self) -> None:
        source = pd.Series([" Premium ", None], index=["u2", "u7"], name="plan", dtype="string")
        original = source.copy(deep=True)
        result = TEXT.normalize_text(source)
        self.assertTrue(result.index.equals(source.index))
        self.assertEqual(result.name, "plan")
        self.assertEqual(result.tolist()[0], "premium")
        self.assertTrue(pd.isna(result.iloc[1]))
        pd.testing.assert_series_equal(source, original)

    def test_fullmatch_checks_the_whole_value_and_keeps_missing_unknown(self) -> None:
        result = TEXT.fullmatch_text(
            pd.Series(["RU", "RU-extra", None], name="country", dtype="string"),
            r"[A-Z]{2}",
        )
        self.assertEqual(result.name, "country")
        self.assertEqual(str(result.dtype), "boolean")
        self.assertIs(bool(result.iloc[0]), True)
        self.assertIs(bool(result.iloc[1]), False)
        self.assertTrue(pd.isna(result.iloc[2]))

    def test_invalid_unknown_policy_fails_even_without_unknown_values(self) -> None:
        with self.assertRaisesRegex(TEXT.CategoryContractError, "unknown policy"):
            TEXT.categorize_text(
                pd.Series(["basic"], dtype="string"),
                categories=["basic"],
                unknown="typo",
            )

    def test_unknown_category_fails_with_evidence(self) -> None:
        with self.assertRaisesRegex(
            TEXT.CategoryContractError,
            "unknown categories: 'enterprise': 2",
        ):
            TEXT.categorize_text(
                pd.Series(["basic", "enterprise", "enterprise"], dtype="string"),
                categories=["basic", "premium"],
            )

    def test_other_policy_has_stable_schema_without_current_unknowns(self) -> None:
        result = TEXT.categorize_text(
            pd.Series(["basic", "premium"], dtype="string"),
            categories=["basic", "premium"],
            unknown="other",
        )
        self.assertEqual(result.values.cat.categories.tolist(), ["basic", "premium", "other"])
        self.assertEqual(result.audit["unknown_count"], 0)
        self.assertEqual(result.audit["canonical_counts"]["other"], 0)

    def test_other_policy_maps_unknown_but_not_missing(self) -> None:
        result = TEXT.categorize_text(
            pd.Series(["basic", "enterprise", None, "   "], dtype="string"),
            categories=["basic", "premium"],
            unknown="other",
        )
        rendered = result.values.astype("string").tolist()
        self.assertEqual(rendered[:2], ["basic", "other"])
        self.assertTrue(pd.isna(rendered[2]))
        self.assertTrue(pd.isna(rendered[3]))
        self.assertEqual(result.audit["unknown_values"], {"enterprise": 1})
        self.assertEqual(result.audit["source_missing_count"], 1)
        self.assertEqual(result.audit["blank_to_missing_count"], 1)
        self.assertEqual(result.audit["result_missing_count"], 2)

    def test_category_contract_reports_normalization_changes(self) -> None:
        result = TEXT.categorize_text(
            pd.Series([" Premium ", "PREMIUM", "basic"], dtype="string"),
            categories=["basic", "premium"],
        )
        self.assertEqual(result.audit["canonical_counts"], {"basic": 1, "premium": 2})
        changes = {
            (item["raw"], item["canonical"], item["count"])
            for item in result.audit["normalization_changes"]
        }
        self.assertIn((" Premium ", "premium", 1), changes)
        self.assertIn(("PREMIUM", "premium", 1), changes)

    def test_ordered_category_uses_declared_business_order(self) -> None:
        result = TEXT.categorize_text(
            pd.Series(["premium", "trial", "basic"], dtype="string"),
            categories=["trial", "basic", "premium"],
            ordered=True,
        )
        self.assertTrue(result.values.cat.ordered)
        self.assertEqual(
            result.values.sort_values().astype("string").tolist(),
            ["trial", "basic", "premium"],
        )

    def test_missing_has_code_minus_one_and_is_not_a_category(self) -> None:
        result = TEXT.categorize_text(
            pd.Series(["basic", None], dtype="string"),
            categories=["basic", "premium"],
        )
        self.assertEqual(result.values.cat.categories.tolist(), ["basic", "premium"])
        self.assertEqual(result.values.cat.codes.tolist(), [0, -1])

    def test_vocabulary_must_be_unique_and_canonical(self) -> None:
        with self.assertRaisesRegex(TEXT.CategoryContractError, "unique"):
            TEXT.categorize_text(
                pd.Series(["basic"], dtype="string"),
                categories=["basic", "basic"],
            )
        with self.assertRaisesRegex(TEXT.CategoryContractError, "canonical"):
            TEXT.categorize_text(
                pd.Series(["basic"], dtype="string"),
                categories=["Basic"],
            )

    def test_other_policy_does_not_mutate_declared_categories(self) -> None:
        categories = ["basic", "premium"]
        TEXT.categorize_text(
            pd.Series(["enterprise"], dtype="string"),
            categories=categories,
            unknown="other",
        )
        self.assertEqual(categories, ["basic", "premium"])

    def test_tiny_items_collapse_to_declared_vocabulary(self) -> None:
        items = pd.read_csv(DATA / "order_items.csv")
        result = TEXT.categorize_text(
            items["category"],
            categories=["add_on", "subscription", "service"],
            aliases={"addon": "add_on"},
            unknown="other",
        )
        self.assertEqual(str(result.values.dtype), "category")
        self.assertEqual(result.audit["canonical_counts"]["add_on"], 4)
        self.assertEqual(result.audit["unknown_count"], 0)


if __name__ == "__main__":
    unittest.main()
