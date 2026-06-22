# Customer revenue health mart design brief

## Business question

Product and finance need a trusted customer-level mart for activation, paid revenue,
refund and support-risk decisions. The first version publishes
`mart_customer_revenue_health` at one row per registered user.

## Layer map

```text
raw_users, raw_orders, raw_order_items
        |
        v
stg_users, stg_orders, stg_order_items
        |
        v
int_order_line_revenue
        |
        v
mart_customer_revenue_health
```

The mart does not read raw sources directly. Staging models keep source grain and
intermediate models hold reusable joins and reconciliation.

## Publication rule

`mart_customer_revenue_health` can be published only when primary-key tests, source
contract checks and revenue reconciliation pass. Warning checks such as freshness watch
must be visible in the handoff, but they do not silently rewrite the mart.

## Known limitations

- Subscription SCD history is deferred to the snapshot lesson.
- Support tickets are present in raw data but not part of the first mart contract.
- Currency conversion appears in raw sources and will become a dedicated intermediate
  model later in the phase.
