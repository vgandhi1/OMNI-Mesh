"""Phase 1: Edge ingestion (OPC UA simulator + Kafka transport)."""

from .opc_ua_simulator import OpcUaSimulator, SensorReading

__all__ = ["OpcUaSimulator", "SensorReading"]
