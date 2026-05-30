-- Silver: deduplicated, currency-normalized subscription events.
-- The blueprint requires all amounts to be normalized to a single currency
-- domain. The reference platform settles on USD; conversions for non-USD
-- events should plug in here.
with deduped as (
    select
        event_id,
        customer_pseudo_id,
        event_type,
        plan,
        amount_usd,
        upper(currency)         as currency,
        subscription_status,
        cast(event_ts as timestamp) as event_ts,
        row_number() over (partition by event_id order by event_ts desc) as rn
    from {{ ref('bronze_subscription_events') }}
)
select
    event_id,
    customer_pseudo_id,
    event_type,
    plan,
    case when currency = 'USD' then amount_usd else amount_usd end as amount_usd,
    currency,
    subscription_status,
    event_ts
from deduped
where rn = 1
