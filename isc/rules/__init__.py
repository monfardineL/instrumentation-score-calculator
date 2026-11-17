"""Registered instrumentation score rules across all signals."""

from isc.rules import logs, metrics, profiling, resource, traces  # noqa: F401
from isc.rules.base import ALL_RULES, RuleDefinition

__all__ = ["ALL_RULES", "RuleDefinition"]
