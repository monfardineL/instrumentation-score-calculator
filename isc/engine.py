"""Scoring engine that runs registered rules and computes weighted 0-100 scores."""

from __future__ import annotations

from collections import defaultdict

from isc.models import RuleResult, ScoreReport, Signal, TargetConfig, TelemetryBundle
from isc.rules import ALL_RULES


def _weighted_score(results: list[RuleResult]) -> float:
    active = [r for r in results if not r.skipped]
    if not active:
        return 0.0
    total_weight = sum(r.impact.weight for r in active)
    earned_weight = sum(r.impact.weight * max(0.0, min(1.0, r.score_ratio)) for r in active)
    return round((earned_weight / total_weight) * 100.0, 1) if total_weight else 0.0


def evaluate_bundle(bundle: TelemetryBundle, config: TargetConfig) -> ScoreReport:
    """Evaluate all enabled rules against a TelemetryBundle."""
    disabled = set(config.disabled_rules)
    results: list[RuleResult] = []

    for rule_def in ALL_RULES:
        if rule_def.rule_id in disabled:
            continue
        results.append(rule_def.evaluator(bundle, config))

    by_signal: dict[str, list[RuleResult]] = defaultdict(list)
    for res in results:
        by_signal[res.signal.value].append(res)

    signal_scores: dict[str, float] = {}
    for sig in Signal:
        sig_results = by_signal.get(sig.value, [])
        if any(not r.skipped for r in sig_results):
            signal_scores[sig.value] = _weighted_score(sig_results)

    return ScoreReport(
        target_name=config.name,
        selector=f"{config.selector_key}={config.selector_value}",
        lookback=config.lookback,
        overall_score=_weighted_score(results),
        signal_scores=signal_scores,
        results=results,
        collection_errors=bundle.collection_errors,
    )
