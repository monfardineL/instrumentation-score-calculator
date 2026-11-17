#!/usr/bin/env python3
"""Convert `isc score --format json` output into a self-contained HTML report."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any


def _score_class(score: float) -> str:
    if score >= 85:
        return "good"
    if score >= 60:
        return "warn"
    return "bad"


def render_html(data: dict[str, Any]) -> str:
    """Render a ScoreReport JSON dict into a standalone HTML document."""
    target = html.escape(str(data.get("target_name", "Unknown")))
    selector = html.escape(str(data.get("selector", "")))
    lookback = html.escape(str(data.get("lookback", "")))
    overall = float(data.get("overall_score", 0.0))
    overall_cls = _score_class(overall)

    signal_cards = []
    for sig, val in (data.get("signal_scores") or {}).items():
        sval = float(val)
        signal_cards.append(
            f'<div class="card {_score_class(sval)}">'
            f'<div class="card-label">{html.escape(str(sig))}</div>'
            f'<div class="card-value">{sval:.1f}</div>'
            f"</div>"
        )

    warnings_html = ""
    errors = data.get("collection_errors") or {}
    if errors:
        items = "".join(
            f"<li><strong>{html.escape(str(k))}:</strong> {html.escape(str(v))}</li>"
            for k, v in errors.items()
        )
        warnings_html = f'<div class="warnings"><strong>Collection Warnings</strong><ul>{items}</ul></div>'

    rows_html = []
    for r in data.get("results") or []:
        skipped = bool(r.get("skipped", False))
        passed = bool(r.get("passed", False))
        ratio = float(r.get("score_ratio", 0.0))
        if skipped:
            status_badge = '<span class="badge skip">SKIP</span>'
            score_txt = "-"
        elif passed:
            status_badge = '<span class="badge pass">PASS</span>'
            score_txt = f"{ratio * 100:.0f}%"
        else:
            status_badge = '<span class="badge fail">FAIL</span>'
            score_txt = f"{ratio * 100:.0f}%"

        details = [f'<div>{html.escape(str(r.get("summary", "")))}</div>']
        evidence = r.get("evidence") or []
        if evidence:
            ev_items = "".join(f"<li>{html.escape(str(e))}</li>" for e in evidence)
            details.append(f'<ul class="evidence">{ev_items}</ul>')
        remediation = r.get("remediation")
        if not passed and not skipped and remediation:
            details.append(f'<div class="remediation"><strong>Fix:</strong> {html.escape(str(remediation))}</div>')

        rows_html.append(
            "<tr>"
            f'<td><code>{html.escape(str(r.get("rule_id", "")))}</code></td>'
            f'<td>{html.escape(str(r.get("signal", "")))}</td>'
            f'<td>{html.escape(str(r.get("impact", "")))}</td>'
            f"<td>{status_badge}</td>"
            f'<td class="num">{score_txt}</td>'
            f'<td>{"".join(details)}</td>'
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Instrumentation Score — {target}</title>
  <style>
    :root {{
      --bg: #0f172a; --surface: #1e293b; --border: #334155; --text: #e2e8f0;
      --muted: #94a3b8; --good: #22c55e; --warn: #eab308; --bad: #ef4444;
    }}
    body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 2rem; line-height: 1.5; }}
    .container {{ max-width: 1100px; margin: 0 auto; }}
    header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; background: var(--surface); padding: 1.5rem; border-radius: 10px; border: 1px solid var(--border); }}
    h1 {{ margin: 0 0 0.25rem 0; font-size: 1.4rem; }}
    .meta {{ color: var(--muted); font-size: 0.9rem; }}
    .overall {{ text-align: center; padding: 0.75rem 1.25rem; border-radius: 8px; border: 2px solid currentColor; }}
    .overall .num {{ font-size: 2rem; font-weight: 700; }}
    .good {{ color: var(--good); }} .warn {{ color: var(--warn); }} .bad {{ color: var(--bad); }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.75rem; margin: 1.25rem 0; }}
    .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.9rem; text-align: center; }}
    .card-label {{ color: var(--muted); font-size: 0.8rem; font-weight: 600; }}
    .card-value {{ font-size: 1.5rem; font-weight: 700; margin-top: 0.2rem; }}
    .warnings {{ background: #422006; border: 1px solid #a16207; border-radius: 8px; padding: 0.9rem 1.2rem; margin-bottom: 1.25rem; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--surface); border-radius: 10px; overflow: hidden; border: 1px solid var(--border); }}
    th, td {{ padding: 0.75rem 0.9rem; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }}
    th {{ background: #0b1220; font-size: 0.8rem; text-transform: uppercase; color: var(--muted); }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }}
    .badge.pass {{ background: rgba(34,197,94,0.18); color: var(--good); }}
    .badge.fail {{ background: rgba(239,68,68,0.18); color: var(--bad); }}
    .badge.skip {{ background: rgba(148,163,184,0.18); color: var(--muted); }}
    .evidence {{ margin: 0.4rem 0 0 1.1rem; padding: 0; color: var(--muted); font-size: 0.88rem; }}
    .remediation {{ margin-top: 0.4rem; font-size: 0.88rem; color: #cbd5e1; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Instrumentation Score: {target}</h1>
        <div class="meta">Selector: <code>{selector}</code> &middot; Lookback: <code>{lookback}</code></div>
      </div>
      <div class="overall {overall_cls}">
        <div class="num">{overall:.1f}</div>
        <div>/ 100</div>
      </div>
    </header>
    <div class="cards">{"".join(signal_cards)}</div>
    {warnings_html}
    <table>
      <thead>
        <tr><th>Rule</th><th>Signal</th><th>Impact</th><th>Status</th><th style="text-align:right">Score</th><th>Details</th></tr>
      </thead>
      <tbody>{"".join(rows_html)}</tbody>
    </table>
  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert isc JSON output into an HTML report.")
    parser.add_argument("input", help="Path to JSON file, or '-' to read from stdin.")
    parser.add_argument("-o", "--output", default="report.html", help="Output HTML file path (default: report.html).")
    args = parser.parse_args()

    raw_text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    data = json.loads(raw_text)
    out_path = Path(args.output)
    out_path.write_text(render_html(data), encoding="utf-8")
    print(f"Wrote HTML report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
