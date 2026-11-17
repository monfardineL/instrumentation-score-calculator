"""Data models for telemetry bundles, rules, configuration, and score reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Impact(str, Enum):
    """Rule impact levels aligned with instrumentation-score/spec."""

    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"

    @property
    def weight(self) -> int:
        return {
            Impact.CRITICAL: 4,
            Impact.IMPORTANT: 2,
            Impact.NORMAL: 1,
        }[self]


class Signal(str, Enum):
    """Telemetry signal categories."""

    RESOURCE = "RES"
    METRICS = "MET"
    LOGS = "LOG"
    TRACES = "SPA"
    PROFILING = "PRO"


@dataclass(slots=True)
class DatasourceConfig:
    """Explicit Grafana datasource UIDs per signal to scope queries."""

    prometheus_uid: str | None = None
    loki_uid: str | None = None
    tempo_uid: str | None = None
    pyroscope_uid: str | None = None


@dataclass(slots=True)
class SelectorMapping:
    """How the target key-value selector maps to each signal's label/attribute."""

    prometheus_label: str | None = None
    loki_label: str | None = None
    tempo_attribute: str | None = None
    pyroscope_label: str | None = None


@dataclass(slots=True)
class LogQualityThresholds:
    """Configurable thresholds for log quality evaluation."""

    sample_limit: int = 1000
    min_logs_per_hour: int = 1
    max_logs_per_minute: int = 10000
    max_debug_ratio: float = 0.50
    max_error_ratio: float = 0.20
    max_duplicate_ratio: float = 0.40
    max_boilerplate_ratio: float = 0.30
    min_structured_ratio: float = 0.80
    min_trace_correlation_ratio: float = 0.50
    boilerplate_patterns: list[str] = field(
        default_factory=lambda: [
            r"^GET /(health|healthz|ready|readyz|livez|metrics)\b",
            r"^ping\b",
            r"^heartbeat\b",
        ]
    )


@dataclass(slots=True)
class MCPConfig:
    """Configuration for connecting to mcp-grafana (remote HTTP/SSE or local stdio)."""

    transport: str = "auto"  # auto | streamable_http | sse | stdio
    url: str | None = None
    url_env: str = "GRAFANA_MCP_URL"
    headers: dict[str, str] = field(default_factory=dict)
    command: str = "uvx"
    args: list[str] = field(default_factory=lambda: ["mcp-grafana"])
    grafana_url_env: str = "GRAFANA_URL"
    grafana_token_env: str = "GRAFANA_SERVICE_ACCOUNT_TOKEN"
    extra_env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TargetConfig:
    """Top-level configuration for scoring a specific application context."""

    name: str
    selector_key: str
    selector_value: str
    lookback: str = "1h"
    datasources: DatasourceConfig = field(default_factory=DatasourceConfig)
    selector_mapping: SelectorMapping = field(default_factory=SelectorMapping)
    log_thresholds: LogQualityThresholds = field(default_factory=LogQualityThresholds)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    disabled_rules: list[str] = field(default_factory=list)

    def label_for(self, signal: Signal) -> str:
        """Return the label/attribute name to filter on for a given signal."""
        mapping = {
            Signal.METRICS: self.selector_mapping.prometheus_label,
            Signal.LOGS: self.selector_mapping.loki_label,
            Signal.TRACES: self.selector_mapping.tempo_attribute,
            Signal.PROFILING: self.selector_mapping.pyroscope_label,
        }
        return mapping.get(signal) or self.selector_key


@dataclass(slots=True)
class MetricSeries:
    """Sampled Prometheus/Mimir metric metadata and label sets."""

    name: str
    metric_type: str | None = None
    unit: str | None = None
    help_text: str | None = None
    labels: list[dict[str, str]] = field(default_factory=list)
    unique_series_count: int = 0


@dataclass(slots=True)
class LogEntry:
    """A single sampled log record from Loki."""

    timestamp: str
    line: str
    labels: dict[str, str] = field(default_factory=dict)
    structured_fields: dict[str, Any] = field(default_factory=dict)
    level: str | None = None
    trace_id: str | None = None
    span_id: str | None = None


@dataclass(slots=True)
class LogStats:
    """Aggregate Loki statistics over the lookback window (via metric queries/stats)."""

    total_lines: int = 0
    total_bytes: int = 0
    buckets_per_minute: list[int] = field(default_factory=list)
    level_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class SpanSummary:
    """Sampled span metadata from Tempo."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    service_name: str | None = None
    status_code: str | None = None
    resource_attributes: dict[str, Any] = field(default_factory=dict)
    span_attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TraceSummary:
    """Sampled trace from Tempo."""

    trace_id: str
    spans: list[SpanSummary] = field(default_factory=list)


@dataclass(slots=True)
class ProfileSummary:
    """Pyroscope profiling summary for the target."""

    profile_types: list[str] = field(default_factory=list)
    labels_present: dict[str, list[str]] = field(default_factory=dict)
    sample_functions: list[str] = field(default_factory=list)
    total_samples: int = 0


@dataclass(slots=True)
class TelemetryBundle:
    """All telemetry collected for a single target evaluation."""

    target_key: str
    target_value: str
    lookback: str
    metrics: list[MetricSeries] = field(default_factory=list)
    logs: list[LogEntry] = field(default_factory=list)
    log_stats: LogStats = field(default_factory=LogStats)
    traces: list[TraceSummary] = field(default_factory=list)
    profiling: ProfileSummary = field(default_factory=ProfileSummary)
    collection_errors: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RuleResult:
    """Evaluation result of a single instrumentation rule."""

    rule_id: str
    signal: Signal
    title: str
    impact: Impact
    passed: bool
    skipped: bool = False
    score_ratio: float = 1.0  # 1.0 = full pass, 0.0 = fail, 0..1 for partial
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    remediation: str = ""


@dataclass(slots=True)
class ScoreReport:
    """Final aggregated instrumentation score report."""

    target_name: str
    selector: str
    lookback: str
    overall_score: float
    signal_scores: dict[str, float]
    results: list[RuleResult]
    collection_errors: dict[str, str] = field(default_factory=dict)
