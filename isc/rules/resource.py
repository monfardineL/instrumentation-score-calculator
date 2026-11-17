"""Resource attribute rules (RES-*) aligned with OTel semantic conventions."""

from __future__ import annotations

from isc.models import Impact, RuleResult, Signal, TargetConfig, TelemetryBundle
from isc.rules.base import register_rule, skipped_result


def _collect_resource_keys(bundle: TelemetryBundle) -> tuple[set[str], int]:
    """Gather observed resource/label keys across signals and count non-empty signals."""
    keys: set[str] = set()
    signals_present = 0

    if bundle.metrics:
        signals_present += 1
        for m in bundle.metrics:
            for lbl in m.labels:
                keys.update(lbl.keys())

    if bundle.logs:
        signals_present += 1
        for log in bundle.logs:
            keys.update(log.labels.keys())
            keys.update(log.structured_fields.keys())
            res = log.structured_fields.get("resource")
            if isinstance(res, dict):
                keys.update(res.keys())

    if bundle.traces:
        signals_present += 1
        for trace in bundle.traces:
            for span in trace.spans:
                if span.service_name:
                    keys.add("service.name")
                keys.update(span.resource_attributes.keys())

    return keys, signals_present


@register_rule(
    rule_id="RES-001",
    signal=Signal.RESOURCE,
    title="service.name resource attribute present",
    impact=Impact.CRITICAL,
    description="Telemetry must identify the emitting service via service.name (or service_name).",
)
def check_service_name(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    keys, signals_present = _collect_resource_keys(bundle)
    if signals_present == 0:
        return skipped_result(
            "RES-001", Signal.RESOURCE, "service.name resource attribute present", Impact.CRITICAL,
            "No telemetry signals collected to evaluate resource attributes.",
        )

    has_service_name = any(k in keys for k in ("service.name", "service_name", "exported_service_name"))
    return RuleResult(
        rule_id="RES-001",
        signal=Signal.RESOURCE,
        title="service.name resource attribute present",
        impact=Impact.CRITICAL,
        passed=has_service_name,
        score_ratio=1.0 if has_service_name else 0.0,
        summary="service.name is present." if has_service_name else "Missing service.name / service_name across signals.",
        remediation="Configure OTel Resource attribute `service.name` in your SDK or OTLP Collector resource processor.",
    )


@register_rule(
    rule_id="RES-002",
    signal=Signal.RESOURCE,
    title="service.version resource attribute present",
    impact=Impact.NORMAL,
    description="Telemetry should include service.version to correlate regressions with releases.",
)
def check_service_version(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    keys, signals_present = _collect_resource_keys(bundle)
    if signals_present == 0:
        return skipped_result(
            "RES-002", Signal.RESOURCE, "service.version resource attribute present", Impact.NORMAL,
            "No telemetry signals collected.",
        )

    has_version = any(k in keys for k in ("service.version", "service_version", "version"))
    return RuleResult(
        rule_id="RES-002",
        signal=Signal.RESOURCE,
        title="service.version resource attribute present",
        impact=Impact.NORMAL,
        passed=has_version,
        score_ratio=1.0 if has_version else 0.0,
        summary="service.version is present." if has_version else "Missing service.version attribute.",
        remediation="Set `service.version` via OTEL_RESOURCE_ATTRIBUTES or build-time injection.",
    )


@register_rule(
    rule_id="RES-003",
    signal=Signal.RESOURCE,
    title="deployment.environment attribute present",
    impact=Impact.IMPORTANT,
    description="Telemetry should identify deployment.environment (or env) to separate contexts.",
)
def check_deployment_env(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult:
    keys, signals_present = _collect_resource_keys(bundle)
    if signals_present == 0:
        return skipped_result(
            "RES-003", Signal.RESOURCE, "deployment.environment attribute present", Impact.IMPORTANT,
            "No telemetry signals collected.",
        )

    has_env = any(
        k in keys
        for k in ("deployment.environment", "deployment.environment.name", "deployment_environment", "env", "environment")
    )
    return RuleResult(
        rule_id="RES-003",
        signal=Signal.RESOURCE,
        title="deployment.environment attribute present",
        impact=Impact.IMPORTANT,
        passed=has_env,
        score_ratio=1.0 if has_env else 0.0,
        summary="deployment.environment is present." if has_env else "Missing deployment.environment attribute.",
        remediation="Add `deployment.environment` in your OTLP Collector resource processor or OTEL_RESOURCE_ATTRIBUTES.",
    )
