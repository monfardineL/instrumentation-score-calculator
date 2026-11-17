# instrumentation-score-calculator (`isc`)

CLI tool to evaluate telemetry instrumentation quality (`0–100`) across **Prometheus/Mimir**, **Loki**, **Tempo**, and **Pyroscope** via **`mcp-grafana`**, scoped by a key-value selector (e.g., `appid=tms`) and explicit Grafana datasource UIDs.

## Quickstart

```bash
uv sync --extra dev
uv run pytest
```

### Run offline with the example fixture
```bash
uv run isc score --config examples/isc.yaml --fixture examples/tms_fixture.json
```

### Run against a remote `mcp-grafana` web service (no auth required)
1. Create or edit `isc.yaml` (`uv run isc init --selector appid=tms`) with your Grafana datasource UIDs and your MCP service URL (e.g. `http://localhost:8000/mcp` or `http://localhost:8000/sse`), or set `GRAFANA_MCP_URL`:
   ```bash
   export GRAFANA_MCP_URL="http://your-mcp-grafana-host:8000/mcp"
   ```
   *(By default `transport: auto` uses SSE if the URL ends with `/sse`, otherwise Streamable HTTP; no auth headers are sent unless you configure `mcp.headers`.)*
2. Run the scorer:
   ```bash
   uv run isc score --config isc.yaml
   ```

### Alternative: Run with local `mcp-grafana` (`stdio`)
If you don't have `mcp-grafana` running as a web service, leave `mcp.url` and `GRAFANA_MCP_URL` unset and provide your Grafana credentials so `isc` spawns `uvx mcp-grafana` locally:
```bash
export GRAFANA_URL="https://your-grafana.example.com"
export GRAFANA_SERVICE_ACCOUNT_TOKEN="glsa_..."
uv run isc score --config isc.yaml
```

### Useful options
- `--selector appid=other` — override the target selector from the CLI
- `--format json|markdown|table` — export results for CI or reports
- `--min-score 80` — exit with code `1` if the overall score is below `80`
- `uv run isc rules` — list all registered rules

### Generate an HTML report
Use the standalone [scripts/json_to_html.py](scripts/json_to_html.py) script (stdlib-only) to convert JSON output into a self-contained HTML report:

```bash
# Pipe directly from `isc`
uv run isc score --config isc.yaml --format json | python3 scripts/json_to_html.py - -o report.html

# Or convert an existing JSON file
python3 scripts/json_to_html.py report.json -o report.html
```
