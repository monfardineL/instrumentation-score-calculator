"""CLI entrypoint for Instrumentation Score Calculator."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from isc.config import load_config
from isc.engine import evaluate_bundle
from isc.models import TargetConfig
from isc.providers import FixtureProvider, GrafanaMCPProvider
from isc.report import render_terminal, to_json, to_markdown
from isc.rules import ALL_RULES

app = typer.Typer(
    name="isc",
    help="Evaluate telemetry instrumentation quality across Prometheus/Mimir, Loki, Tempo, and Pyroscope via Grafana MCP.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def score(
    config: Path = typer.Option(..., "--config", "-c", help="Path to target YAML config."),
    selector: Optional[str] = typer.Option(None, "--selector", "-s", help="Override selector (e.g. appid=tms)."),
    fixture: Optional[Path] = typer.Option(None, "--fixture", "-f", help="Evaluate an offline JSON fixture instead of Grafana MCP."),
    output_format: str = typer.Option("table", "--format", "-o", help="Output format: table, json, markdown."),
    min_score: Optional[float] = typer.Option(None, "--min-score", help="Exit with code 1 if overall score is below threshold."),
) -> None:
    """Calculate the instrumentation score for a configured application."""
    cfg = load_config(config, selector_override=selector)
    provider = FixtureProvider(fixture) if fixture else GrafanaMCPProvider()
    bundle = asyncio.run(provider.collect(cfg))
    report = evaluate_bundle(bundle, cfg)

    fmt = output_format.lower()
    if fmt == "json":
        typer.echo(to_json(report))
    elif fmt in ("md", "markdown"):
        typer.echo(to_markdown(report))
    else:
        render_terminal(report, console=console)

    if min_score is not None and report.overall_score < min_score:
        raise typer.Exit(code=1)


@app.command()
def rules() -> None:
    """List all available instrumentation & log-quality rules."""
    table = Table(title="Registered Instrumentation Rules", show_header=True, header_style="bold")
    table.add_column("Rule ID", style="cyan", no_wrap=True)
    table.add_column("Signal", no_wrap=True)
    table.add_column("Impact", no_wrap=True)
    table.add_column("Title")
    table.add_column("Description")

    for r in ALL_RULES:
        table.add_row(r.rule_id, r.signal.value, r.impact.value, r.title, r.description)
    console.print(table)


@app.command()
def init(
    output: Path = typer.Option(Path("isc.yaml"), "--output", "-o", help="Output path for starter config."),
    selector: str = typer.Option("appid=tms", "--selector", "-s", help="Target key=value selector."),
) -> None:
    """Generate a starter isc.yaml configuration file."""
    if output.exists():
        console.print(f"[red]File already exists:[/red] {output}")
        raise typer.Exit(code=1)

    template = f"""name: {selector}
selector: "{selector}"
lookback: 1h

datasources:
  prometheus_uid: "your-prometheus-or-mimir-uid"
  loki_uid: "your-loki-uid"
  tempo_uid: "your-tempo-uid"
  pyroscope_uid: "your-pyroscope-uid"

# Optional: override the label/attribute name per signal if it differs from '{selector.split('=')[0]}'
selector_mapping:
  prometheus_label: "{selector.split('=')[0]}"
  loki_label: "{selector.split('=')[0]}"
  tempo_attribute: "{selector.split('=')[0]}"
  pyroscope_label: "{selector.split('=')[0]}"

log_thresholds:
  sample_limit: 1000
  min_logs_per_hour: 1
  max_logs_per_minute: 10000
  max_debug_ratio: 0.50
  max_error_ratio: 0.20
  max_duplicate_ratio: 0.40
  max_boilerplate_ratio: 0.30
  min_structured_ratio: 0.80
  min_trace_correlation_ratio: 0.50

mcp:
  # Remote mcp-grafana web service (set url or GRAFANA_MCP_URL; no auth required)
  transport: auto
  url: "http://localhost:8000/mcp"
  url_env: GRAFANA_MCP_URL
  # Local stdio fallback (used when url and GRAFANA_MCP_URL are unset)
  command: uvx
  args: ["mcp-grafana"]
  grafana_url_env: GRAFANA_URL
  grafana_token_env: GRAFANA_SERVICE_ACCOUNT_TOKEN
"""
    output.write_text(template, encoding="utf-8")
    console.print(f"[green]Created starter config:[/green] {output}")
