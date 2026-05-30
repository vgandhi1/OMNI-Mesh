"""Phase 5 — OpenTelemetry tracer bootstrap.

Provides a single ``start_span`` helper that the rest of the codebase uses to
wrap dbt invocations, embedding runs, and RAG queries. The exporter writes
spans to stdout for the local demo; in production swap in an OTLP exporter
pointed at Datadog / Honeycomb / Tempo.
"""

from __future__ import annotations

import contextlib
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

from scripts._config import get_settings

_SETTINGS = get_settings()
_PROVIDER = TracerProvider(
    resource=Resource.create(
        {
            "service.name": _SETTINGS.otel_service_name,
            "service.namespace": "heal-mesh",
            "deployment.environment": "local-demo",
        }
    )
)
_PROVIDER.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(_PROVIDER)

_TRACER = trace.get_tracer("heal_mesh")


@contextlib.contextmanager
def start_span(name: str) -> Iterator[trace.Span]:
    with _TRACER.start_as_current_span(name) as span:
        yield span
