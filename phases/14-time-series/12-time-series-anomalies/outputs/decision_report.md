# Forecast package decision: active-subscriptions-forecast-package

- Status: diagnostic_forecast_package_not_production_release
- Forecast: active-subscriptions-4w-capacity / active_subscriptions
- Primary model: ets_additive_trend_seasonal_7
- Primary interval method: residual_quantile
- Package valid: true
- Blocking errors: none
- Warnings: upstream_warnings_propagated_to_decision

## Anomaly triage

- data_quality: 3
- calendar_expected: 8
- model_misspecification: 14
- product_signal_candidate: 0
- inconclusive: 16

## Interpretation boundary

This package can describe unusual observations relative to declared forecasts, intervals, data quality gates, and known calendar context.
It does not make a causal claim and it is not a production SLA release on the tiny profile.
