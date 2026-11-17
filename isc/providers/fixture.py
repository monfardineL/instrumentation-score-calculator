"""Offline JSON fixture provider for testing and local development."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from isc.models import (
    LogEntry,
    LogStats,
    MetricSeries,
    ProfileSummary,
    SpanSummary,
    TargetConfig,
    TelemetryBundle,
    TraceSummary,
)


class FixtureProvider:
    """Loads telemetry from a local JSON file."""

    def __init__(self, fixture_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)

    async def collect(self, config: TargetConfig) -> TelemetryBundle:
        raw: dict[str, Any] = json.loads(self.fixture_path.read_text(encoding="utf-8"))

        metrics = [
            MetricSeries(
                name=m["name"],
                metric_type=m.get("metric_type"),
                unit=m.get("unit"),
                help_text=m.get("help_text"),
                labels=m.get("labels", []),
                unique_series_count=int(m.get("unique_series_count", len(m.get("labels", [])))),
            )
            for m in raw.get("metrics", [])
        ]

        logs = [
            LogEntry(
                timestamp=entry.get("timestamp", ""),
                line=entry.get("line", ""),
                labels=entry.get("labels", {}),
                structured_fields=entry.get("structured_fields", {}),
                level=entry.get("level"),
                trace_id=entry.get("trace_id"),
                span_id=entry.get("span_id"),
            )
            for entry in raw.get("logs", [])
        ]

        ls_raw = raw.get("log_stats") or {}
        log_stats = LogStats(
            total_lines=int(ls_raw.get("total_lines", len(logs))),
            total_bytes=int(ls_raw.get("total_bytes", sum(len(x.line) for x in logs))),
            buckets_per_minute=[int(v) for v in ls_raw.get("buckets_per_minute", [])],
            level_counts={str(k): int(v) for k, v in (ls_raw.get("level_counts") or {}).items()},
        )

        traces: list[TraceSummary] = []
        for t in raw.get("traces", []):
            spans = [
                SpanSummary(
                    trace_id=s.get("trace_id", t["trace_id"]),
                    span_id=s["span_id"],
                    parent_span_id=s.get("parent_span_id"),
                    name=s["name"],
                    service_name=s.get("service_name"),
                    status_code=s.get("status_code"),
                    resource_attributes=s.get("resource_attributes", {}),
                    span_attributes=s.get("span_attributes", {}),
                )
                for s in t.get("spans", [])
            ]
            traces.append(TraceSummary(trace_id=t["trace_id"], spans=spans))

        prof_raw = raw.get("profiling") or {}
        profiling = ProfileSummary(
            profile_types=list(prof_raw.get("profile_types", [])),
            labels_present=dict(prof_raw.get("labels_present", {})),
            sample_functions=list(prof_raw.get("sample_functions", [])),
            total_samples=int(prof_raw.get("total_samples", 0)),
        )

        return TelemetryBundle(
            target_key=raw.get("target_key", config.selector_key),
            target_value=raw.get("target_value", config.selector_value),
            lookback=raw.get("lookback", config.lookback),
            metrics=metrics,
            logs=logs,
            log_stats=log_stats,
            traces=traces,
            profiling=profiling,
            collection_errors=dict(raw.get("collection_errors", {})),
        )
