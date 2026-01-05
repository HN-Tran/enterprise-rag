"""OpenTelemetry tracing and metrics for observability."""

from __future__ import annotations

from typing import TYPE_CHECKING

from enterprise_rag.config import settings
from enterprise_rag.log import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = get_logger(__name__)

# Global tracer (initialized lazily)
_tracer = None


def setup_telemetry(app: "FastAPI") -> None:
    """Initialize OpenTelemetry tracing with Jaeger exporter.

    Call this during FastAPI startup if OTEL_ENDPOINT is configured.
    """
    if not settings.OTEL_ENDPOINT:
        logger.info("telemetry_disabled", reason="OTEL_ENDPOINT not configured")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Create resource with service info
        resource = Resource.create(
            {
                "service.name": "enterprise-rag",
                "service.version": "0.2.0",
            }
        )

        # Set up tracer provider
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT, insecure=True)
        )
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        # Store global tracer
        global _tracer
        _tracer = trace.get_tracer(__name__)

        # Auto-instrument FastAPI
        FastAPIInstrumentor.instrument_app(app)

        # Auto-instrument requests library (for LLM/embedding calls)
        RequestsInstrumentor().instrument()

        logger.info(
            "telemetry_enabled",
            endpoint=settings.OTEL_ENDPOINT,
            service="enterprise-rag",
        )

    except ImportError as e:
        logger.warning("telemetry_import_error", error=str(e))
    except Exception as e:
        logger.error("telemetry_setup_error", error=str(e))


def get_tracer():
    """Get the global tracer for manual span creation.

    Returns None if telemetry is not configured.

    Usage:
        tracer = get_tracer()
        if tracer:
            with tracer.start_as_current_span("my_operation") as span:
                span.set_attribute("key", "value")
                # ... do work
    """
    return _tracer


def trace_operation(name: str):
    """Decorator for tracing a function.

    Usage:
        @trace_operation("retrieve_documents")
        def retrieve(query: str):
            ...
    """
    from functools import wraps
    from typing import Callable, TypeVar

    F = TypeVar("F", bound=Callable)

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            if tracer is None:
                return func(*args, **kwargs)

            with tracer.start_as_current_span(name) as span:
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    raise

        return wrapper  # type: ignore

    return decorator


def shutdown_telemetry() -> None:
    """Shutdown telemetry and flush pending spans.

    Call this during FastAPI shutdown.
    """
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
            logger.info("telemetry_shutdown")
    except Exception as e:
        logger.warning("telemetry_shutdown_error", error=str(e))
