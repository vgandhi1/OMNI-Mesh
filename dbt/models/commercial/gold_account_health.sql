-- Gold: per-plan churn & revenue rollup for CLV analysis (no raw customer id).
select
    plan_tier,
    count(*) as account_count,
    round(avg(monthly_revenue), 2) as avg_monthly_revenue,
    round(avg(lifetime_value), 2) as avg_lifetime_value,
    sum(case when churned_flag then 1 else 0 end) as churned_count,
    round(avg(case when churned_flag then 1.0 else 0.0 end), 3) as churn_rate
from {{ ref('silver_subscription_events') }}
group by 1
order by 1
