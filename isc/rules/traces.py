"""Trace / Span rules (SPA-*) for Tempo OTLP traces."""

from __future__ import annotations

import re

from isc.models import Impact, RuleResult, Signal, TargetConfig, TelemetryBundle
from isc.rules.base import register_rule, skipped_result

_DYNAMIC_ID_RE = re.compile(
    r"(/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|/\d{3,})"
)


@register_rule(
    rule_id="SPA-001",
    signal=Signal.TRACES,
    title="Low-cardinality span names",
    impact=Impact.CRITICAL,
    description="Span names must use parameterized route templates, not raw IDs or UUIDs.",
)
def check_span_names(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    spans = [s for t in bundle.traces for s in t.spans]
    if not spans:
        return skipped_result(
            "SPA-001", Signal.TRACES, "Low-cardinality span names", Impact.CRITICAL,
            "No traces collected for target.",
        )

    bad = [s.name for s in spans if _DYNAMIC_ID_RE.search(s.name)]
    ratio = max(0.0, 1.0 - (len(bad) / len(spans)))
    passed = len(bad) == 0
    return RuleResult(
        rule_id="SPA-001",
        signal=Signal.TRACES,
        title="Low-cardinality span names",
        impact=Impact.CRITICAL,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=(
            f"All {len(spans)} sampled spans use low-cardinality names."
            if passed
            else f"{len(bad)}/{len(spans)} spans contain raw IDs/UUIDs in span names."
        ),
        evidence=list(dict.fromkeys(bad))[:5],
        remediation="Use parameterized route names (e.g., `GET /orders/{id}`) via HTTP framework instrumentation.",
    )


@register_rule(
    rule_id="SPA-002",
    signal=Signal.TRACES,
    title="Trace context propagation integrity",
    impact=Impact.IMPORTANT,
    description="Multi-span traces should form connected trees without broken parent references.",
)
def check_context_propagation(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.traces:
        return skipped_result(
            "SPA-002", Signal.TRACES, "Trace context propagation integrity", Impact.IMPORTANT,
            "No traces collected for target.",
        )

    broken: list[str] = []
    for trace in bundle.traces:
        span_ids = {s.span_id for s in trace.spans if s.span_id}
        roots = [s for s in trace.spans if not s.parent_span_id]
        orphans = [
            s for s in trace.spans
            if s.parent_span_id and s.parent_span_id not in span_ids and len(trace.spans) > 1
        ]
        if len(trace.spans) > 1 and (len(roots) == 0 or orphans):
            broken.append(f"trace {trace.trace_id}: {len(roots)} roots, {len(orphans)} orphan spans")

    ratio = max(0.0, 1.0 - (len(broken) / len(bundle.traces)))
    passed = len(broken) == 0
    return RuleResult(
        rule_id="SPA-002",
        signal=Signal.TRACES,
        title="Trace context propagation integrity",
        impact=Impact.IMPORTANT,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=(
            f"All {len(bundle.traces)} sampled traces have intact parent-child span trees."
            if passed
            else f"{len(broken)}/{len(bundle.traces)} traces show broken context propagation."
        ),
        evidence=broken[:5],
        remediation="Ensure W3C `traceparent` header propagation is enabled across HTTP/gRPC/messaging clients.",
    )


@register_rule(
    rule_id="SPA-003",
    signal=Signal.TRACES,
    title="Span semantic attributes & status populated",
    impact=Impact.NORMAL,
    description="Spans should include OTel semantic attributes (http.*, db.*, rpc.*) or status codes.",
)
def check_span_semantics(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    spans = [s for t in bundle.traces for s in t.spans]
    if not spans:
        return skipped_result(
            "SPA-003", Signal.TRACES, "Span semantic attributes & status populated", Impact.NORMAL,
            "No traces collected for target.",
        )

    rich_spans = [
        s for s in spans
        if s.status_code or any(
            k.startswith(("http.", "db.", "rpc.", "messaging.", "url."))
            for k in s.span_attributes
        )
    ]
    ratio = len(rich_spans) / len(spans)
    passed = ratio >= 0.7
    return RuleResult(
        rule_id="SPA-003",
        signal=Signal.TRACES,
        title="Span semantic attributes & status populated",
        impact=Impact.NORMAL,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=f"{len(rich_spans)}/{len(spans)} spans ({ratio:.0%}) include semantic attributes or status.",
        remediation="Use standard OTel instrumentation libraries so HTTP/DB/RPC semantic attributes are attached.",
    )
