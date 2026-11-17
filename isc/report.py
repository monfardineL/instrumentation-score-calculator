"""Report formatting for terminal (Rich), JSON, and Markdown."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from isc.models import ScoreReport


def _score_color(score: float) -> str:
    if score >= 85:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"


def render_terminal(report: ScoreReport, console: Console | None = None) -> None:
    """Print a Rich summary table of the score report."""
    con = console or Console()
    color = _score_color(report.overall_score)

    signal_parts = "  |  ".join(
        f"[bold]{sig}[/bold]: [{_score_color(val)}]{val:.1f}[/{_score_color(val)}]"
        for sig, val in report.signal_scores.items()
    )
    header = (
        f"[bold]Target:[/bold] {report.target_name} ({report.selector})   "
        f"[bold]Lookback:[/bold] {report.lookback}\n"
        f"[bold]Overall Score:[/bold] [{color}][bold]{report.overall_score:.1f} / 100[/bold][/{color}]\n"
        f"{signal_parts}"
    )
    con.print(Panel(header, title="Instrumentation Score Report", border_style=color))

    if report.collection_errors:
        for sig, err in report.collection_errors.items():
            con.print(f"[yellow]Warning ({sig} collection):[/yellow] {err}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Rule", style="cyan", no_wrap=True)
    table.add_column("Impact", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Score", justify="right", no_wrap=True)
    table.add_column("Summary / Evidence")

    for r in report.results:
        if r.skipped:
            status = "[dim]SKIP[/dim]"
            score_str = "[dim]-[/dim]"
        elif r.passed:
            status = "[green]PASS[/green]"
            score_str = f"[green]{r.score_ratio * 100:.0f}%[/green]"
        else:
            status = "[red]FAIL[/red]"
            score_str = f"[red]{r.score_ratio * 100:.0f}%[/red]"

        details = r.summary
        if r.evidence:
            details += "\n  • " + "\n  • ".join(r.evidence)
        if not r.passed and not r.skipped and r.remediation:
            details += f"\n  [dim]Fix: {r.remediation}[/dim]"

        table.add_row(r.rule_id, r.impact.value, status, score_str, details)

    con.print(table)


def to_json(report: ScoreReport) -> str:
    """Serialize ScoreReport to formatted JSON."""
    payload: dict[str, Any] = asdict(report)
    for r in payload["results"]:
        r["signal"] = r["signal"].value if hasattr(r["signal"], "value") else str(r["signal"])
        r["impact"] = r["impact"].value if hasattr(r["impact"], "value") else str(r["impact"])
    return json.dumps(payload, indent=2)


def to_markdown(report: ScoreReport) -> str:
    """Serialize ScoreReport to Markdown."""
    lines = [
        f"# Instrumentation Score: {report.target_name} (`{report.selector}`)",
        "",
        f"- **Lookback:** `{report.lookback}`",
        f"- **Overall Score:** **{report.overall_score:.1f} / 100**",
        "",
        "## Signal Scores",
        "",
    ]
    for sig, val in report.signal_scores.items():
        lines.append(f"- **{sig}:** {val:.1f} / 100")

    lines.extend(["", "## Rule Breakdown", "", "| Rule | Impact | Status | Score | Details |", "| :--- | :--- | :--- | :--- | :--- |"])
    for r in report.results:
        status = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
        score_str = "-" if r.skipped else f"{r.score_ratio * 100:.0f}%"
        lines.append(f"| `{r.rule_id}` | {r.impact.value} | {status} | {score_str} | {r.summary} |")

    return "\n".join(lines) + "\n"
