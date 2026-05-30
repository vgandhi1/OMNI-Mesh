-- Gold: per-customer CLV, MRR contribution and churn-risk classification.
-- These are the metric names called out in the blueprint:
--   customer_lifetime_value, mrr_churn_risk.
with paid_events as (
    select *
    from {{ ref('silver_subscription_events') }}
    where event_type in ('subscription.created', 'invoice.payment_failed')
),
aggregates as (
    select
        customer_pseudo_id,
        max(plan)                         as latest_plan,
        max(subscription_status)          as latest_status,
        sum(amount_usd)                   as lifetime_revenue_usd,
        count_if(event_type = 'invoice.payment_failed') as payment_failures,
        min(event_ts)                     as first_seen_ts,
        max(event_ts)                     as last_seen_ts
    from paid_events
    group by 1
)
select
    customer_pseudo_id,
    latest_plan,
    latest_status,
    lifetime_revenue_usd as customer_lifetime_value,
    case
        when latest_status = 'canceled' then 'churned'
        when latest_status = 'past_due' or payment_failures >= 2 then 'high_risk'
        when latest_status = 'trialing' then 'evaluating'
        else 'healthy'
    end as mrr_churn_risk,
    first_seen_ts,
    last_seen_ts
from aggregates
