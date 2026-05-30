# Telemetry Domain · Ingestion

In production this directory holds the streaming/batch ingest jobs that land
wearable IoT events into the Iceberg bronze table
`telemetry_domain.wearable_events_bronze`.

Typical artifacts:

| File | Purpose |
| --- | --- |
| `wearable_stream_to_iceberg.py` | Kinesis / Pub/Sub → Spark Structured Streaming → Iceberg writer |
| `device_backfill.py` | One-shot backfill of historical device exports |
| `dlq_replay.py` | Dead-letter-queue replay utility |

In the local reference implementation the equivalent step is
`scripts/generate_synthetic_data.py` followed by `scripts/bootstrap_iceberg.py`.
