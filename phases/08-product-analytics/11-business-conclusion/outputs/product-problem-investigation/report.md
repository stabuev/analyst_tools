# Product problem investigation

## Question

После изменения onboarding и paywall видим рост ранней активации, но жалобы и отмены подписки растут. Продолжать rollout, откатить изменение или поставить следующий проверяемый шаг?

## Recommendation

Recommended decision: `investigate`.

Pause automatic rollout and investigate the product-risk signals before choosing between
`continue` and `rollback`. The evidence supports a risk investigation, but it does not
prove a release effect.

## What We Know

Latest complete 7-day active audience row is `2026-06-09`: `3/7` users, rate `0.428571`.

Final funnel checkpoints:

- `activation_rate_7d` final step `feature_value_seen`: conversion_from_start `0.333333` on `2` units
- `paywall_to_trial_conversion_7d` final step `trial_started`: conversion_from_start `0.500000` on `2` units

Guardrail assessment:

- `support_ticket_rate_7d`: baseline `0.250000`, comparison `0.666667`, delta `0.416667`, status `breached`
- `subscription_cancel_rate_14d`: baseline `0.000000`, comparison `0.500000`, delta `0.500000`, status `breached`
- `refund_rate_7d`: baseline `0.000000`, comparison `0.500000`, delta `0.500000`, status `breached`

Anomaly summary:

- quality gates passed: `True`
- product signal candidates: `3`
- composition candidates: `1`
- calendar-effect candidates: `1`

## Evidence Map

| Claim | Statement | Artifacts | Limitation |
|---|---|---|---|
| `quality-gates-passed` | Freshness, duplicate, late-arrival and tracking completeness gates passed for the observation slice. | `metrics/anomalies.json`, `audits/event-quality.json` | Passing gates means the slice is interpretable; it does not prove a product mechanism. |
| `guardrails-breached` | 3 guardrail metrics breached with risk direction up_is_bad. | `metrics/guardrails.csv`, `metrics/anomalies.json` | A guardrail breach is a risk decision rule, not a causal estimate. |
| `anomaly-product-signals` | 3 anomaly candidates are classified as product_signal after gates passed. | `metrics/anomalies.json` | The class allows investigation of product behavior, not attribution to a release. |
| `composition-context` | 1 composition candidate points to mix or segment contribution. | `metrics/segments.csv`, `metrics/anomalies.json` | Composition explains where the aggregate moved, not why users changed behavior. |
| `calendar-context` | 1 calendar candidate coincides with the comparison period. | `metrics/anomalies.json` | Calendar coincidence is context for investigation, not proof. |

## What We Cannot Say

- We cannot say that release `R002` produced the risk movement from these observational diagnostics alone.
- We cannot choose rollback solely from the calendar match; the package needs release notes, platform rollout details and support/cancel/refund inspection.
- We cannot ignore guardrails just because activation-related inputs look useful.

## Next Steps

1. `inspect-android-paywall-release` (product + mobile): Support ticket rate and paywall complaints are split by platform, app_version and release cohort.
1. `review-cancellations-and-refunds` (monetization): Cancellation/refund reasons reconcile to subscription and order grains.
1. `prepare-experiment-if-clean` (analytics): A follow-up experiment or rollout holdout has explicit outcome, guardrails and decision rule.

## Package Contents

- `brief.md` - decision question and boundary.
- `metric-tree.json`, `metric-specs.json`, `tracking-plan.json` - contracts.
- `metrics/` - tables and anomaly report from phase lessons.
- `audits/` - event and metric quality checks for this package.
- `figures/` - static figures for guardrails and decomposition.
- `recommendation.json` - machine-readable decision, options, claims and next steps.
- `manifest.json` - SHA-256 manifest for every delivered file.
