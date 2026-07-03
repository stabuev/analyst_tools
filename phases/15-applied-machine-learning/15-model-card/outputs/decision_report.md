# ML Baseline Decision: trial-churn-ml-baseline-package-v0

- Status: review_required_before_production
- Package valid: true
- Blocking errors: none
- Warnings: upstream_warnings_propagated_to_model_card, segment_hidden_failures_block_production_claim, small_n_segment_claims_are_diagnostic_only, model_card_requires_human_review_before_production
- Allowed package claim: baseline_package_ready_for_review

## Production Blockers

- hidden_segment_failure
- calibration_tiny_bins

## Allowed Next Actions

- ship_baseline_package_for_review
- plan_offer_effect_experiment
- collect_larger_evaluation_sample
- prepare_phase_16_model_improvement

## Blocked Actions

- auto_deploy_model
- hide_small_n_slices
- drop_hidden_failure_slices
- choose_threshold_on_test

## Interpretation Boundary

The package documents a churn-risk baseline. It does not estimate the causal effect of a retention offer and does not approve automated actions.
This package is an offline baseline handoff, not a production deployment approval.
