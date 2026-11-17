---
name: instrumentation-score-calculator
description: >-
  Guide for AI agents working on or interacting with the Instrumentation Score
  Calculator (isc) CLI. Covers project goals, architecture, file structure,
  rule-authoring conventions, Grafana MCP integration, and testing workflows.
---

# Instrumentation Score Calculator (`isc`)

## 1. Goals & Design Philosophy

`isc` is a Python CLI tool that calculates a repeatable **0–100 instrumentation quality score** (inspired by [`instrumentation-score/spec`](https://github.com/instrumentation-score/spec)) for applications emitting OpenTelemetry (OTLP) telemetry into a Grafana stack.

Core design principles:
1. **Multi-context scoping via key-value selector + explicit datasources:**
   - Instead of assuming one global Prometheus job, every evaluation targets a `key=value` selector (e.g., `appid=tms`) and explicit Grafana datasource UIDs (`prometheus_uid`, `loki_uid`, `tempo_uid`, `pyroscope_uid`).
   - `selector_mapping` in `isc.yaml` handles cases where backends store the selector under different label/attribute names.
2. **All 5 signal categories (`RES`, `MET`, `LOG`, `SPA`, `PRO`):**
   - Goes beyond metrics to evaluate **Resource attributes**, **Metrics** (Prometheus/Mimir), **Logs** (Loki), **Traces** (Tempo), and **Continuous Profiling** (Pyroscope).
3. **Grafana MCP (`mcp-grafana`) as the unified gateway:**
   - Uses `mcp-grafana` over stdio (`uvx mcp-grafana`) so one Grafana Service Account token queries all configured datasources.
4. **Deterministic core + bounded/aggregate queries:**
   - Core scoring is 100% deterministic (repeatable in CI via `--min-score`).
   - For **Log Quality (`LOG-*`)**, never rely solely on a small raw log sample for volume or level distribution: `GrafanaMCPProvider` combines `query_loki_stats` + LogQL metric queries (`count_over_time` per minute and by level) across all matching logs with a bounded raw sample (`sample_limit`, default `1000`) for structure, metadata, trace correlation, secrets, and noise/relevance checks.
5. **Offline-first development:**
   - `FixtureProvider` loads local JSON fixtures (`examples/tms_fixture.json`) so rules, scoring, and CLI output can be developed and tested without live Grafana access.

---

## 2. Project Structure

```text
instrumentation-score-calculator/
├── pyproject.toml                  # Package metadata, dependencies, `isc` script entrypoint
├── README.md                       # Quickstart & CLI usage
├── examples/
│   ├── isc.yaml                    # Example config for appid=tms
│   └── tms_fixture.json            # Offline TelemetryBundle fixture
├── isc/
│   ├── __init__.py
│   ├── cli.py                      # Typer CLI: `score`, `rules`, `init`
│   ├── config.py                   # YAML config loader (`load_config`)
│   ├── models.py                   # Dataclasses: TargetConfig, TelemetryBundle, RuleResult, ScoreReport
│   ├── engine.py                   # `evaluate_bundle`: runs rules & computes weighted 0-100 scores
│   ├── report.py                   # Rich terminal table, JSON, and Markdown formatters
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py                 # `TelemetryProvider` Protocol
│   │   ├── mcp_grafana.py          # `GrafanaMCPProvider` (mcp-grafana stdio client)
│   │   └── fixture.py              # `FixtureProvider` (offline JSON loader)
│   └── rules/
│       ├── __init__.py             # Imports all rule modules to populate `ALL_RULES`
│       ├── base.py                 # `register_rule`, `ALL_RULES`, `skipped_result`
│       ├── resource.py             # RES-001..003 (service.name, service.version, deployment.environment)
│       ├── metrics.py              # MET-001..003 (naming, metadata, high-cardinality labels/series)
│       ├── logs.py                 # LOG-001..006 (structure/metadata, trace correlation, secrets, volume, levels, relevance)
│       ├── traces.py               # SPA-001..003 (span name cardinality, context propagation, semantic attrs)
│       └── profiling.py            # PRO-001..003 (active profiling, CPU+memory types, symbolization)
└── tests/
    └── test_rules.py               # Unit tests for config, scoring, and rule pass/fail cases
```

---

## 3. Scoring Mechanics

* **Impact weights** (`Impact` enum in `isc/models.py`):
  * `CRITICAL`: weight `4`
  * `IMPORTANT`: weight `2`
  * `NORMAL`: weight `1`
* **Rule output** (`RuleResult`):
  * `score_ratio` is a float in `[0.0, 1.0]` (`1.0` = full pass, `0.0` = fail, fractional allowed for partial compliance).
  * `skipped=True` excludes the rule from the score denominator so unconfigured/absent signals do not penalize the overall score.
* **Aggregation** (`isc/engine.py`):
  * Overall score and per-signal sub-scores (`RES`, `MET`, `LOG`, `SPA`, `PRO`) are computed as `sum(weight * score_ratio) / sum(weight) * 100`.

---

## 4. Ways of Working (For AI Agents)

### Running Locally & Testing
Always use `uv` in the repository root:

```bash
# Install/sync dependencies including pytest
uv sync --extra dev

# Run unit tests
uv run pytest -v

# Run CLI against the offline fixture
uv run isc score --config examples/isc.yaml --fixture examples/tms_fixture.json

# List all registered rules
uv run isc rules
```

### Adding a New Rule
1. Choose the appropriate module in `isc/rules/` (`resource.py`, `metrics.py`, `logs.py`, `traces.py`, `profiling.py`). If adding a new module, import it in `isc/rules/__init__.py` so `@register_rule` executes on import.
2. Decorate your evaluator function `(bundle: TelemetryBundle, config: TargetConfig) -> RuleResult` with `@register_rule(rule_id=..., signal=..., title=..., impact=..., description=...)`.
3. **Always handle missing data gracefully:** if the required signal/data is empty, return `skipped_result(...)` instead of failing (unless the rule specifically checks for absence of telemetry, like `LOG-004` or `PRO-001` when configured).
4. Include concise `summary`, actionable `evidence` (capped to a few examples), and concrete `remediation` text.
5. Add both passing and failing test cases in `tests/test_rules.py` and run `uv run pytest -v`.

### Modifying `GrafanaMCPProvider` (`isc/providers/mcp_grafana.py`)
* Check tool availability against the `available` set returned by `session.list_tools()` before calling MCP tools.
* Keep queries **bounded** (`limit`, time window `lookback`) and prefer aggregate queries (`count_over_time`, `count by (__name__)`) over pulling unbounded raw payloads.
* Wrap per-signal collection in `try/except` and record errors in `bundle.collection_errors[signal]` so one failing datasource does not abort scoring for the remaining signals.

### Running Live Against Grafana
1. **Remote `mcp-grafana` web service (Streamable HTTP / SSE, no auth required by default):**
   - Set `mcp.url` in `isc.yaml` (e.g. `http://host:8000/mcp` or `http://host:8000/sse`) or export `GRAFANA_MCP_URL`.
2. **Local `stdio` mode (`uvx mcp-grafana`):**
   - Leave `mcp.url` and `GRAFANA_MCP_URL` unset and set `GRAFANA_URL` + `GRAFANA_SERVICE_ACCOUNT_TOKEN`.
3. Run `uv run isc score --config isc.yaml` (or `--format json` / `--min-score 80` for CI).
