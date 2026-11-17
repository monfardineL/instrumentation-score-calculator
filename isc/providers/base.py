"""Base protocol for telemetry collection providers."""

from __future__ import annotations

from typing import Protocol

from isc.models import TargetConfig, TelemetryBundle


class TelemetryProvider(Protocol):
    """Collects a TelemetryBundle for a configured target."""

    async def collect(self, config: TargetConfig) -> TelemetryBundle:
        """Fetch bounded telemetry samples and aggregate stats for the target."""
        ...
