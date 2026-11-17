"""YAML configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from isc.models import (
    DatasourceConfig,
    LogQualityThresholds,
    MCPConfig,
    SelectorMapping,
    TargetConfig,
)


def _parse_selector(raw: dict[str, Any]) -> tuple[str, str]:
    selector = raw.get("selector")
    if isinstance(selector, str) and "=" in selector:
        key, val = selector.split("=", 1)
        return key.strip(), val.strip()
    if isinstance(selector, dict):
        key = str(selector.get("key", "")).strip()
        val = str(selector.get("value", "")).strip()
        if key and val:
            return key, val
    raise ValueError("Config 'selector' must be 'key=value' or {key: ..., value: ...}")


def load_config(path: str | Path, selector_override: str | None = None) -> TargetConfig:
    """Load a TargetConfig from a YAML file."""
    content = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(content, dict):
        raise ValueError("Configuration root must be a YAML mapping")

    if selector_override:
        if "=" not in selector_override:
            raise ValueError("Selector override must be in 'key=value' format")
        sel_key, sel_val = (part.strip() for part in selector_override.split("=", 1))
    else:
        sel_key, sel_val = _parse_selector(content)

    ds_raw = content.get("datasources") or {}
    datasources = DatasourceConfig(
        prometheus_uid=ds_raw.get("prometheus_uid") or ds_raw.get("mimir_uid"),
        loki_uid=ds_raw.get("loki_uid"),
        tempo_uid=ds_raw.get("tempo_uid"),
        pyroscope_uid=ds_raw.get("pyroscope_uid"),
    )

    map_raw = content.get("selector_mapping") or {}
    selector_mapping = SelectorMapping(
        prometheus_label=map_raw.get("prometheus_label"),
        loki_label=map_raw.get("loki_label"),
        tempo_attribute=map_raw.get("tempo_attribute"),
        pyroscope_label=map_raw.get("pyroscope_label"),
    )

    lt_raw = content.get("log_thresholds") or {}
    default_lt = LogQualityThresholds()
    log_thresholds = LogQualityThresholds(
        sample_limit=int(lt_raw.get("sample_limit", default_lt.sample_limit)),
        min_logs_per_hour=int(lt_raw.get("min_logs_per_hour", default_lt.min_logs_per_hour)),
        max_logs_per_minute=int(lt_raw.get("max_logs_per_minute", default_lt.max_logs_per_minute)),
        max_debug_ratio=float(lt_raw.get("max_debug_ratio", default_lt.max_debug_ratio)),
        max_error_ratio=float(lt_raw.get("max_error_ratio", default_lt.max_error_ratio)),
        max_duplicate_ratio=float(lt_raw.get("max_duplicate_ratio", default_lt.max_duplicate_ratio)),
        max_boilerplate_ratio=float(
            lt_raw.get("max_boilerplate_ratio", default_lt.max_boilerplate_ratio)
        ),
        min_structured_ratio=float(
            lt_raw.get("min_structured_ratio", default_lt.min_structured_ratio)
        ),
        min_trace_correlation_ratio=float(
            lt_raw.get("min_trace_correlation_ratio", default_lt.min_trace_correlation_ratio)
        ),
        boilerplate_patterns=list(
            lt_raw.get("boilerplate_patterns", default_lt.boilerplate_patterns)
        ),
    )

    mcp_raw = content.get("mcp") or {}
    default_mcp = MCPConfig()
    mcp_cfg = MCPConfig(
        transport=str(mcp_raw.get("transport", default_mcp.transport)),
        url=mcp_raw.get("url"),
        url_env=str(mcp_raw.get("url_env", default_mcp.url_env)),
        headers=dict(mcp_raw.get("headers") or {}),
        command=str(mcp_raw.get("command", default_mcp.command)),
        args=list(mcp_raw.get("args", default_mcp.args)),
        grafana_url_env=str(mcp_raw.get("grafana_url_env", default_mcp.grafana_url_env)),
        grafana_token_env=str(mcp_raw.get("grafana_token_env", default_mcp.grafana_token_env)),
        extra_env=dict(mcp_raw.get("extra_env", {})),
    )

    return TargetConfig(
        name=str(content.get("name") or f"{sel_key}={sel_val}"),
        selector_key=sel_key,
        selector_value=sel_val,
        lookback=str(content.get("lookback", "1h")),
        datasources=datasources,
        selector_mapping=selector_mapping,
        log_thresholds=log_thresholds,
        mcp=mcp_cfg,
        disabled_rules=list(content.get("disabled_rules") or []),
    )
