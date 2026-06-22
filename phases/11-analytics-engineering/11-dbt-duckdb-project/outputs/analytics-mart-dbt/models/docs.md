{% docs __analytics_mart_dbt__ %}

# Customer revenue health analytics mart

This dbt-duckdb release package demonstrates how an analytics engineering mart should explain itself:
sources declare freshness and source ownership, models describe grain and consumer
contracts, tests name the risk they protect, snapshots document validity windows, and
exposures connect downstream decisions back to the dbt DAG.

{% enddocs %}

{% docs mart_customer_revenue_health_docs %}

Customer-level mart for revenue health review. The grain is one active, non-deleted user.
Revenue is converted to RUB, refunds and support tickets are kept visible, and
`revenue_health_segment` is a triage label for customer success and product finance.

Use this mart for dashboard-level questions, not for raw order reconciliation. For source
reconciliation use the singular data tests and the daily revenue fact.

{% enddocs %}

{% docs subscription_history_docs %}

Readable subscription SCD type 2 history built from `subscription_status_snapshot`.
Each row is a subscription version with `valid_from`, `valid_to`, `dbt_scd_id`, and
`is_current`. A noisy source reload must not create a new version unless one of the
business state columns changes.

{% enddocs %}

{% docs customer_revenue_health_dashboard_docs %}

Executive dashboard that monitors customer revenue health, daily paid revenue, refund
pressure, subscription state, and support load. Every headline claim must be traceable to
`mart_customer_revenue_health`, `fct_order_revenue_daily`, or `int_subscription_history`
and must carry a named owner.

{% enddocs %}
