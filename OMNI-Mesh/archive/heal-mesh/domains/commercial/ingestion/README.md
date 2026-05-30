# Commercial Domain · Ingestion

In production this directory holds the Fivetran / custom-webhook jobs that
land subscription lifecycle events into the Iceberg bronze table
`commercial_domain.subscription_events_bronze`.

Typical artifacts:

| File | Purpose |
| --- | --- |
| `stripe_webhook_handler.py` | Verified webhook receiver (`Stripe-Signature` HMAC check) |
| `app_store_server_notifications.py` | Apple In-App Purchase server notifications consumer |
| `fivetran_connector_overrides.sql` | Fivetran custom-connector SQL transforms |

In the local reference implementation the equivalent step is the
`scripts/generate_synthetic_data.py` Stripe-shaped event generator.
