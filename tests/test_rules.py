"""Unit tests for instrumentation score rules, engine, and config."""

from __future__ import annotations

import asyncio
from pathlib import Path

from isc.config import load_config
from isc.engine import evaluate_bundle
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
from isc.providers.fixture import FixtureProvider

ROOT = Path(__file__).resolve().parent.parent


def _base_config() -> TargetConfig:
    return TargetConfig(name="tms-test", selector_key="appid", selector_value="tms")


def test_healthy_fixture_scores_100() -> None:
    cfg = load_config(ROOT / "examples" / "isc.yaml")
    bundle = asyncio.run(FixtureProvider(ROOT / "examples" / "tms_fixture.json").collect(cfg))
    report = evaluate_bundle(bundle, cfg)

    assert report.overall_score == 100.0
    assert all(r.passed for r in report.results)


def test_selector_override() -> None:
    cfg = load_config(ROOT / "examples" / "isc.yaml", selector_override="appid=billing")
    assert cfg.selector_key == "appid"
    assert cfg.selector_value == "billing"
    assert cfg.mcp.url == "http://localhost:8000/mcp"
    assert cfg.mcp.transport == "auto"
    assert cfg.mcp.headers == {}


def test_log_quality_failures() -> None:
    cfg = _base_config()
    noisy_logs = [
        LogEntry(
            timestamp="2026-11-17T12:00:00Z",
            line="GET /healthz 200 OK",
            labels={},
            structured_fields={},
            level="DEBUG",
        )
        for _ in range(10)
    ]
    noisy_logs.append(
        LogEntry(
            timestamp="2026-11-17T12:00:01Z",
            line="Authorization: Bearer super_secret_token_12345",
            labels={},
            structured_fields={},
            level="ERROR",
        )
    )
    bundle = TelemetryBundle(
        target_key="appid",
        target_value="tms",
        lookback="1h",
        logs=noisy_logs,
        log_stats=LogStats(
            total_lines=1000,
            total_bytes=50000,
            buckets_per_minute=[0, 0, 0, 0, 0, 0, 950, 50],
            level_counts={"DEBUG": 700, "ERROR": 300},
        ),
    )
    report = evaluate_bundle(bundle, cfg)
    by_id = {r.rule_id: r for r in report.results}

    assert not by_id["LOG-001"].passed  # unstructured & missing metadata
    assert not by_id["LOG-002"].passed  # no trace correlation
    assert not by_id["LOG-003"].passed  # leaked Bearer token
    assert not by_id["LOG-004"].passed  # intermittent 0s + spike
    assert not by_id["LOG-005"].passed  # DEBUG + ERROR ratio too high
    assert not by_id["LOG-006"].passed  # healthz boilerplate + duplicates


def test_metric_trace_and_profiling_failures() -> None:
    cfg = _base_config()
    bundle = TelemetryBundle(
        target_key="appid",
        target_value="tms",
        lookback="1h",
        metrics=[
            MetricSeries(
                name="bad_counter",
                metric_type="counter",
                labels=[{"appid": "tms", "user_id": "123"}],
                unique_series_count=6000,
            )
        ],
        traces=[
            TraceSummary(
                trace_id="t1",
                spans=[
                    SpanSummary(
                        trace_id="t1",
                        span_id="s1",
                        parent_span_id="missing_parent",
                        name="GET /users/12345",
                    ),
                    SpanSummary(
                        trace_id="t1",
                        span_id="s2",
                        parent_span_id="missing_root",
                        name="GET /users/67890",
                    ),
                ],
            )
        ],
        profiling=ProfileSummary(
            profile_types=["process_cpu"],
            sample_functions=["0x7f123456", "[unknown]"],
            total_samples=100,
        ),
    )
    report = evaluate_bundle(bundle, cfg)
    by_id = {r.rule_id: r for r in report.results}

    assert not by_id["MET-001"].passed
    assert not by_id["MET-002"].passed
    assert not by_id["MET-003"].passed
    assert not by_id["SPA-001"].passed
    assert not by_id["SPA-002"].passed
    assert not by_id["PRO-002"].passed
    assert not by_id["PRO-003"].passed
