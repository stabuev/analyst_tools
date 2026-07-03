# Model Card: trial-churn-risk-model-card-v0

## Model Details

- Package: trial-churn-ml-baseline-package-v0
- Model: random_forest_depth2_class_weight_balanced
- Type: sklearn Pipeline(ColumnTransformer, RandomForestClassifier)
- Generated at: 2026-07-03T11:00:00+03:00

## Intended Use

- prioritize support review for eligible trial users
- Decision action: send_one_retention_offer_or_no_offer
- Offer budget: 2 per scoring batch

## Out-of-Scope Uses

- causal_effect_of_offer
- automatic_account_action
- production_deployment_without_monitoring
- segment_readiness_claim_from_overall_metric

## Training And Evaluation Data

- Train rows: 4
- Validation rows: 3
- Test rows: 5
- Final holdout used for selection: False

## Metrics

- Precision at budget: 0.5
- Recall at budget: 1.0
- Overall error rate: 0.2
- False positives / false negatives: 1 / 0

## Calibration

- Method: validation_bin_map_with_laplace_smoothing
- Test Brier score: 0.079012
- Test log loss: 0.318608
- Test used for calibration: False

## Error Analysis

- Slice metric rows: 23
- Small-n slices: 19
- Hidden failure slices: 4
- platform=android
- acquisition_channel=organic
- business_cohort=trial_basic:RU
- score_band=low

## Limitations

- tiny_profile_not_production_sample
- hidden_segment_failure
- small_n_segment_metrics
- calibration_tiny_bins
- unknown_categories_bucketed
- no_causal_offer_effect
- model_artifact_security

## Ethical Considerations

The package documents a churn-risk baseline. It does not estimate the causal effect of a retention offer and does not approve automated actions.
The score can prioritize human review, but it must not be used as an automatic account action or as a causal offer-effect statement.

## Decision

- Status: review_required_before_production
- Allowed claim: baseline_package_ready_for_review
- Production requires:
- larger_test_sample
- monitoring_plan
- owner_signoff
- security_review_for_model_artifact
- experiment_or_causal_design_for_offer_effect

## Maintenance

- input schema and unknown-category rates
- precision/recall at offer budget
- calibration drift
- segment hidden failures
