"""Log quality rules (LOG-*) for Loki OTLP logs."""

from __future__ import annotations

import re
from collections import Counter

from isc.models import Impact, LogEntry, RuleResult, Signal, TargetConfig, TelemetryBundle
from isc.rules.base import register_rule, skipped_result

_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"(password|passwd|secret|api_key|apikey|token)\s*[:=]\s*['\"]?[^\s'\"]{6,}", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

_STANDARD_LEVELS = {"TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"}


def _extract_message(entry: LogEntry) -> str:
    """Return the core message text of a log entry for noise/duplicate analysis."""
    if entry.structured_fields:
        for key in ("msg", "message", "body", "log"):
            val = entry.structured_fields.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return entry.line.strip()


@register_rule(
    rule_id="LOG-001",
    signal=Signal.LOGS,
    title="Structured logging and OTel metadata attached",
    impact=Impact.IMPORTANT,
    description="Logs should be structured (JSON/fields) and carry OTel resource/stream metadata.",
)
def check_log_structure_and_metadata(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.logs:
        return skipped_result(
            "LOG-001", Signal.LOGS, "Structured logging and OTel metadata attached", Impact.IMPORTANT,
            "No sampled logs collected for target.",
        )

    th = config.log_thresholds
    structured_count = sum(1 for log in bundle.logs if len(log.structured_fields) >= 2)
    metadata_count = sum(
        1
        for log in bundle.logs
        if len(log.labels) >= 1 and (
            "service.name" in log.labels
            or "service_name" in log.labels
            or config.label_for(Signal.LOGS) in log.labels
            or "service.name" in log.structured_fields
        )
    )

    struct_ratio = structured_count / len(bundle.logs)
    meta_ratio = metadata_count / len(bundle.logs)
    combined = (struct_ratio + meta_ratio) / 2.0
    passed = struct_ratio >= th.min_structured_ratio and meta_ratio >= 0.9

    evidence: list[str] = []
    if struct_ratio < th.min_structured_ratio:
        evidence.append(f"Structured JSON logs: {struct_ratio:.0%} (target >= {th.min_structured_ratio:.0%})")
    if meta_ratio < 0.9:
        evidence.append(f"Logs with service/target metadata: {meta_ratio:.0%} (target >= 90%)")

    return RuleResult(
        rule_id="LOG-001",
        signal=Signal.LOGS,
        title="Structured logging and OTel metadata attached",
        impact=Impact.IMPORTANT,
        passed=passed,
        score_ratio=round(combined, 2),
        summary=f"Structured: {struct_ratio:.0%}, metadata attached: {meta_ratio:.0%} across {len(bundle.logs)} sampled logs.",
        evidence=evidence,
        remediation="Emit JSON logs and configure the OTLP Collector Loki exporter to preserve resource attributes as labels/structured metadata.",
    )


@register_rule(
    rule_id="LOG-002",
    signal=Signal.LOGS,
    title="Log-to-trace correlation (trace_id / span_id)",
    impact=Impact.IMPORTANT,
    description="Logs should carry trace_id and span_id for correlation with Tempo traces.",
)
def check_log_trace_correlation(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.logs:
        return skipped_result(
            "LOG-002", Signal.LOGS, "Log-to-trace correlation (trace_id / span_id)", Impact.IMPORTANT,
            "No sampled logs collected for target.",
        )

    th = config.log_thresholds
    correlated = sum(1 for log in bundle.logs if log.trace_id and log.span_id)
    ratio = correlated / len(bundle.logs)
    passed = ratio >= th.min_trace_correlation_ratio
    return RuleResult(
        rule_id="LOG-002",
        signal=Signal.LOGS,
        title="Log-to-trace correlation (trace_id / span_id)",
        impact=Impact.IMPORTANT,
        passed=passed,
        score_ratio=round(min(1.0, ratio / max(th.min_trace_correlation_ratio, 0.01)), 2),
        summary=f"{correlated}/{len(bundle.logs)} sampled logs ({ratio:.0%}) include both trace_id and span_id.",
        evidence=[] if passed else [f"Target correlation ratio is >= {th.min_trace_correlation_ratio:.0%}"],
        remediation="Use OTel logging bridge/appender so active span context (trace_id, span_id) is injected into log records.",
    )


@register_rule(
    rule_id="LOG-003",
    signal=Signal.LOGS,
    title="No sensitive data or credentials in logs",
    impact=Impact.CRITICAL,
    description="Logs must not expose bearer tokens, passwords, API keys, or private keys.",
)
def check_log_secrets(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.logs:
        return skipped_result(
            "LOG-003", Signal.LOGS, "No sensitive data or credentials in logs", Impact.CRITICAL,
            "No sampled logs collected for target.",
        )

    flagged: list[str] = []
    for log in bundle.logs:
        for pat in _SECRET_PATTERNS:
            if pat.search(log.line):
                flagged.append(f"Matched pattern `{pat.pattern[:32]}...` at {log.timestamp}")
                break

    passed = len(flagged) == 0
    ratio = max(0.0, 1.0 - (len(flagged) / len(bundle.logs)))
    return RuleResult(
        rule_id="LOG-003",
        signal=Signal.LOGS,
        title="No sensitive data or credentials in logs",
        impact=Impact.CRITICAL,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=(
            f"No credential/token patterns found in {len(bundle.logs)} sampled logs."
            if passed
            else f"Found {len(flagged)} log line(s) matching sensitive credential patterns."
        ),
        evidence=flagged[:5],
        remediation="Redact secrets at the logger or with an OTLP Collector `redaction` / `transform` processor before Loki ingestion.",
    )


@register_rule(
    rule_id="LOG-004",
    signal=Signal.LOGS,
    title="Log volume and stability over time",
    impact=Impact.IMPORTANT,
    description="Evaluates total log volume and per-minute stability to catch silent dropouts or flooding spikes.",
)
def check_log_volume_over_time(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    stats = bundle.log_stats
    if stats.total_lines == 0 and not bundle.logs and not stats.buckets_per_minute:
        return RuleResult(
            rule_id="LOG-004",
            signal=Signal.LOGS,
            title="Log volume and stability over time",
            impact=Impact.IMPORTANT,
            passed=False,
            score_ratio=0.0,
            summary="0 logs received in the lookback window.",
            evidence=["No log entries or Loki stats found for target."],
            remediation="Verify OTLP Collector log pipeline and target selector labels.",
        )

    th = config.log_thresholds
    issues: list[str] = []
    total = stats.total_lines or len(bundle.logs)

    if total < th.min_logs_per_hour:
        issues.append(f"Low log volume: {total} lines (min expected {th.min_logs_per_hour}).")

    buckets = stats.buckets_per_minute
    if buckets:
        peak = max(buckets)
        avg = sum(buckets) / len(buckets)
        zero_buckets = sum(1 for b in buckets if b == 0)
        if peak > th.max_logs_per_minute:
            issues.append(f"Log flood detected: peak {peak} lines/min (> {th.max_logs_per_minute}).")
        if avg > 0 and peak > avg * 10 and peak > 100:
            issues.append(f"Severe log spike: peak {peak}/min vs avg {avg:.1f}/min.")
        if len(buckets) >= 5 and zero_buckets / len(buckets) > 0.5:
            issues.append(f"Intermittent logging: {zero_buckets}/{len(buckets)} minutes had 0 logs.")

    passed = len(issues) == 0
    ratio = 1.0 if passed else max(0.2, 1.0 - 0.3 * len(issues))
    return RuleResult(
        rule_id="LOG-004",
        signal=Signal.LOGS,
        title="Log volume and stability over time",
        impact=Impact.IMPORTANT,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=f"Total volume: {total} lines ({stats.total_bytes} bytes) across {len(buckets)} time buckets.",
        evidence=issues,
        remediation="Rate-limit noisy loggers or investigate pipeline dropouts in the OTLP Collector.",
    )


@register_rule(
    rule_id="LOG-005",
    signal=Signal.LOGS,
    title="Log level quality and distribution",
    impact=Impact.IMPORTANT,
    description="Logs should use standardized severity levels without DEBUG flooding or elevated ERROR ratios.",
)
def check_log_levels(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    counts = dict(bundle.log_stats.level_counts)
    if not counts and bundle.logs:
        for log in bundle.logs:
            lvl = (log.level or "UNKNOWN").upper()
            counts[lvl] = counts.get(lvl, 0) + 1

    if not counts:
        return skipped_result(
            "LOG-005", Signal.LOGS, "Log level quality and distribution", Impact.IMPORTANT,
            "No log level data available.",
        )

    th = config.log_thresholds
    total = sum(counts.values())
    unknown = sum(v for k, v in counts.items() if k not in _STANDARD_LEVELS)
    debug_cnt = counts.get("DEBUG", 0) + counts.get("TRACE", 0)
    error_cnt = counts.get("ERROR", 0) + counts.get("FATAL", 0) + counts.get("CRITICAL", 0)

    unknown_ratio = unknown / total
    debug_ratio = debug_cnt / total
    error_ratio = error_cnt / total

    issues: list[str] = []
    if unknown_ratio > 0.10:
        issues.append(f"{unknown_ratio:.0%} of logs lack a standard level (TRACE/DEBUG/INFO/WARN/ERROR).")
    if debug_ratio > th.max_debug_ratio:
        issues.append(f"DEBUG/TRACE ratio is {debug_ratio:.0%} (threshold <= {th.max_debug_ratio:.0%}).")
    if error_ratio > th.max_error_ratio:
        issues.append(f"ERROR/FATAL ratio is {error_ratio:.0%} (threshold <= {th.max_error_ratio:.0%}).")

    passed = len(issues) == 0
    ratio = 1.0 if passed else max(0.0, 1.0 - 0.35 * len(issues))
    dist_str = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
    return RuleResult(
        rule_id="LOG-005",
        signal=Signal.LOGS,
        title="Log level quality and distribution",
        impact=Impact.IMPORTANT,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=f"Level distribution ({total} total): {dist_str}",
        evidence=issues,
        remediation="Standardize `severity_text`/`level`, lower DEBUG verbosity in production, and investigate high ERROR rates.",
    )


@register_rule(
    rule_id="LOG-006",
    signal=Signal.LOGS,
    title="Log information relevance and low noise",
    impact=Impact.NORMAL,
    description="Logs should carry meaningful information rather than empty lines, duplicate spam, or healthcheck boilerplate.",
)
def check_log_relevance(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.logs:
        return skipped_result(
            "LOG-006", Signal.LOGS, "Log information relevance and low noise", Impact.NORMAL,
            "No sampled logs collected for target.",
        )

    th = config.log_thresholds
    compiled = [re.compile(p, re.IGNORECASE) for p in th.boilerplate_patterns]

    messages = [_extract_message(log) for log in bundle.logs]
    empty_count = sum(1 for m in messages if len(m) < 4)
    boilerplate_count = sum(1 for m in messages if any(p.search(m) for p in compiled))

    msg_counts = Counter(messages)
    repeated_excess = sum(cnt - 1 for cnt in msg_counts.values() if cnt > 3)

    total = len(bundle.logs)
    boilerplate_ratio = boilerplate_count / total
    duplicate_ratio = repeated_excess / total
    empty_ratio = empty_count / total

    issues: list[str] = []
    if boilerplate_ratio > th.max_boilerplate_ratio:
        issues.append(f"Healthcheck/boilerplate noise: {boilerplate_ratio:.0%} (max {th.max_boilerplate_ratio:.0%}).")
    if duplicate_ratio > th.max_duplicate_ratio:
        top_msg, top_cnt = msg_counts.most_common(1)[0]
        issues.append(f"High duplicate ratio {duplicate_ratio:.0%} (e.g. '{top_msg[:50]}' x{top_cnt}).")
    if empty_ratio > 0.05:
        issues.append(f"Empty/trivial messages: {empty_ratio:.0%}.")

    passed = len(issues) == 0
    penalty = min(1.0, boilerplate_ratio + duplicate_ratio * 0.5 + empty_ratio)
    ratio = 1.0 if passed else max(0.0, 1.0 - penalty)
    return RuleResult(
        rule_id="LOG-006",
        signal=Signal.LOGS,
        title="Log information relevance and low noise",
        impact=Impact.NORMAL,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=f"Boilerplate: {boilerplate_ratio:.0%}, duplicates: {duplicate_ratio:.0%}, empty: {empty_ratio:.0%} across {total} logs.",
        evidence=issues,
        remediation="Filter /healthz & /metrics access logs in the OTLP Collector and deduplicate/rate-limit repetitive log messages.",
    )
