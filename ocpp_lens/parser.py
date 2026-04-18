"""
OCPP 1.6 log file parser.

Supports multiple log formats:
  1. Newline-delimited JSON   — one OCPP message array per line
  2. JSON array               — a file containing [[2,...], [3,...], ...]
  3. Timestamp-prefixed lines — "2024-01-01T10:00:00Z [2, ...]"
  4. Wrapped object format    — {"timestamp": "...", "message": [...]}
"""

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, List, Optional, Union

from .models import MessageType, OCPPMessage

# Regex patterns for extracting optional timestamp prefixes from log lines
_TS_ISO = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)\s+(.+)$"
)
_TS_UNIX = re.compile(r"^(\d{10,13}(?:\.\d+)?)\s+(.+)$")

_ISO_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
]


def _parse_iso(ts_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 string into a UTC-aware datetime."""
    # Handle "+05:30" style offsets
    ts_clean = ts_str.strip()
    for fmt in _ISO_FORMATS:
        try:
            dt = datetime.strptime(ts_clean, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_timestamp(line: str):
    """
    Try to split a log line into (timestamp, json_str).
    Returns (None, line) if no timestamp prefix is found.
    """
    m = _TS_ISO.match(line)
    if m:
        ts = _parse_iso(m.group(1))
        return ts, m.group(2)

    m = _TS_UNIX.match(line)
    if m:
        raw = m.group(1)
        val = float(raw)
        # Millisecond unix timestamps have 13 digits
        if val > 1e12:
            val /= 1000
        ts = datetime.fromtimestamp(val, tz=timezone.utc)
        return ts, m.group(2)

    return None, line


def _build_message(
    msg: list,
    timestamp: Optional[datetime],
    raw: str,
) -> Optional[OCPPMessage]:
    """Construct an OCPPMessage from a parsed JSON list."""
    if not msg or not isinstance(msg, list) or len(msg) < 3:
        return None

    try:
        msg_type = MessageType(int(msg[0]))
    except (ValueError, KeyError):
        return None

    message_id = str(msg[1])

    if msg_type == MessageType.CALL:
        if len(msg) < 4:
            return None
        return OCPPMessage(
            message_type=msg_type,
            message_id=message_id,
            action=str(msg[2]),
            payload=msg[3] if isinstance(msg[3], dict) else {},
            timestamp=timestamp,
            raw=raw,
        )

    if msg_type == MessageType.CALLRESULT:
        return OCPPMessage(
            message_type=msg_type,
            message_id=message_id,
            action=None,
            payload=msg[2] if isinstance(msg[2], dict) else {},
            timestamp=timestamp,
            raw=raw,
        )

    if msg_type == MessageType.CALLERROR:
        return OCPPMessage(
            message_type=msg_type,
            message_id=message_id,
            action=None,
            payload=msg[5] if len(msg) > 5 and isinstance(msg[5], dict) else {},
            error_code=str(msg[2]) if len(msg) > 2 else None,
            error_description=str(msg[3]) if len(msg) > 3 else None,
            timestamp=timestamp,
            raw=raw,
        )

    return None


def _parse_line(line: str) -> Optional[OCPPMessage]:
    """Parse a single log line into an OCPPMessage (or None if invalid)."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    timestamp, json_str = _extract_timestamp(line)

    try:
        obj = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    # Handle wrapped object: {"timestamp": "...", "message": [...]}
    if isinstance(obj, dict):
        if "message" in obj:
            if timestamp is None and "timestamp" in obj:
                timestamp = _parse_iso(str(obj["timestamp"]))
            obj = obj["message"]
        else:
            return None

    if not isinstance(obj, list):
        return None

    return _build_message(obj, timestamp, line)


class OCPPLogParser:
    """
    Parser for OCPP 1.6 log files.

    Handles four common log formats automatically:

    **Format 1 — Newline-delimited JSON** (most common):
    Each line is one OCPP message array::

        [2,"msg1","BootNotification",{"chargePointModel":"EVC-001"}]
        [3,"msg1",{"status":"Accepted","currentTime":"2024-01-01T10:00:00Z","interval":300}]

    **Format 2 — JSON array**:
    The whole file is a JSON array of message arrays::

        [[2,"msg1","BootNotification",{...}],[3,"msg1",{...}]]

    **Format 3 — Timestamp-prefixed**:
    ISO 8601 or Unix timestamp before each message::

        2024-01-01T10:00:00.000Z [2,"msg1","Heartbeat",{}]
        1704067200.123 [3,"msg1",{}]

    **Format 4 — Wrapped objects**:
    Each line is a JSON object with a "message" key::

        {"timestamp":"2024-01-01T10:00:00Z","message":[2,"msg1","Heartbeat",{}]}

    Examples::

        from ocpp_lens import OCPPLogParser

        parser = OCPPLogParser()

        # From file
        messages = parser.parse_file("charger.log")

        # From string
        messages = parser.parse_string('[2,"abc","Heartbeat",{}]')
    """

    def parse_file(self, path: Union[str, Path]) -> List[OCPPMessage]:
        """
        Parse an OCPP log file and return a list of :class:`OCPPMessage` objects.

        :param path: Path to the log file.
        :raises FileNotFoundError: If the file does not exist.
        """
        path = Path(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return self._parse_stream(f)

    def parse_string(self, text: str) -> List[OCPPMessage]:
        """
        Parse OCPP log content from a string.

        :param text: Raw log content.
        """
        return self._parse_stream(io.StringIO(text))

    def parse_stream(self, stream: IO) -> List[OCPPMessage]:
        """
        Parse OCPP log content from any file-like object.

        :param stream: A readable text stream.
        """
        return self._parse_stream(stream)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_stream(self, stream: IO) -> List[OCPPMessage]:
        content = stream.read().strip()
        if not content:
            return []

        # Try the whole content as a JSON array first
        if content.lstrip().startswith("["):
            result = self._try_json_array(content)
            if result is not None:
                return result

        # Fall back to line-by-line parsing
        messages: List[OCPPMessage] = []
        for line in content.splitlines():
            msg = _parse_line(line)
            if msg is not None:
                messages.append(msg)
        return messages

    @staticmethod
    def _try_json_array(content: str) -> Optional[List[OCPPMessage]]:
        """Try to parse content as a JSON array of messages."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, list):
            return None

        # Array of message arrays: [[2,...], [3,...], ...]
        if data and isinstance(data[0], list):
            messages = []
            for item in data:
                msg = _build_message(item, None, json.dumps(item))
                if msg:
                    messages.append(msg)
            return messages

        # Single message (array): [2, "id", "action", {}]
        if data and isinstance(data[0], int):
            msg = _build_message(data, None, content)
            return [msg] if msg else []

        return None