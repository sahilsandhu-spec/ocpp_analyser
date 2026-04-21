"""
Tests for ocpp-lens.
Run with:  python -m pytest tests/ -v
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure the package is importable when running from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocpp_lens import OCPPAnalyzer, OCPPLogParser, OCPPReporter
from ocpp_lens.models import MessageType

SAMPLE_LOG = Path(__file__).parent.parent / "examples" / "sample_charger.log"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def parser():
    return OCPPLogParser()


@pytest.fixture()
def analyzer():
    return OCPPAnalyzer()


@pytest.fixture()
def sample_messages(parser):
    return parser.parse_file(SAMPLE_LOG)


@pytest.fixture()
def sample_result(sample_messages, analyzer):
    return analyzer.analyze(sample_messages)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestOCPPLogParser:

    def test_parse_call_message(self, parser):
        line = '[2,"msg1","Heartbeat",{}]'
        msgs = parser.parse_string(line)
        assert len(msgs) == 1
        m = msgs[0]
        assert m.message_type == MessageType.CALL
        assert m.message_id == "msg1"
        assert m.action == "Heartbeat"
        assert m.payload == {}

    def test_parse_callresult_message(self, parser):
        line = '[3,"msg1",{"currentTime":"2024-01-01T10:00:00Z"}]'
        msgs = parser.parse_string(line)
        assert len(msgs) == 1
        m = msgs[0]
        assert m.message_type == MessageType.CALLRESULT
        assert m.message_id == "msg1"
        assert m.action is None
        assert "currentTime" in m.payload

    def test_parse_callerror_message(self, parser):
        line = '[4,"msg1","GenericError","Something failed",{}]'
        msgs = parser.parse_string(line)
        assert len(msgs) == 1
        m = msgs[0]
        assert m.message_type == MessageType.CALLERROR
        assert m.error_code == "GenericError"
        assert m.error_description == "Something failed"

    def test_parse_json_array_format(self, parser):
        data = json.dumps([
            [2, "m1", "Heartbeat", {}],
            [3, "m1", {"currentTime": "2024-01-01T10:00:00Z"}],
        ])
        msgs = parser.parse_string(data)
        assert len(msgs) == 2

    def test_parse_wrapped_object_format(self, parser):
        line = '{"timestamp":"2024-01-01T10:00:00Z","message":[2,"m1","Heartbeat",{}]}'
        msgs = parser.parse_string(line)
        assert len(msgs) == 1
        assert msgs[0].timestamp is not None
        assert msgs[0].timestamp.year == 2024

    def test_parse_timestamp_prefix_format(self, parser):
        line = "2024-01-01T10:00:00Z [2,\"m1\",\"Heartbeat\",{}]"
        msgs = parser.parse_string(line)
        assert len(msgs) == 1
        assert msgs[0].timestamp is not None

    def test_ignores_empty_lines(self, parser):
        text = "\n\n[2,\"m1\",\"Heartbeat\",{}]\n\n"
        msgs = parser.parse_string(text)
        assert len(msgs) == 1

    def test_ignores_invalid_lines(self, parser):
        text = "not json at all\n[2,\"m1\",\"Heartbeat\",{}]"
        msgs = parser.parse_string(text)
        assert len(msgs) == 1

    def test_parse_sample_file(self, parser):
        msgs = parser.parse_file(SAMPLE_LOG)
        assert len(msgs) > 0

    def test_parse_empty_string(self, parser):
        msgs = parser.parse_string("")
        assert msgs == []

    def test_message_helpers(self, parser):
        msgs = parser.parse_string('[2,"m1","Heartbeat",{}]')
        m = msgs[0]
        assert m.is_call()
        assert not m.is_result()
        assert not m.is_error()


# ---------------------------------------------------------------------------
# Analyzer tests
# ---------------------------------------------------------------------------

class TestOCPPAnalyzer:

    def test_analyze_returns_result(self, sample_result):
        assert sample_result is not None

    def test_charger_identity_extracted(self, sample_result):
        assert sample_result.charger_vendor == "Exicom"
        assert sample_result.charger_model  == "EVC-7kW"
        assert sample_result.charger_id     == "EXI-2024-00312"
        assert sample_result.firmware_version == "v2.4.1"

    def test_sessions_extracted(self, sample_result):
        # 4 StartTransactions, 3 complete StopTransactions → 3 complete + 1 ongoing
        complete = sample_result.complete_sessions
        assert len(complete) == 3
        assert sample_result.total_sessions == 4

    def test_session_energy_computed(self, sample_result):
        complete = sample_result.complete_sessions
        # First session: 168500 - 150200 = 18300 Wh = 18.3 kWh
        session_1001 = next(s for s in complete if s.transaction_id == 1001)
        assert session_1001.energy_kwh == pytest.approx(18.3, rel=1e-3)

    def test_session_duration_computed(self, sample_result):
        complete = sample_result.complete_sessions
        session_1001 = next(s for s in complete if s.transaction_id == 1001)
        assert session_1001.duration_minutes == pytest.approx(150.1, rel=0.01)

    def test_session_stop_reason(self, sample_result):
        complete = sample_result.complete_sessions
        session_1002 = next(s for s in complete if s.transaction_id == 1002)
        assert session_1002.stop_reason == "EmergencyStop"

    def test_faults_extracted(self, sample_result):
        # HighTemperature + WeakSignal/Unavailable
        assert sample_result.total_faults >= 2

    def test_critical_fault_detected(self, sample_result):
        critical = sample_result.critical_faults
        assert len(critical) >= 1
        codes = {f.error_code for f in critical}
        assert "HighTemperature" in codes

    def test_call_errors_collected(self, sample_result):
        assert len(sample_result.call_errors) >= 1
        assert sample_result.call_errors[0].error_code == "GenericError"

    def test_total_energy(self, sample_result):
        assert sample_result.total_energy_kwh > 0

    def test_log_time_range(self, sample_result):
        assert sample_result.log_start is not None
        assert sample_result.log_end   is not None
        assert sample_result.log_end > sample_result.log_start

    def test_unique_id_tags(self, sample_result):
        tags = sample_result.unique_id_tags
        assert "RFID-AA-001" in tags
        assert "RFID-BB-002" in tags

    def test_analyze_empty_list(self, analyzer):
        result = analyzer.analyze([])
        assert result.total_sessions == 0
        assert result.total_faults   == 0
        assert result.total_messages == 0

    def test_avg_session_duration(self, sample_result):
        avg = sample_result.avg_session_duration_minutes
        assert avg is not None and avg > 0

    def test_ongoing_session_has_no_stop_time(self, sample_result):
        ongoing = [s for s in sample_result.sessions if not s.is_complete]
        assert len(ongoing) == 1
        assert ongoing[0].stop_time is None
        assert ongoing[0].energy_kwh is None


# ---------------------------------------------------------------------------
# ChargingSession model tests
# ---------------------------------------------------------------------------

class TestChargingSession:

    def test_energy_kwh_property(self):
        from ocpp_lens.models import ChargingSession
        s = ChargingSession(
            transaction_id=1,
            connector_id=1,
            id_tag="TEST",
            start_time=None,
            stop_time=None,
            start_meter_wh=10000.0,
            stop_meter_wh=17500.0,
        )
        assert s.energy_kwh == pytest.approx(7.5)

    def test_energy_none_when_no_stop(self):
        from ocpp_lens.models import ChargingSession
        s = ChargingSession(
            transaction_id=1,
            connector_id=1,
            id_tag="TEST",
            start_time=None,
            stop_time=None,
            start_meter_wh=10000.0,
        )
        assert s.energy_kwh is None

    def test_avg_power_kw(self):
        from ocpp_lens.models import ChargingSession
        from datetime import datetime, timezone, timedelta
        t0 = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(hours=2)
        s = ChargingSession(
            transaction_id=1,
            connector_id=1,
            id_tag="TEST",
            start_time=t0,
            stop_time=t1,
            start_meter_wh=0.0,
            stop_meter_wh=14000.0,
        )
        assert s.avg_power_kw == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# Reporter tests
# ---------------------------------------------------------------------------

class TestOCPPReporter:

    def test_to_csv_returns_string(self, sample_result):
        reporter = OCPPReporter()
        csv_str = reporter.to_csv(sample_result)
        assert isinstance(csv_str, str)
        assert "CHARGING SESSIONS" in csv_str
        assert "FAULT EVENTS" in csv_str

    def test_to_html_returns_string(self, sample_result):
        reporter = OCPPReporter()
        html = reporter.to_html(sample_result)
        assert isinstance(html, str)
        assert "ocpp-lens" in html.lower() or "OCPP" in html
        assert "<table>" in html

    def test_to_json_returns_string(self, sample_result):
        reporter = OCPPReporter()
        json_str = reporter.to_json(sample_result)
        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert "summary" in data
        assert "sessions" in data
        assert data["summary"]["total_sessions"] == sample_result.total_sessions

    def test_html_contains_charger_info(self, sample_result):
        html = OCPPReporter().to_html(sample_result)
        assert "Exicom" in html
        assert "EVC-7kW" in html

    def test_html_contains_session_count(self, sample_result):
        html = OCPPReporter().to_html(sample_result)
        assert str(sample_result.total_sessions) in html

    def test_to_csv_file_write(self, sample_result, tmp_path):
        out = tmp_path / "report.csv"
        reporter = OCPPReporter()
        reporter.to_csv(sample_result, str(out))
        assert out.exists()
        assert out.stat().st_size > 0

    def test_to_html_file_write(self, sample_result, tmp_path):
        out = tmp_path / "report.html"
        reporter = OCPPReporter()
        reporter.to_html(sample_result, str(out))
        assert out.exists()
        assert out.stat().st_size > 0

    def test_to_json_file_write(self, sample_result, tmp_path):
        out = tmp_path / "report.json"
        reporter = OCPPReporter()
        reporter.to_json(sample_result, str(out))
        assert out.exists()
        assert out.stat().st_size > 0