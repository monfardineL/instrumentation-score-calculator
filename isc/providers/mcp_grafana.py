"""Grafana MCP (mcp-grafana) telemetry provider."""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from isc.models import (
    LogEntry,
    LogStats,
    MetricSeries,
    ProfileSummary,
    Signal,
    SpanSummary,
    TargetConfig,
    TelemetryBundle,
    TraceSummary,
)

_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")


def parse_lookback_seconds(lookback: str) -> int:
    """Convert a duration string like '1h', '30m', '2d' into seconds."""
    match = _DURATION_RE.match(lookback.strip())
    if not match:
        return 3600
    value, unit = int(match.group(1)), match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return value * multipliers[unit]


def _extract_json_payload(result: Any) -> Any:
    """Extract parsed JSON or text from an MCP CallToolResult."""
    content = getattr(result, "content", None) or []
    texts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            texts.append(text)
    joined = "\n".join(texts).strip()
    if not joined:
        return None
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


def _parse_log_line(raw_line: str, labels: dict[str, str]) -> tuple[dict[str, Any], str | None, str | None, str | None]:
    """Extract structured JSON fields, level, trace_id, and span_id from a log entry."""
    structured: dict[str, Any] = {}
    try:
        parsed = json.loads(raw_line)
        if isinstance(parsed, dict):
            structured = parsed
    except json.JSONDecodeError:
        pass

    level = (
        structured.get("level")
        or structured.get("severity")
        or structured.get("severity_text")
        or labels.get("level")
        or labels.get("severity_text")
        or labels.get("detected_level")
    )
    if level is not None:
        level = str(level).upper()

    trace_id = (
        structured.get("trace_id")
        or structured.get("traceId")
        or structured.get("traceid")
        or labels.get("trace_id")
    )
    span_id = (
        structured.get("span_id")
        or structured.get("spanId")
        or structured.get("spanid")
        or labels.get("span_id")
    )
    return structured, level, str(trace_id) if trace_id else None, str(span_id) if span_id else None


class GrafanaMCPProvider:
    """Connects to mcp-grafana (remote HTTP/SSE or local stdio) to collect telemetry."""

    @asynccontextmanager
    async def _open_session(self, config: TargetConfig) -> AsyncIterator[ClientSession]:
        mcp_url = config.mcp.url or os.environ.get(config.mcp.url_env)
        transport = config.mcp.transport.lower()
        if transport == "auto":
            if mcp_url:
                transport = "sse" if mcp_url.rstrip("/").endswith("/sse") else "streamable_http"
            else:
                transport = "stdio"

        if transport == "streamable_http":
            if not mcp_url:
                raise RuntimeError(f"Remote MCP URL not set (mcp.url or {config.mcp.url_env}).")
            http_client = httpx2.AsyncClient(headers=config.mcp.headers) if config.mcp.headers else None
            try:
                async with streamable_http_client(mcp_url, http_client=http_client) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        yield session
            finally:
                if http_client is not None:
                    await http_client.aclose()
            return

        if transport == "sse":
            if not mcp_url:
                raise RuntimeError(f"Remote MCP URL not set (mcp.url or {config.mcp.url_env}).")
            async with sse_client(mcp_url, headers=config.mcp.headers or None) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    yield session
            return

        if transport == "stdio":
            env = dict(os.environ)
            url_val = env.get(config.mcp.grafana_url_env)
            token_val = env.get(config.mcp.grafana_token_env)
            if not url_val or not token_val:
                raise RuntimeError(
                    f"Missing Grafana credentials for stdio mode: "
                    f"{config.mcp.grafana_url_env} and {config.mcp.grafana_token_env}"
                )
            env["GRAFANA_URL"] = url_val
            env["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = token_val
            env.update(config.mcp.extra_env)

            server_params = StdioServerParameters(
                command=config.mcp.command,
                args=config.mcp.args,
                env=env,
            )
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    yield session
            return

        raise ValueError(f"Unsupported MCP transport: {config.mcp.transport}")

    async def collect(self, config: TargetConfig) -> TelemetryBundle:
        bundle = TelemetryBundle(
            target_key=config.selector_key,
            target_value=config.selector_value,
            lookback=config.lookback,
        )

        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=parse_lookback_seconds(config.lookback))
        start_rfc = start.isoformat()
        end_rfc = now.isoformat()

        async with self._open_session(config) as session:
            await session.initialize()
            tools_resp = await session.list_tools()
            available = {t.name for t in tools_resp.tools}

            if config.datasources.prometheus_uid:
                await self._collect_metrics(session, available, config, bundle, start_rfc, end_rfc)
            if config.datasources.loki_uid:
                await self._collect_logs(session, available, config, bundle, start_rfc, end_rfc)
            if config.datasources.tempo_uid:
                await self._collect_traces(session, available, config, bundle, start_rfc, end_rfc)
            if config.datasources.pyroscope_uid:
                await self._collect_profiling(session, available, config, bundle, start_rfc, end_rfc)

        return bundle

    async def _call_tool(
        self, session: ClientSession, available: set[str], name: str, args: dict[str, Any]
    ) -> Any:
        if name not in available:
            raise RuntimeError(f"MCP tool '{name}' is not available on mcp-grafana server")
        res = await session.call_tool(name, args)
        if getattr(res, "isError", False):
            raise RuntimeError(f"MCP tool '{name}' failed: {_extract_json_payload(res)}")
        return _extract_json_payload(res)

    async def _collect_metrics(
        self,
        session: ClientSession,
        available: set[str],
        config: TargetConfig,
        bundle: TelemetryBundle,
        start_rfc: str,
        end_rfc: str,
    ) -> None:
        uid = config.datasources.prometheus_uid
        label = config.label_for(Signal.METRICS)
        selector = f'{{{label}="{config.selector_value}"}}'
        try:
            series_data = await self._call_tool(
                session,
                available,
                "query_prometheus",
                {
                    "datasourceUid": uid,
                    "expr": f"count by (__name__) ({selector})",
                    "queryType": "instant",
                    "startTime": start_rfc,
                    "endTime": end_rfc,
                },
            )
            metadata: dict[str, dict[str, Any]] = {}
            if "list_prometheus_metric_metadata" in available:
                meta_raw = await self._call_tool(
                    session, available, "list_prometheus_metric_metadata", {"datasourceUid": uid}
                )
                if isinstance(meta_raw, dict):
                    metadata = meta_raw

            results = series_data if isinstance(series_data, list) else (series_data or {}).get("result", [])
            for item in results or []:
                metric_info = item.get("metric", {})
                name = metric_info.get("__name__", "")
                if not name:
                    continue
                val = item.get("value", [0, "0"])
                count = int(float(val[1])) if isinstance(val, list) and len(val) > 1 else 1
                meta_entries = metadata.get(name, [])
                meta = meta_entries[0] if isinstance(meta_entries, list) and meta_entries else {}
                bundle.metrics.append(
                    MetricSeries(
                        name=name,
                        metric_type=meta.get("type"),
                        unit=meta.get("unit"),
                        help_text=meta.get("help"),
                        labels=[metric_info],
                        unique_series_count=count,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            bundle.collection_errors["metrics"] = str(exc)

    async def _collect_logs(
        self,
        session: ClientSession,
        available: set[str],
        config: TargetConfig,
        bundle: TelemetryBundle,
        start_rfc: str,
        end_rfc: str,
    ) -> None:
        uid = config.datasources.loki_uid
        label = config.label_for(Signal.LOGS)
        selector = f'{{{label}="{config.selector_value}"}}'
        try:
            if "query_loki_stats" in available:
                stats_raw = await self._call_tool(
                    session,
                    available,
                    "query_loki_stats",
                    {"datasourceUid": uid, "logql": selector, "start": start_rfc, "end": end_rfc},
                )
                if isinstance(stats_raw, dict):
                    bundle.log_stats.total_lines = int(stats_raw.get("entries", 0))
                    bundle.log_stats.total_bytes = int(stats_raw.get("bytes", 0))

            # Aggregate volume over time (1m buckets) & level distribution across ALL matching logs
            if "query_loki_logs" in available:
                vol_raw = await self._call_tool(
                    session,
                    available,
                    "query_loki_logs",
                    {
                        "datasourceUid": uid,
                        "logql": f"sum(count_over_time({selector}[1m]))",
                        "startRfc3339": start_rfc,
                        "endRfc3339": end_rfc,
                        "queryType": "range",
                        "stepSeconds": 60,
                    },
                )
                if isinstance(vol_raw, list):
                    for stream in vol_raw:
                        for _, val in stream.get("values", []):
                            bundle.log_stats.buckets_per_minute.append(int(float(val)))

                lvl_raw = await self._call_tool(
                    session,
                    available,
                    "query_loki_logs",
                    {
                        "datasourceUid": uid,
                        "logql": f"sum by (level, detected_level) (count_over_time({selector}[{config.lookback}]))",
                        "startRfc3339": start_rfc,
                        "endRfc3339": end_rfc,
                        "queryType": "instant",
                    },
                )
                if isinstance(lvl_raw, list):
                    for item in lvl_raw:
                        metric = item.get("metric", {})
                        lvl = (metric.get("level") or metric.get("detected_level") or "UNKNOWN").upper()
                        val = item.get("value", [0, "0"])
                        count = int(float(val[1])) if isinstance(val, list) and len(val) > 1 else 0
                        bundle.log_stats.level_counts[lvl] = (
                            bundle.log_stats.level_counts.get(lvl, 0) + count
                        )

                # Bounded raw log sample for metadata, trace correlation, and relevance checks
                logs_raw = await self._call_tool(
                    session,
                    available,
                    "query_loki_logs",
                    {
                        "datasourceUid": uid,
                        "logql": selector,
                        "startRfc3339": start_rfc,
                        "endRfc3339": end_rfc,
                        "limit": config.log_thresholds.sample_limit,
                        "direction": "backward",
                    },
                )
                if isinstance(logs_raw, list):
                    for stream in logs_raw:
                        labels = stream.get("labels", {}) or stream.get("stream", {}) or {}
                        for entry in stream.get("values", []):
                            ts, line = str(entry[0]), str(entry[1])
                            structured, lvl, trace_id, span_id = _parse_log_line(line, labels)
                            bundle.logs.append(
                                LogEntry(
                                    timestamp=ts,
                                    line=line,
                                    labels=labels,
                                    structured_fields=structured,
                                    level=lvl,
                                    trace_id=trace_id,
                                    span_id=span_id,
                                )
                            )
        except Exception as exc:  # noqa: BLE001
            bundle.collection_errors["logs"] = str(exc)

    async def _collect_traces(
        self,
        session: ClientSession,
        available: set[str],
        config: TargetConfig,
        bundle: TelemetryBundle,
        start_rfc: str,
        end_rfc: str,
    ) -> None:
        uid = config.datasources.tempo_uid
        attr = config.label_for(Signal.TRACES)
        traceql = f'{{ resource.{attr}="{config.selector_value}" || span.{attr}="{config.selector_value}" }}'
        try:
            traces_raw = await self._call_tool(
                session,
                available,
                "search_tempo_traces",
                {
                    "datasourceUid": uid,
                    "query": traceql,
                    "start": start_rfc,
                    "end": end_rfc,
                    "limit": 50,
                },
            )
            trace_list = traces_raw if isinstance(traces_raw, list) else (traces_raw or {}).get("traces", [])
            for t in trace_list or []:
                tid = t.get("traceID") or t.get("trace_id") or ""
                if not tid:
                    continue
                spans: list[SpanSummary] = []
                for rs in t.get("spanSets", []):
                    for sp in rs.get("spans", []):
                        attrs = {a["key"]: a.get("value") for a in sp.get("attributes", []) if "key" in a}
                        spans.append(
                            SpanSummary(
                                trace_id=tid,
                                span_id=sp.get("spanID", ""),
                                parent_span_id=sp.get("parentSpanID"),
                                name=sp.get("name", t.get("rootTraceName", "")),
                                service_name=t.get("rootServiceName"),
                                status_code=sp.get("status", {}).get("code") if isinstance(sp.get("status"), dict) else None,
                                resource_attributes=attrs,
                                span_attributes=attrs,
                            )
                        )
                if not spans:
                    spans.append(
                        SpanSummary(
                            trace_id=tid,
                            span_id=tid,
                            parent_span_id=None,
                            name=t.get("rootTraceName", ""),
                            service_name=t.get("rootServiceName"),
                        )
                    )
                bundle.traces.append(TraceSummary(trace_id=tid, spans=spans))
        except Exception as exc:  # noqa: BLE001
            bundle.collection_errors["traces"] = str(exc)

    async def _collect_profiling(
        self,
        session: ClientSession,
        available: set[str],
        config: TargetConfig,
        bundle: TelemetryBundle,
        start_rfc: str,
        end_rfc: str,
    ) -> None:
        uid = config.datasources.pyroscope_uid
        label = config.label_for(Signal.PROFILING)
        matcher = f'{{{label}="{config.selector_value}"}}'
        try:
            if "list_pyroscope_profile_types" in available:
                ptypes = await self._call_tool(
                    session,
                    available,
                    "list_pyroscope_profile_types",
                    {"datasourceUid": uid, "start": start_rfc, "end": end_rfc},
                )
                if isinstance(ptypes, list):
                    bundle.profiling.profile_types = [str(p) for p in ptypes]

            if "query_pyroscope" in available and bundle.profiling.profile_types:
                prof_raw = await self._call_tool(
                    session,
                    available,
                    "query_pyroscope",
                    {
                        "datasourceUid": uid,
                        "profileType": bundle.profiling.profile_types[0],
                        "labelSelector": matcher,
                        "start": start_rfc,
                        "end": end_rfc,
                    },
                )
                if isinstance(prof_raw, dict):
                    bundle.profiling.total_samples = int(prof_raw.get("total", 0) or prof_raw.get("numTicks", 0))
                    names = prof_raw.get("names") or prof_raw.get("functions") or []
                    bundle.profiling.sample_functions = [str(n) for n in names[:200]]
        except Exception as exc:  # noqa: BLE001
            bundle.collection_errors["profiling"] = str(exc)
