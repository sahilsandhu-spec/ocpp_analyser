"""
OCPP 1.6 log analyzer.

Correlates CALL / CALLRESULT message pairs to reconstruct charging sessions
and extracts fault events from StatusNotification messages and CALLERRORs.
"""

from datetime import datetime
from typing import Dict, List, Optional

from .models import (
    AnalysisResult,
    ChargingSession,
    FaultEvent,
    MessageType,
    OCPPMessage,
)
from .parser import _parse_iso


class OCPPAnalyzer:
    """
    Analyzes a list of parsed OCPP 1.6 messages to produce an
    :class:`~ocpp_lens.models.AnalysisResult`.

    What it does:

    * **Sessions** — correlates ``StartTransaction`` CALLs with their
      CALLRESULTs (to get ``transactionId``), then pairs them with
      ``StopTransaction`` CALLs to compute energy, duration, and stop reason.

    * **Faults** — collects ``StatusNotification`` messages where
      ``errorCode != "NoError"`` or ``status`` is ``Faulted`` / ``Unavailable``.

    * **Call errors** — collects all ``CALLERROR`` frames.

    * **Charger identity** — extracts ``vendor``, ``model``, ``serial``,
      and ``firmwareVersion`` from the first ``BootNotification``.

    Example::

        from ocpp_lens import OCPPLogParser, OCPPAnalyzer

        messages = OCPPLogParser().parse_file("charger.log")
        result   = OCPPAnalyzer().analyze(messages)

        print(result.total_sessions)       # 42
        print(result.total_energy_kwh)     # 318.5
        print(result.critical_faults)      # [FaultEvent(...), ...]
    """

    # StatusNotification errorCodes that indicate genuine hardware faults
    CRITICAL_FAULT_CODES = {
        "ConnectorLockFailure", "EVCommunicationError", "GroundFailure",
        "HighTemperature", "InternalError", "OverCurrentFailure",
        "PowerMeterFailure", "PowerSwitchFailure", "ReaderFailure",
        "ResetFailure", "UnderVoltage", "OverVoltage", "WeakSignal",
    }

    def analyze(self, messages: List[OCPPMessage]) -> AnalysisResult:
        """
        Analyze a list of OCPP messages and return a complete
        :class:`~ocpp_lens.models.AnalysisResult`.

        :param messages: Messages produced by :class:`~ocpp_lens.OCPPLogParser`.
        """
        result = AnalysisResult(total_messages=len(messages))

        if not messages:
            return result

        # ------------------------------------------------------------------
        # 1. Compute log time range
        # ------------------------------------------------------------------
        timestamped = [m for m in messages if m.timestamp]
        if timestamped:
            result.log_start = min(m.timestamp for m in timestamped)
            result.log_end   = max(m.timestamp for m in timestamped)

        # ------------------------------------------------------------------
        # 2. Build index maps for message correlation
        # ------------------------------------------------------------------
        calls:   Dict[str, OCPPMessage] = {}   # message_id → CALL
        results: Dict[str, OCPPMessage] = {}   # message_id → CALLRESULT

        for msg in messages:
            if msg.message_type == MessageType.CALL:
                calls[msg.message_id] = msg
            elif msg.message_type == MessageType.CALLRESULT:
                results[msg.message_id] = msg
            elif msg.message_type == MessageType.CALLERROR:
                result.call_errors.append(msg)

        # ------------------------------------------------------------------
        # 3. Extract charger identity from first BootNotification
        # ------------------------------------------------------------------
        for msg in messages:
            if msg.message_type == MessageType.CALL and msg.action == "BootNotification":
                p = msg.payload
                result.charger_id      = (
                    p.get("chargePointSerialNumber")
                    or p.get("chargeBoxSerialNumber")
                )
                result.charger_model   = p.get("chargePointModel")
                result.charger_vendor  = p.get("chargePointVendor")
                result.firmware_version = p.get("firmwareVersion")
                break

        # ------------------------------------------------------------------
        # 4. Reconstruct charging sessions
        # ------------------------------------------------------------------
        result.sessions = self._extract_sessions(calls, results)

        # ------------------------------------------------------------------
        # 5. Collect fault events
        # ------------------------------------------------------------------
        result.faults = self._extract_faults(messages)

        return result

    # ------------------------------------------------------------------
    # Session extraction
    # ------------------------------------------------------------------

    def _extract_sessions(
        self,
        calls:   Dict[str, OCPPMessage],
        results: Dict[str, OCPPMessage],
    ) -> List[ChargingSession]:

        pending: Dict[int, ChargingSession] = {}   # transaction_id → session
        completed: List[ChargingSession] = []

        # --- Pass 1: StartTransaction calls → open sessions ---
        for msg_id, msg in calls.items():
            if msg.action != "StartTransaction":
                continue

            result_msg = results.get(msg_id)
            if result_msg is None:
                continue  # No CALLRESULT → can't get transaction_id

            transaction_id = result_msg.payload.get("transactionId")
            if transaction_id is None:
                continue

            p = msg.payload
            start_time = _parse_iso(p.get("timestamp", "")) or msg.timestamp

            session = ChargingSession(
                transaction_id=int(transaction_id),
                connector_id=int(p.get("connectorId", 0)),
                id_tag=p.get("idTag", "Unknown"),
                start_time=start_time,
                stop_time=None,
                start_meter_wh=float(p.get("meterStart", 0)),
            )
            pending[int(transaction_id)] = session

        # --- Pass 2: StopTransaction calls → close sessions ---
        for msg_id, msg in calls.items():
            if msg.action != "StopTransaction":
                continue

            p = msg.payload
            txn_id = p.get("transactionId")
            if txn_id is None:
                continue
            txn_id = int(txn_id)

            session = pending.pop(txn_id, None)
            if session is None:
                # Session started before the log window — create a partial entry
                session = ChargingSession(
                    transaction_id=txn_id,
                    connector_id=0,
                    id_tag=p.get("idTag", "Unknown"),
                    start_time=None,
                    stop_time=None,
                    start_meter_wh=0.0,
                )

            session.stop_time     = _parse_iso(p.get("timestamp", "")) or msg.timestamp
            session.stop_meter_wh = float(p["meterStop"]) if "meterStop" in p else None
            session.stop_reason   = p.get("reason")
            session.is_complete   = True
            completed.append(session)

        # Remaining pending sessions started but never stopped in this log window
        incomplete = list(pending.values())

        all_sessions = completed + incomplete
        all_sessions.sort(key=lambda s: s.start_time or datetime.min)
        return all_sessions

    # ------------------------------------------------------------------
    # Fault extraction
    # ------------------------------------------------------------------

    def _extract_faults(self, messages: List[OCPPMessage]) -> List[FaultEvent]:
        faults: List[FaultEvent] = []

        for msg in messages:
            if msg.message_type != MessageType.CALL:
                continue
            if msg.action != "StatusNotification":
                continue

            p = msg.payload
            error_code = p.get("errorCode", "NoError")
            status     = p.get("status", "")

            is_error_code = error_code not in ("NoError", "")
            is_bad_status = status in ("Faulted", "Unavailable")

            if is_error_code or is_bad_status:
                ts = _parse_iso(p.get("timestamp", "")) or msg.timestamp
                faults.append(FaultEvent(
                    timestamp=ts,
                    connector_id=int(p.get("connectorId", 0)),
                    error_code=error_code,
                    status=status,
                    info=p.get("info"),
                    vendor_error_code=p.get("vendorErrorCode"),
                    source="StatusNotification",
                ))

        faults.sort(key=lambda f: f.timestamp or datetime.min)
        return faults