# ⚡ ocpp-lens

**Parse and analyze OCPP 1.6 EV charger log files in Python.**

`ocpp-lens` turns raw OCPP 1.6 JSON logs into structured charging sessions, fault events, and readable reports — with zero dependencies.

```python
from ocpp_lens import OCPPLogParser, OCPPAnalyzer, OCPPReporter

messages = OCPPLogParser().parse_file("charger.log")
result   = OCPPAnalyzer().analyze(messages)

print(result.total_sessions)       # 42
print(result.total_energy_kwh)     # 318.5
print(result.critical_faults)      # [FaultEvent(...), ...]

OCPPReporter().to_html(result, "report.html")
```

---

## Features

- **Multi-format parser** — handles newline-delimited JSON, JSON arrays, timestamp-prefixed lines, and wrapped-object formats
- **Session reconstruction** — pairs `StartTransaction` / `StopTransaction` messages to compute energy, duration, avg power, and stop reason
- **Fault detection** — extracts `StatusNotification` errors, `Faulted` / `Unavailable` states, and `CALLERROR` frames
- **Charger identity** — reads vendor, model, serial number, and firmware version from `BootNotification`
- **HTML report** — self-contained dark-theme report you can open in any browser
- **CSV export** — sessions and faults as comma-separated values
- **JSON export** — machine-friendly structured output for pipelines and dashboards
- **CLI tool** — analyze logs directly from the terminal
- **Zero dependencies** — pure Python standard library

---

## Installation

```bash
pip install ocpp-lens
```

For local development:

```bash
pip install -e ".[dev]"
```

---

## Quick Start

### Python API

```python
from ocpp_lens import OCPPLogParser, OCPPAnalyzer, OCPPReporter

# 1. Parse the log file
parser   = OCPPLogParser()
messages = parser.parse_file("charger.log")

# 2. Analyze
result = OCPPAnalyzer().analyze(messages)

# 3. Explore
print(f"Charger  : {result.charger_vendor} {result.charger_model}")
print(f"Sessions : {result.total_sessions}")
print(f"Energy   : {result.total_energy_kwh} kWh")
print(f"Faults   : {result.total_faults}")

for session in result.sessions:
    print(session)

for fault in result.faults:
    print(fault)

# 4. Export
reporter = OCPPReporter()
reporter.to_html(result, "report.html")
reporter.to_csv(result, "report.csv")
```

### Command-Line Interface

```bash
# Print summary
ocpp-lens charger.log

# Export HTML + CSV reports
ocpp-lens charger.log --html report.html --csv sessions.csv

# Export JSON report
ocpp-lens charger.log --json report.json

# Quiet mode (no terminal output)
ocpp-lens charger.log --html report.html --json report.json --quiet
```

---

## Supported Log Formats

`ocpp-lens` auto-detects the format — no configuration needed.

**Format 1 — Newline-delimited JSON** (most common):
```
[2,"msg1","BootNotification",{"chargePointModel":"EVC-001"}]
[3,"msg1",{"status":"Accepted","currentTime":"2024-01-01T10:00:00Z","interval":300}]
```

**Format 2 — JSON array**:
```json
[[2,"msg1","Heartbeat",{}],[3,"msg1",{"currentTime":"2024-01-01T10:00:00Z"}]]
```

**Format 3 — Timestamp prefix** (ISO 8601 or Unix):
```
2024-01-01T10:00:00.000Z [2,"msg1","Heartbeat",{}]
1704067200.123 [3,"msg1",{}]
```

**Format 4 — Wrapped objects**:
```json
{"timestamp":"2024-01-01T10:00:00Z","message":[2,"msg1","Heartbeat",{}]}
```

---

## Data Models

### `ChargingSession`

| Property | Type | Description |
|---|---|---|
| `transaction_id` | `int` | OCPP transaction ID |
| `connector_id` | `int` | Connector number |
| `id_tag` | `str` | RFID / ID tag used |
| `start_time` | `datetime` | Session start (UTC) |
| `stop_time` | `datetime \| None` | Session stop (UTC), `None` if ongoing |
| `energy_kwh` | `float \| None` | Energy delivered (kWh) |
| `duration_minutes` | `float \| None` | Session duration (minutes) |
| `avg_power_kw` | `float \| None` | Average charging power (kW) |
| `stop_reason` | `str \| None` | OCPP stop reason |
| `is_complete` | `bool` | `True` if a matching StopTransaction was found |

### `FaultEvent`

| Property | Type | Description |
|---|---|---|
| `timestamp` | `datetime \| None` | Fault timestamp (UTC) |
| `connector_id` | `int` | Affected connector |
| `error_code` | `str` | OCPP 1.6 error code |
| `status` | `str` | Connector status at fault time |
| `info` | `str \| None` | Additional info string |
| `is_critical` | `bool` | `True` for hardware-level faults |

### `AnalysisResult`

| Property | Type | Description |
|---|---|---|
| `sessions` | `list[ChargingSession]` | All sessions (complete + ongoing) |
| `faults` | `list[FaultEvent]` | All fault events |
| `call_errors` | `list[OCPPMessage]` | All CALLERROR frames |
| `total_energy_kwh` | `float` | Sum of all delivered energy |
| `critical_faults` | `list[FaultEvent]` | Hardware-level faults only |
| `charger_vendor` | `str \| None` | From BootNotification |
| `charger_model` | `str \| None` | From BootNotification |
| `log_start / log_end` | `datetime \| None` | Time range of the log |

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Project Structure

```text
ocpp-lens/
├── ocpp_lens/
│   ├── __init__.py
│   ├── models.py
│   ├── parser.py
│   ├── analyzer.py
│   ├── reporter.py
│   └── cli.py
├── tests/
├── examples/
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## Publish To PyPI

```bash
# Build source + wheel
python -m build

# Validate package metadata
twine check dist/*

# Upload to TestPyPI first (recommended)
twine upload --repository testpypi dist/*

# Upload to PyPI
twine upload dist/*
```

---

## License

MIT © Sahil Sandhu