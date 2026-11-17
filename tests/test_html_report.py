"""Tests for scripts/json_to_html.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_json_to_html_conversion(tmp_path: Path) -> None:
    sample = {
        "target_name": "tms-prod",
        "selector": "appid=tms",
        "lookback": "1h",
        "overall_score": 75.0,
        "signal_scores": {"LOG": 75.0},
        "collection_errors": {},
        "results": [
            {
                "rule_id": "LOG-003",
                "signal": "LOG",
                "title": "No secrets",
                "impact": "critical",
                "passed": False,
                "skipped": False,
                "score_ratio": 0.0,
                "summary": "Found secret <script>alert(1)</script>",
                "evidence": ["Matched pattern"],
                "remediation": "Redact secrets",
            }
        ],
    }
    in_file = tmp_path / "report.json"
    out_file = tmp_path / "report.html"
    in_file.write_text(json.dumps(sample), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "json_to_html.py"), str(in_file), "-o", str(out_file)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Wrote HTML report" in proc.stdout
    html_text = out_file.read_text(encoding="utf-8")
    assert "Instrumentation Score: tms-prod" in html_text
    assert "LOG-003" in html_text
    assert "<script>alert(1)</script>" not in html_text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text
