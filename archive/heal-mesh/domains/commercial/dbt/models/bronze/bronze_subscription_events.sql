{{ config(materialized='view') }}

select
    event_id,
    customer_pseudo_id,
    event_type,
    plan,
    amount_usd,
    currency,
    subscription_status,
    event_ts
from {{ source('commercial_raw', 'subscription_events') }}
