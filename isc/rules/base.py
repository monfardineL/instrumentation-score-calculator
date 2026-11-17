"""Rule registry and base types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from isc.models import Impact, RuleResult, Signal, TargetConfig, TelemetryBundle

RuleEvaluator = Callable[[TelemetryBundle, TargetConfig], RuleResult]


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """Metadata and evaluator for a registered instrumentation rule."""

    rule_id: str
    signal: Signal
    title: str
    impact: Impact
    description: str
    evaluator: RuleEvaluator


ALL_RULES: list[RuleDefinition] = []


def register_rule(
    rule_id: str,
    signal: Signal,
    title: str,
    impact: Impact,
    description: str,
) -> Callable[[RuleEvaluator], RuleEvaluator]:
    """Decorator to register a rule evaluator."""

    def decorator(fn: RuleEvaluator) -> RuleEvaluator:
        ALL_RULES.append(
            RuleDefinition(
                rule_id=rule_id,
                signal=signal,
                title=title,
                impact=impact,
                description=description,
                evaluator=fn,
            )
        )
        return fn

    return decorator


def skipped_result(rule_id: str, signal: Signal, title: str, impact: Impact, reason: str) -> RuleResult:
    """Helper for rules skipped due to missing signal data."""
    return RuleResult(
        rule_id=rule_id,
        signal=signal,
        title=title,
        impact=impact,
        passed=True,
        skipped=True,
        score_ratio=1.0,
        summary=reason,
    )
