"""
Report generation for OCPP analysis results.

Supports two output formats:
  - HTML  — a self-contained dark-theme report you can open in any browser
  - CSV   — sessions and faults exported as comma-separated values
"""

import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional

from .models import AnalysisResult


class OCPPReporter:
    """
    Generates reports from an :class:`~ocpp_lens.models.AnalysisResult`.

    Example::

        from ocpp_lens import OCPPLogParser, OCPPAnalyzer, OCPPReporter

        result   = OCPPAnalyzer().analyze(OCPPLogParser().parse_file("log.json"))
        reporter = OCPPReporter()

        reporter.to_html(result, "report.html")   # save HTML report
        reporter.to_csv(result,  "report.csv")    # save CSV report
        reporter.to_json(result, "report.json")   # save JSON report
        html_str = reporter.to_html(result)       # get HTML as string
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_html(
        self,
        result: AnalysisResult,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generate a self-contained HTML report.

        :param result:      Analysis result to render.
        :param output_path: If provided, write HTML to this file path.
        :returns:           The HTML as a string.
        """
        html = self._build_html(result)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as fp:
                fp.write(html)
        return html

    def to_csv(
        self,
        result: AnalysisResult,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generate a CSV report containing sessions and faults.

        :param result:      Analysis result to export.
        :param output_path: If provided, write CSV to this file path.
        :returns:           The CSV content as a string.
        """
        buf = io.StringIO()
        writer = csv.writer(buf)

        # --- Sessions ---
        writer.writerow(["CHARGING SESSIONS"])
        writer.writerow([
            "Transaction ID", "Connector ID", "ID Tag",
            "Start Time (UTC)", "Stop Time (UTC)",
            "Duration (min)", "Energy (kWh)", "Avg Power (kW)", "Stop Reason", "Complete",
        ])
        for s in result.sessions:
            writer.writerow([
                s.transaction_id,
                s.connector_id,
                s.id_tag,
                s.start_time.isoformat() if s.start_time else "",
                s.stop_time.isoformat()  if s.stop_time  else "Ongoing",
                s.duration_minutes or "",
                s.energy_kwh       or "",
                s.avg_power_kw     or "",
                s.stop_reason      or "",
                "Yes" if s.is_complete else "No",
            ])

        writer.writerow([])

        # --- Faults ---
        writer.writerow(["FAULT EVENTS"])
        writer.writerow([
            "Timestamp (UTC)", "Connector ID", "Error Code",
            "Status", "Info", "Vendor Error Code", "Source", "Critical",
        ])
        for f in result.faults:
            writer.writerow([
                f.timestamp.isoformat() if f.timestamp else "",
                f.connector_id,
                f.error_code,
                f.status,
                f.info             or "",
                f.vendor_error_code or "",
                f.source,
                "Yes" if f.is_critical else "No",
            ])

        writer.writerow([])

        # --- Call Errors ---
        if result.call_errors:
            writer.writerow(["CALL ERRORS"])
            writer.writerow(["Message ID", "Error Code", "Description"])
            for e in result.call_errors:
                writer.writerow([e.message_id, e.error_code or "", e.error_description or ""])

        content = buf.getvalue()
        if output_path:
            with open(output_path, "w", encoding="utf-8", newline="") as fp:
                fp.write(content)
        return content

    def to_json(
        self,
        result: AnalysisResult,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generate a structured JSON report.

        :param result:      Analysis result to export.
        :param output_path: If provided, write JSON to this file path.
        :returns:           The JSON content as a string.
        """
        payload = {
            "summary": {
                "total_messages": result.total_messages,
                "total_sessions": result.total_sessions,
                "complete_sessions": len(result.complete_sessions),
                "ongoing_sessions": result.total_sessions - len(result.complete_sessions),
                "total_energy_kwh": result.total_energy_kwh,
                "avg_session_duration_minutes": result.avg_session_duration_minutes,
                "avg_session_energy_kwh": result.avg_session_energy_kwh,
                "total_faults": result.total_faults,
                "critical_faults": len(result.critical_faults),
                "call_errors": len(result.call_errors),
                "unique_id_tags": result.unique_id_tags,
            },
            "charger": {
                "id": result.charger_id,
                "vendor": result.charger_vendor,
                "model": result.charger_model,
                "firmware_version": result.firmware_version,
            },
            "log_range": {
                "start": result.log_start.isoformat() if result.log_start else None,
                "end": result.log_end.isoformat() if result.log_end else None,
            },
            "sessions": [
                {
                    "transaction_id": s.transaction_id,
                    "connector_id": s.connector_id,
                    "id_tag": s.id_tag,
                    "start_time": s.start_time.isoformat() if s.start_time else None,
                    "stop_time": s.stop_time.isoformat() if s.stop_time else None,
                    "duration_minutes": s.duration_minutes,
                    "energy_kwh": s.energy_kwh,
                    "avg_power_kw": s.avg_power_kw,
                    "stop_reason": s.stop_reason,
                    "is_complete": s.is_complete,
                }
                for s in result.sessions
            ],
            "faults": [
                {
                    "timestamp": f.timestamp.isoformat() if f.timestamp else None,
                    "connector_id": f.connector_id,
                    "error_code": f.error_code,
                    "status": f.status,
                    "info": f.info,
                    "vendor_error_code": f.vendor_error_code,
                    "source": f.source,
                    "is_critical": f.is_critical,
                }
                for f in result.faults
            ],
            "call_errors": [
                {
                    "message_id": e.message_id,
                    "error_code": e.error_code,
                    "error_description": e.error_description,
                }
                for e in result.call_errors
            ],
        }

        content = json.dumps(payload, indent=2, sort_keys=True)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as fp:
                fp.write(content)
        return content

    # ------------------------------------------------------------------
    # HTML builder
    # ------------------------------------------------------------------

    def _build_html(self, result: AnalysisResult) -> str:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        log_range = "N/A"
        if result.log_start and result.log_end:
            log_range = (
                f"{result.log_start.strftime('%Y-%m-%d %H:%M')} UTC"
                f" → "
                f"{result.log_end.strftime('%Y-%m-%d %H:%M')} UTC"
            )

        # Charger identity banner
        charger_line = ""
        parts = []
        if result.charger_vendor:
            parts.append(result.charger_vendor)
        if result.charger_model:
            parts.append(result.charger_model)
        if result.charger_id:
            parts.append(f"<code>{result.charger_id}</code>")
        if result.firmware_version:
            parts.append(f"FW: {result.firmware_version}")
        if parts:
            charger_line = (
                f'<p class="charger-info">⚡ {" &nbsp;·&nbsp; ".join(parts)}</p>'
            )

        # Stat cards
        fault_color  = "red"   if result.total_faults      > 0 else "green"
        error_color  = "red"   if result.call_errors        else "green"

        stats_html = f"""
        <div class="stats">
            {self._stat("Sessions",     result.total_sessions,                          "blue")}
            {self._stat("Energy",       f"{result.total_energy_kwh} kWh",              "green")}
            {self._stat("Avg Duration", f"{result.avg_session_duration_minutes or '—'} min", "yellow")}
            {self._stat("Avg Energy",   f"{result.avg_session_energy_kwh or '—'} kWh", "purple")}
            {self._stat("Faults",       result.total_faults,                            fault_color)}
            {self._stat("Call Errors",  len(result.call_errors),                        error_color)}
        </div>
        """

        # Sessions table
        if result.sessions:
            rows = ""
            for s in result.sessions:
                cls = "complete" if s.is_complete else "ongoing"
                stop_cell = (
                    s.stop_time.strftime("%Y-%m-%d %H:%M:%S")
                    if s.stop_time
                    else '<span class="badge ongoing">Ongoing</span>'
                )
                rows += f"""
                <tr class="{cls}">
                    <td>{s.transaction_id}</td>
                    <td>{s.connector_id}</td>
                    <td><code>{s.id_tag}</code></td>
                    <td>{s.start_time.strftime('%Y-%m-%d %H:%M:%S') if s.start_time else '—'}</td>
                    <td>{stop_cell}</td>
                    <td>{s.duration_minutes or '—'} min</td>
                    <td><strong>{s.energy_kwh or '—'}</strong> kWh</td>
                    <td>{s.avg_power_kw or '—'} kW</td>
                    <td>{s.stop_reason or '—'}</td>
                </tr>"""
            session_section = f"""
            <table>
              <thead><tr>
                <th>Txn ID</th><th>Connector</th><th>ID Tag</th>
                <th>Start (UTC)</th><th>Stop (UTC)</th>
                <th>Duration</th><th>Energy</th><th>Avg Power</th><th>Reason</th>
              </tr></thead>
              <tbody>{rows}</tbody>
            </table>"""
        else:
            session_section = "<p class='empty'>No sessions found in this log.</p>"

        # Faults table
        if result.faults:
            rows = ""
            for f in result.faults:
                sev = "high" if f.is_critical else "medium"
                rows += f"""
                <tr>
                    <td>{f.timestamp.strftime('%Y-%m-%d %H:%M:%S') if f.timestamp else '—'}</td>
                    <td>{f.connector_id}</td>
                    <td><span class="badge {sev}">{f.error_code}</span></td>
                    <td>{f.status}</td>
                    <td>{f.info or '—'}</td>
                    <td>{f.vendor_error_code or '—'}</td>
                </tr>"""
            fault_section = f"""
            <table>
              <thead><tr>
                <th>Timestamp (UTC)</th><th>Connector</th><th>Error Code</th>
                <th>Status</th><th>Info</th><th>Vendor Code</th>
              </tr></thead>
              <tbody>{rows}</tbody>
            </table>"""
        else:
            fault_section = "<p class='empty'>✓ No faults detected in this log.</p>"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OCPP Lens — Report</title>
<style>
:root {{
  --bg:       #0d1117;
  --surface:  #161b22;
  --surface2: #21262d;
  --border:   #30363d;
  --text:     #e6edf3;
  --muted:    #7d8590;
  --accent:   #58a6ff;
  --green:    #3fb950;
  --yellow:   #d29922;
  --red:      #f85149;
  --blue:     #58a6ff;
  --purple:   #bc8cff;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  padding: 32px 24px;
  max-width: 1200px;
  margin: 0 auto;
}}
.header {{
  border-bottom: 1px solid var(--border);
  padding-bottom: 20px;
  margin-bottom: 28px;
}}
.header h1 {{
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: -0.02em;
}}
.header p {{
  color: var(--muted);
  font-size: 0.82rem;
  margin-top: 6px;
}}
.charger-info {{
  color: var(--muted);
  font-size: 0.84rem;
  margin-top: 8px;
}}
.charger-info code {{
  background: var(--surface2);
  padding: 1px 6px;
  border-radius: 4px;
  color: var(--text);
  font-size: 0.8rem;
}}
.stats {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 14px;
  margin-bottom: 36px;
}}
.stat {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px;
}}
.stat .label {{
  color: var(--muted);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-weight: 500;
}}
.stat .value {{
  font-size: 1.8rem;
  font-weight: 700;
  margin-top: 8px;
  line-height: 1;
}}
.stat .value.green  {{ color: var(--green);  }}
.stat .value.red    {{ color: var(--red);    }}
.stat .value.blue   {{ color: var(--blue);   }}
.stat .value.yellow {{ color: var(--yellow); }}
.stat .value.purple {{ color: var(--purple); }}

section {{ margin-bottom: 36px; }}
section h2 {{
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
}}
.count {{
  background: var(--surface2);
  color: var(--muted);
  font-size: 0.74rem;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 400;
}}
.table-wrap {{
  overflow-x: auto;
  border-radius: 10px;
  border: 1px solid var(--border);
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}}
th {{
  background: var(--surface);
  color: var(--muted);
  font-weight: 500;
  text-align: left;
  padding: 10px 14px;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}}
td {{
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
  white-space: nowrap;
}}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: var(--surface2); }}
tr.ongoing td {{ color: var(--muted); }}
code {{
  background: var(--surface2);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.8rem;
}}
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.73rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}}
.badge.high    {{ background: rgba(248,81,73,0.15); color: var(--red);    }}
.badge.medium  {{ background: rgba(210,153,34,0.15); color: var(--yellow); }}
.badge.ongoing {{ background: rgba(88,166,255,0.15); color: var(--blue);   }}
.empty {{
  color: var(--muted);
  font-style: italic;
  padding: 28px;
  text-align: center;
  font-size: 0.88rem;
}}
.footer {{
  color: var(--muted);
  font-size: 0.75rem;
  border-top: 1px solid var(--border);
  padding-top: 16px;
  margin-top: 16px;
}}
</style>
</head>
<body>

<div class="header">
  <h1>⚡ OCPP Lens — Charger Log Report</h1>
  <p>Log period: {log_range} &nbsp;·&nbsp; Generated: {generated}</p>
  {charger_line}
</div>

{stats_html}

<section>
  <h2>Charging Sessions <span class="count">{result.total_sessions}</span></h2>
  <div class="table-wrap">{session_section}</div>
</section>

<section>
  <h2>Fault Events <span class="count">{result.total_faults}</span></h2>
  <div class="table-wrap">{fault_section}</div>
</section>

<div class="footer">
  Generated by <strong>ocpp-lens</strong> &nbsp;·&nbsp;
  OCPP 1.6 Log Analyzer &nbsp;·&nbsp;
  <a href="https://pypi.org/project/ocpp-lens/" style="color:var(--accent);">PyPI</a>
</div>
</body>
</html>"""

    @staticmethod
    def _stat(label: str, value, color: str = "") -> str:
        color_class = f' class="value {color}"' if color else ' class="value"'
        return f"""
        <div class="stat">
          <div class="label">{label}</div>
          <div{color_class}>{value}</div>
        </div>"""