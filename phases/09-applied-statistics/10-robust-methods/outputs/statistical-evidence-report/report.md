# Statistical Evidence Report

## Question

Can we trust early activation, revenue, association and regression evidence from the current user-level sample?

## Main Answer

The package supports association-only statistical evidence with explicit limitations. Point estimates and intervals are available, but sampling coverage warnings, weak tiny-sample intervals, bootstrap discreteness and regression diagnostics prevent causal or production-decision claims.

## Evidence

- Sampling audit: `sampling/sampling-audit.json`.
- Distribution cards: `distributions/distribution-cards.json`.
- Point estimates and bias/variance: `estimates/point-estimates.csv`, `estimates/bias-variance.csv`.
- Formula and bootstrap intervals: `estimates/confidence-intervals.csv`, `estimates/bootstrap-intervals.json`.
- Correlation audit: `association/correlation-audit.json`.
- OLS inference and diagnostics: `regression/coefficients.csv`, `regression/diagnostics.json`.
- Robust sensitivity: `robustness/robust-estimates.csv`, `robustness/sensitivity.json`.

## Robustness

Leave-one-out revenue max absolute delta is `196.0` RUB. Regression warning flags: `high_cook_distance, residual_scale_related_to_fitted, too_few_rows_for_breusch_pagan, too_few_rows_for_residual_normality_test`.

## Limitations

Coverage bias, non-response, tiny sample size, observational design, formula interval under-coverage and regression specification warnings remain active. The next decision should use this as evidence preparation, not as an experiment result.
