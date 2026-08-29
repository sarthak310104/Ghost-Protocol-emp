"""
Minimal pydantic models for the OTLP/HTTP+JSON export request shape
(https://opentelemetry.io/docs/specs/otlp/#otlphttp). We deliberately only
model the fields Ghost Protocol actually consumes -- an OTel collector's
`otlphttp` exporter can point straight at our /v1/traces and /v1/metrics
endpoints with no custom config beyond the endpoint URL and an auth
header, which is the entire "onboarding" flow for a new company.
"""
from typing import Any

from pydantic import BaseModel, Field


class AnyValue(BaseModel):
    stringValue: str | None = None
    intValue: str | int | None = None
    doubleValue: float | None = None
    boolValue: bool | None = None


class KeyValue(BaseModel):
    key: str
    value: AnyValue = Field(default_factory=AnyValue)


class Resource(BaseModel):
    attributes: list[KeyValue] = Field(default_factory=list)


class Span(BaseModel):
    traceId: str
    spanId: str
    parentSpanId: str | None = None
    name: str
    kind: int | None = None
    startTimeUnixNano: str
    endTimeUnixNano: str
    attributes: list[KeyValue] = Field(default_factory=list)
    status: dict[str, Any] = Field(default_factory=dict)


class ScopeSpans(BaseModel):
    spans: list[Span] = Field(default_factory=list)


class ResourceSpans(BaseModel):
    resource: Resource = Field(default_factory=Resource)
    scopeSpans: list[ScopeSpans] = Field(default_factory=list)


class TracesExportRequest(BaseModel):
    resourceSpans: list[ResourceSpans] = Field(default_factory=list)


class NumberDataPoint(BaseModel):
    timeUnixNano: str
    asDouble: float | None = None
    asInt: str | int | None = None
    attributes: list[KeyValue] = Field(default_factory=list)


class Metric(BaseModel):
    name: str
    unit: str | None = None
    gauge: dict[str, Any] | None = None
    sum: dict[str, Any] | None = None

    def data_points(self) -> list[NumberDataPoint]:
        source = self.gauge or self.sum
        if not source:
            return []
        return [NumberDataPoint(**dp) for dp in source.get("dataPoints", [])]


class ScopeMetrics(BaseModel):
    metrics: list[Metric] = Field(default_factory=list)


class ResourceMetrics(BaseModel):
    resource: Resource = Field(default_factory=Resource)
    scopeMetrics: list[ScopeMetrics] = Field(default_factory=list)


class MetricsExportRequest(BaseModel):
    resourceMetrics: list[ResourceMetrics] = Field(default_factory=list)
