"""
Core data models for OCPP 1.6 log analysis.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageType(Enum):
    """OCPP 1.6 message type identifiers."""
    CALL = 2
    CALLRESULT = 3
    CALLERROR = 4


class ConnectorStatus(Enum):
    """OCPP 1.6 connector status values."""
    AVAILABLE = "Available"
    PREPARING = "Preparing"
    CHARGING = "Charging"
    SUSPENDED_EVSE = "SuspendedEVSE"
    SUSPENDED_EV = "SuspendedEV"
    FINISHING = "Finishing"
    RESERVED = "Reserved"
    UNAVAILABLE = "Unavailable"
    FAULTED = "Faulted"


# All OCPP 1.6 error codes from StatusNotification
OCPP16_ERROR_CODES = {
    "ConnectorLockFailure", "EVCommunicationError", "GroundFailure",
    "HighTemperature", "InternalError", "LocalListConflict", "NoError",
    "OtherError", "OverCurrentFailure", "PowerMeterFailure",
    "PowerSwitchFailure", "ReaderFailure", "ResetFailure",
    "UnderVoltage", "OverVoltage", "WeakSignal",
}

# Stop reason values
OCPP16_STOP_REASONS = {
    "DeAuthorized", "EmergencyStop", "EVDisconnected", "HardReset",
    "Local", "Other", "PowerLoss", "Reboot", "Remote", "SoftReset",
    "UnlockCommand",
}


@dataclass
class OCPPMessage:
    """
    Represents a single parsed OCPP 1.6 message.

    OCPP 1.6 message frame format:
      CALL:        [2, "<messageId>", "<action>", {<payload>}]
      CALLRESULT:  [3, "<messageId>", {<payload>}]
      CALLERROR:   [4, "<messageId>", "<errorCode>", "<errorDescription>", {<details>}]
    """
    message_type: MessageType
    message_id: str
    action: Optional[str]           # Only present on CALL messages
    payload: Dict[str, Any]
    timestamp: Optional[datetime] = None
    raw: Optional[str] = None

    # Only populated for CALLERROR
    error_code: Optional[str] = None
    error_description: Optional[str] = None

    def is_call(self) -> bool:
        return self.message_type == MessageType.CALL

    def is_result(self) -> bool:
        return self.message_type == MessageType.CALLRESULT

    def is_error(self) -> bool:
        return self.message_type == MessageType.CALLERROR


@dataclass
class ChargingSession:
    """
    Represents a complete (or in-progress) EV charging session derived
    from StartTransaction / StopTransaction OCPP message pairs.
    """
    transaction_id: int
    connector_id: int
    id_tag: str
    start_time: Optional[datetime]
    stop_time: Optional[datetime]
    start_meter_wh: float           # Meter reading at session start (Wh)
    stop_meter_wh: Optional[float] = None   # Meter reading at session end (Wh)
    stop_reason: Optional[str] = None
    is_complete: bool = False

    @property
    def energy_kwh(self) -> Optional[float]:
        """Energy delivered in this session in kWh."""
        if self.stop_meter_wh is not None:
            return round((self.stop_meter_wh - self.start_meter_wh) / 1000, 3)
        return None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Session duration in seconds."""
        if self.start_time and self.stop_time:
            return (self.stop_time - self.start_time).total_seconds()
        return None

    @property
    def duration_minutes(self) -> Optional[float]:
        """Session duration in minutes (rounded to 1 decimal)."""
        d = self.duration_seconds
        return round(d / 60, 1) if d is not None else None

    @property
    def avg_power_kw(self) -> Optional[float]:
        """Average charging power in kW."""
        if self.energy_kwh is not None and self.duration_seconds:
            hours = self.duration_seconds / 3600
            if hours > 0:
                return round(self.energy_kwh / hours, 2)
        return None

    def __repr__(self) -> str:
        return (
            f"ChargingSession(txn={self.transaction_id}, connector={self.connector_id}, "
            f"tag={self.id_tag!r}, energy={self.energy_kwh}kWh, "
            f"duration={self.duration_minutes}min)"
        )


@dataclass
class FaultEvent:
    """
    Represents a fault or error condition reported by the charger,
    sourced from StatusNotification messages or CALLERROR frames.
    """
    timestamp: Optional[datetime]
    connector_id: int
    error_code: str
    status: str
    info: Optional[str] = None
    vendor_error_code: Optional[str] = None
    source: str = "StatusNotification"     # "StatusNotification" or "CallError"

    @property
    def is_critical(self) -> bool:
        """True if this is a Faulted status or a non-recoverable error."""
        critical_codes = {
            "GroundFailure", "HighTemperature", "InternalError",
            "OverCurrentFailure", "OverVoltage", "UnderVoltage",
            "PowerSwitchFailure",
        }
        return self.status == "Faulted" or self.error_code in critical_codes

    def __repr__(self) -> str:
        return (
            f"FaultEvent(connector={self.connector_id}, "
            f"code={self.error_code!r}, status={self.status!r})"
        )


@dataclass
class AnalysisResult:
    """
    The complete output of analyzing an OCPP log file, containing
    all extracted sessions, faults, errors, and summary statistics.
    """
    sessions: List[ChargingSession] = field(default_factory=list)
    faults: List[FaultEvent] = field(default_factory=list)
    call_errors: List[OCPPMessage] = field(default_factory=list)
    total_messages: int = 0

    # Charger identity (from BootNotification)
    charger_id: Optional[str] = None
    charger_model: Optional[str] = None
    charger_vendor: Optional[str] = None
    firmware_version: Optional[str] = None

    # Log time range
    log_start: Optional[datetime] = None
    log_end: Optional[datetime] = None

    # ---- Computed summary properties ----

    @property
    def total_sessions(self) -> int:
        return len(self.sessions)

    @property
    def complete_sessions(self) -> List[ChargingSession]:
        return [s for s in self.sessions if s.is_complete]

    @property
    def total_energy_kwh(self) -> float:
        return round(sum(s.energy_kwh for s in self.sessions if s.energy_kwh is not None), 3)

    @property
    def total_faults(self) -> int:
        return len(self.faults)

    @property
    def critical_faults(self) -> List[FaultEvent]:
        return [f for f in self.faults if f.is_critical]

    @property
    def avg_session_duration_minutes(self) -> Optional[float]:
        durations = [s.duration_minutes for s in self.sessions if s.duration_minutes is not None]
        return round(sum(durations) / len(durations), 1) if durations else None

    @property
    def avg_session_energy_kwh(self) -> Optional[float]:
        energies = [s.energy_kwh for s in self.sessions if s.energy_kwh is not None]
        return round(sum(energies) / len(energies), 3) if energies else None

    @property
    def unique_id_tags(self) -> List[str]:
        return list({s.id_tag for s in self.sessions})

    def __repr__(self) -> str:
        return (
            f"AnalysisResult(sessions={self.total_sessions}, "
            f"energy={self.total_energy_kwh}kWh, faults={self.total_faults})"
        )