"""Continuous profiling rules (PRO-*) for Pyroscope."""

from __future__ import annotations

import re

from isc.models import Impact, RuleResult, Signal, TargetConfig, TelemetryBundle
from isc.rules.base import register_rule, skipped_result

_HEX_ADDR_RE = re.compile(r"^(0x)?[0-9a-fA-F]{6,}$")


@register_rule(
    rule_id="PRO-001",
    signal=Signal.PROFILING,
    title="Continuous profiling active for target",
    impact=Impact.IMPORTANT,
    description="Pyroscope should receive continuous profiling data for the target application.",
)
def check_profiling_active(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not config.datasources.pyroscope_uid and not bundle.profiling.profile_types and bundle.profiling.total_samples == 0:
        return skipped_result(
            "PRO-001", Signal.PROFILING, "Continuous profiling active for target", Impact.IMPORTANT,
            "Pyroscope datasource not configured.",
        )

    active = bool(bundle.profiling.profile_types) and bundle.profiling.total_samples > 0
    return RuleResult(
        rule_id="PRO-001",
        signal=Signal.PROFILING,
        title="Continuous profiling active for target",
        impact=Impact.IMPORTANT,
        passed=active,
        score_ratio=1.0 if active else 0.0,
        summary=(
            f"Profiling active ({bundle.profiling.total_samples} samples, types: {', '.join(bundle.profiling.profile_types)})."
            if active
            else "No profiling samples found for target in Pyroscope."
        ),
        remediation="Enable Grafana Alloy / Pyroscope SDK or OTLP profiling receiver for this application.",
    )


@register_rule(
    rule_id="PRO-002",
    signal=Signal.PROFILING,
    title="CPU and memory profile types collected",
    impact=Impact.NORMAL,
    description="Target should report both CPU and memory/allocation profile types when supported.",
)
def check_profile_types(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    if not bundle.profiling.profile_types:
        return skipped_result(
            "PRO-002", Signal.PROFILING, "CPU and memory profile types collected", Impact.NORMAL,
            "No profile types available.",
        )

    types_lower = [p.lower() for p in bundle.profiling.profile_types]
    has_cpu = any("cpu" in p for p in types_lower)
    has_mem = any(k in p for p in types_lower for k in ("alloc", "heap", "memory", "inuse"))
    score = (0.5 if has_cpu else 0.0) + (0.5 if has_mem else 0.0)
    passed = has_cpu and has_mem
    return RuleResult(
        rule_id="PRO-002",
        signal=Signal.PROFILING,
        title="CPU and memory profile types collected",
        impact=Impact.NORMAL,
        passed=passed,
        score_ratio=score,
        summary=f"Available profile types: {', '.join(bundle.profiling.profile_types)}",
        evidence=[] if passed else ["Recommended: both CPU and memory/alloc profiles."],
        remediation="Enable both CPU and heap/allocation profiling in your Pyroscope agent.",
    )


@register_rule(
    rule_id="PRO-003",
    signal=Signal.PROFILING,
    title="Profile stack frames are symbolized",
    impact=Impact.IMPORTANT,
    description="Sampled stack frames should contain readable function names rather than raw hex addresses.",
)
def check_profile_symbolization(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    funcs = bundle.profiling.sample_functions
    if not funcs:
        return skipped_result(
            "PRO-003", Signal.PROFILING, "Profile stack frames are symbolized", Impact.IMPORTANT,
            "No sampled stack frame functions available.",
        )

    raw_hex = [f for f in funcs if _HEX_ADDR_RE.match(f.strip()) or f.strip() in ("[unknown]", "unknown")]
    ratio = max(0.0, 1.0 - (len(raw_hex) / len(funcs)))
    passed = ratio >= 0.8
    return RuleResult(
        rule_id="PRO-003",
        signal=Signal.PROFILING,
        title="Profile stack frames are symbolized",
        impact=Impact.IMPORTANT,
        passed=passed,
        score_ratio=round(ratio, 2),
        summary=f"{len(funcs) - len(raw_hex)}/{len(funcs)} sampled frames ({ratio:.0%}) are symbolized.",
        evidence=raw_hex[:5],
        remediation="Preserve debug symbols or enable symbolization in Grafana Alloy / Pyroscope.",
    )
