# Tabular ML interpretation report

Package: `trial-churn-tabular-ml-interpretation-package-v0`.

## Explanation stack

- CatBoost built-in importance, permutation importance and Tree SHAP are included as separate evidence views.
- All methods point to `platform` as the main diagnostic feature.
- Direction set: `loss_decrease_when_permuted,mixed,negative,positive`.
- This is model behavior evidence, not a causal claim about retention offers.

## Stability limits

- SHAP output space: `raw_margin`.
- SHAP background rows: `4`.
- Feature drift watch features: `acquisition_channel`.
- Segment hidden failure slices: `13`.

## Method disagreement

- `CatBoost PredictionValuesChange`: top feature `platform`, direction `positive`, status `watch`.
- `CatBoost LossFunctionChange`: top feature `platform`, direction `negative`, status `watch`.
- `Permutation importance`: top feature `platform`, direction `loss_decrease_when_permuted`, status `watch`.
- `Tree SHAP mean_abs`: top feature `platform`, direction `mixed`, status `watch`.

Interpretation is therefore diagnostic-only until larger validation data, stable feature mix and segment review are available.
