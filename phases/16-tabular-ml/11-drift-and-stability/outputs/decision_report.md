# Tabular ML decision report

Decision status: `keep_baseline`.
Monitoring status: `drift_watch_required`.

## Decision

Keep `random_forest_depth2_class_weight_balanced` as the selected baseline for the course handoff.
Do not promote `catboost_optuna_fixed_budget_logloss` because required promotion gates failed.

## Failed gates

- `candidate_threshold_cost_lte_baseline_best`
- `candidate_top_k_cost_lte_baseline_top_k`
- `candidate_has_approved_calibration`
- `segment_hidden_failures_absent`

## Boundaries

- This package does not make a causal claim about the retention offer.
- This package is not a production serving release or model registry approval.
- Drift and stability diagnostics are local offline checks, not online monitoring.

## Stability notes

- Feature drift status: `watch`.
- Importance stability status: `watch`.
- Segment stability status: `blocked_for_promotion`.
