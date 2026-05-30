-- Silver: subscription events with a simple lifetime-value estimate.
select
    timestamp,
    customer_id_hashed,
    plan_tier,
    region,
    monthly_revenue,
    tenure_months,
    churned_flag,
    round(monthly_revenue * tenure_months, 2) as lifetime_value
from {{ source('commercial_bronze', 'subscription_events') }}
where customer_id_hashed is not null
