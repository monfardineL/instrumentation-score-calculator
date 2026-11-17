"""Metrics rules (MET-*) for Prometheus/Mimir OTLP-ingested metrics."""

from __future__ import annotations

import re

from isc.models import Impact, RuleResult, Signal, TargetConfig, TelemetryBundle
from isc.rules.base import register_rule, skipped_result

_VALID_METRIC_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_HIGH_CARDINALITY_LABELS = {"trace_id", "span_id", "request_id", "user_id", "session_id", "uuid"}


@register_rule(
    rule_id="MET-001",
    signal=Signal.METRICS,
    title="Metric naming conventions",
    impact=Impact.NORMAL,
    description="Counter metrics should end with _total and follow Prometheus/OTel naming conventions.",
)
def check_metric_naming(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.metrics:
        return skipped_result(
            "MET-001", Signal.METRICS, "Metric naming conventions", Impact.NORMAL,
            "No metrics collected for target.",
        )

    bad: list[str] = []
    for m in bundle.metrics:
        if not _VALID_METRIC_NAME_RE.match(m.name):
            bad.append(f"{m.name} (invalid characters)")
        elif m.metric_type == "counter" and not m.name.endswith("_total"):
            bad.append(f"{m.name} (counter missing _total suffix)")

    ratio = max(0.0, 1.0 - (len(bad) / len(bundle.metrics)))
    passed = len(bad) == 0
    return RuleResult(
        rule_id="MET-001",
        signal=Signal.METRICS,
        title="Metric naming conventions",
        impact=Impact.NORMAL,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=(
            f"All {len(bundle.metrics)} metrics follow naming conventions."
            if passed
            else f"{len(bad)}/{len(bundle.metrics)} metrics violate naming conventions."
        ),
        evidence=bad[:5],
        remediation="Ensure counters end with `_total` and use snake_case metric names.",
    )


@register_rule(
    rule_id="MET-002",
    signal=Signal.METRICS,
    title="Metric unit and help metadata present",
    impact=Impact.IMPORTANT,
    description="Metrics should expose unit/help metadata from OTel instruments.",
)
def check_metric_metadata(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.metrics:
        return skipped_result(
            "MET-002", Signal.METRICS, "Metric unit and help metadata present", Impact.IMPORTANT,
            "No metrics collected for target.",
        )

    missing = [m.name for m in bundle.metrics if not m.help_text and not m.unit]
    ratio = max(0.0, 1.0 - (len(missing) / len(bundle.metrics)))
    passed = len(missing) == 0
    return RuleResult(
        rule_id="MET-002",
        signal=Signal.METRICS,
        title="Metric unit and help metadata present",
        impact=Impact.IMPORTANT,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=(
            "All metrics include unit/help metadata."
            if passed
            else f"{len(missing)}/{len(bundle.metrics)} metrics lack unit and help metadata."
        ),
        evidence=missing[:5],
        remediation="Set `WithDescription` and `WithUnit` on OTel metric instruments and enable `send_metadata` in Prometheus remote write.",
    )


@register_rule(
    rule_id="MET-003",
    signal=Signal.METRICS,
    title="Avoid high-cardinality metric labels",
    impact=Impact.CRITICAL,
    description="Metrics must not attach unbounded identifiers (trace_id, user_id, request_id) or exceed series thresholds.",
)
def check_metric_cardinality(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.metrics:
        return skipped_result(
            "MET-003", Signal.METRICS, "Avoid high-cardinality metric labels", Impact.CRITICAL,
            "No metrics collected for target.",
        )

    violations: list[str] = []
    for m in bundle.metrics:
        for lbl in m.labels:
            risky = _HIGH_CARDINALITY_LABELS.intersection(lbl.keys())
            if risky:
                violations.append(f"{m.name} has high-cardinality labels: {', '.join(sorted(risky))}")
                break
        if m.unique_series_count > 5000:
            violations.append(f"{m.name} has {m.unique_series_count} active series (>5000)")

    passed = len(violations) == 0
    ratio = max(0.0, 1.0 - (len(violations) / len(bundle.metrics)))
    return RuleResult(
        rule_id="MET-003",
        signal=Signal.METRICS,
        title="Avoid high-cardinality metric labels",
        impact=Impact.CRITICAL,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=(
            "No high-cardinality metric labels or series explosions detected."
            if passed
            else f"Detected {len(violations)} high-cardinality metric issue(s)."
        ),
        evidence=violations[:5],
        remediation="Drop unbounded attributes (user_id, request_id, trace_id) from metrics using OTel Views or Collector transform processor.",
    )
