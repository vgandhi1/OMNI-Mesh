"""Optional Kafka producer/consumer for streaming OPC UA telemetry.

These helpers are guarded by the `MFG_MESH_KAFKA_ENABLED` flag. The default
local demo bypasses Kafka entirely and pushes batches directly into Iceberg,
so the platform stays runnable in environments where Docker/Kafka isn't
available.

Partitioning: messages are keyed by `f"{facility_id}|{line_id}"` so that all
records for a given line land on the same partition and preserve PLC order.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Iterable, List

from ..config import get_config
from .opc_ua_simulator import SensorReading

logger = logging.getLogger(__name__)


def _require_confluent_kafka():
    try:
        from confluent_kafka import Consumer, Producer  # type: ignore

        return Producer, Consumer
    except ImportError as e:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Kafka mode requires the optional 'confluent-kafka' extra. "
            "Install with: pip install 'mfg-mesh[kafka]' or pip install confluent-kafka."
        ) from e


def publish_readings(readings: Iterable[SensorReading]) -> int:
    """Publish readings to Kafka. Returns the number of acknowledged messages."""
    cfg = get_config()
    if not cfg.kafka_enabled:
        raise RuntimeError("Kafka mode disabled. Set MFG_MESH_KAFKA_ENABLED=true.")

    Producer, _ = _require_confluent_kafka()
    producer = Producer({"bootstrap.servers": cfg.kafka_bootstrap})
    delivered = 0

    def _ack(err, msg):
        nonlocal delivered
        if err is not None:
            # Per logging rule: log a generic outcome, not raw payload.
            logger.warning("Kafka delivery failed for topic=%s partition=%s", msg.topic(), msg.partition())
            return
        delivered += 1

    for reading in readings:
        key = f"{reading.facility_id}|{reading.line_id}".encode("utf-8")
        value = json.dumps(reading.to_dict()).encode("utf-8")
        producer.produce(cfg.kafka_topic, key=key, value=value, on_delivery=_ack)
        producer.poll(0)

    producer.flush(timeout=10)
    logger.info("Published %d telemetry messages to topic=%s", delivered, cfg.kafka_topic)
    return delivered


def consume_batch(
    *,
    max_records: int = 500,
    timeout_s: float = 5.0,
    group_id: str = "mfg-mesh-lakehouse",
    handler: Callable[[List[SensorReading]], None] | None = None,
) -> List[SensorReading]:
    """Consume up to `max_records` from the configured Kafka topic.

    Returns the deserialized readings. If `handler` is provided, it is invoked
    with the consumed batch after commit.
    """
    cfg = get_config()
    if not cfg.kafka_enabled:
        raise RuntimeError("Kafka mode disabled. Set MFG_MESH_KAFKA_ENABLED=true.")

    _, Consumer = _require_confluent_kafka()
    consumer = Consumer(
        {
            "bootstrap.servers": cfg.kafka_bootstrap,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([cfg.kafka_topic])

    out: List[SensorReading] = []
    try:
        while len(out) < max_records:
            msg = consumer.poll(timeout=timeout_s)
            if msg is None:
                break
            if msg.error():
                logger.warning("Kafka consume error: %s", msg.error().code())
                continue
            try:
                payload = json.loads(msg.value().decode("utf-8"))
                out.append(SensorReading(**payload))
            except (json.JSONDecodeError, TypeError) as exc:
                # Never log raw payload - it could contain unexpected data.
                logger.warning("Dropping malformed Kafka message: %s", type(exc).__name__)
                continue
        if out:
            consumer.commit(asynchronous=False)
        if handler is not None:
            handler(out)
    finally:
        consumer.close()
    return out
