"""
Turns OTLP export requests into flat, JSON-serializable dicts. Kept
separate from the API route so it's independently testable and so the
same normalization logic can be reused if we ever accept OTLP/gRPC or
protobuf directly.
"""
import uuid

from app.ingestion.otlp_schemas import (
    AnyValue,
    KeyValue,
    MetricsExportRequest,
    TracesExportRequest,
)

_STATUS_CODE_MAP = {0: "UNSET", 1: "OK", 2: "ERROR"}


def _value(v: AnyValue) -> str | int | float | bool | None:
    if v.stringValue is not None:
        return v.stringValue
    if v.intValue is not None:
        return int(v.intValue)
    if v.doubleValue is not None:
        return v.doubleValue
    if v.boolValue is not None:
        return v.boolValue
    return None


def _attrs_to_dict(attrs: list[KeyValue]) -> dict:
    return {kv.key: _value(kv.value) for kv in attrs}


def _service_name(resource_attrs: dict) -> str:
    return str(resource_attrs.get("service.name", "unknown-service"))


def normalize_spans(payload: TracesExportRequest, workspace_id: uuid.UUID) -> list[dict]:
    out: list[dict] = []
    for rs in payload.resourceSpans:
        resource_attrs = _attrs_to_dict(rs.resource.attributes)
        service_name = _service_name(resource_attrs)

        for scope in rs.scopeSpans:
            for span in scope.spans:
                start_ns = int(span.startTimeUnixNano)
                end_ns = int(span.endTimeUnixNano)
                duration_ms = max(0.0, (end_ns - start_ns) / 1_000_000)

                out.append({
                    "id": str(uuid.uuid4()),
                    "workspace_id": str(workspace_id),
                    "trace_id": span.traceId,
                    "span_id": span.spanId,
                    "parent_span_id": span.parentSpanId,
                    "service_name": service_name,
                    "span_name": span.name,
                    "kind": str(span.kind) if span.kind is not None else "INTERNAL",
                    "started_at_unix_ns": start_ns,
                    "duration_ms": duration_ms,
                    "status_code": _STATUS_CODE_MAP.get((span.status or {}).get("code", 0), "UNSET"),
                    "attributes": _attrs_to_dict(span.attributes),
                })
    return out


def normalize_metrics(payload: MetricsExportRequest, workspace_id: uuid.UUID) -> list[dict]:
    out: list[dict] = []
    for rm in payload.resourceMetrics:
        resource_attrs = _attrs_to_dict(rm.resource.attributes)
        service_name = _service_name(resource_attrs)

        for scope in rm.scopeMetrics:
            for metric in scope.metrics:
                for dp in metric.data_points():
                    value = dp.asDouble if dp.asDouble is not None else (
                        float(dp.asInt) if dp.asInt is not None else 0.0
                    )
                    out.append({
                        "id": str(uuid.uuid4()),
                        "workspace_id": str(workspace_id),
                        "service_name": service_name,
                        "metric_name": metric.name,
                        "value": value,
                        "unit": metric.unit,
                        "recorded_at_unix_ns": int(dp.timeUnixNano),
                        "attributes": _attrs_to_dict(dp.attributes),
                    })
    return out
