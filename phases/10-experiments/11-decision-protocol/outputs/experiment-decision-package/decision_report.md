# Experiment Decision Report

Experiment: `exp_paywall_onboarding_android_2026_06`

Decision: `hold`

Owner: `growth-lead`

## Headline

Hold launch: primary metric missed direction and decision gates are not cleared.

## Primary Metric

- metric_id: `activation_rate_7d`
- raw_absolute_lift: `-0.666667`
- raw_p_value: `0.931981`
- bootstrap_ci: `[-1.0, 0.0]`
- cuped_adjusted_absolute_lift: `-0.416667`
- practical_status: `missed_primary_direction`

## Launch Requirements

- assignment_audit_valid: true
- randomization_health_ready: true
- power_plan_ready: true
- effect_analysis_ready: false
- multiple_testing_allows_launch: false
- peeking_ready_for_decision: false
- heterogeneity_report_valid: true
- no_guardrail_breach: true

## Decision Reasons

- missed_primary_direction
- guardrails_not_cleared
- observed_sample_below_power_plan
- assumption_warnings_present
- multiple_testing_does_not_allow_launch
- unplanned_decision_look:day_05_slack_peek
- unplanned_decision_look:day_10_dashboard_refresh
- peeking_audit_not_ready_for_decision
- segment_cells_below_minimum_size
- interaction_checks_insufficient_overlap

## Guardrails

- support_ticket_rate_7d: watch
- subscription_cancel_rate_14d: watch
- refund_rate_7d: watch

## Next Action

Do not launch from this experiment; keep the segment findings as exploratory inputs for a new pre-registered iteration.
