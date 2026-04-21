"""
ocpp-lens
~~~~~~~~~

A Python library for parsing and analyzing OCPP 1.6 EV charger log files.

Quick start::

    from ocpp_lens import OCPPLogParser, OCPPAnalyzer, OCPPReporter

    messages = OCPPLogParser().parse_file("charger.log")
    result   = OCPPAnalyzer().analyze(messages)

    print(result.total_sessions)    # 42
    print(result.total_energy_kwh)  # 318.5

    OCPPReporter().to_html(result, "report.html")
"""

from .analyzer import OCPPAnalyzer
from .models import AnalysisResult, ChargingSession, FaultEvent, MessageType, OCPPMessage
from .parser import OCPPLogParser
from .reporter import OCPPReporter

__version__ = "0.2.0"
__author__  = "Sahil Sandhu"
__email__   = "sahilsandhu@alumni.iitm.ac.in"
__license__ = "MIT"

__all__ = [
    # Core pipeline
    "OCPPLogParser",
    "OCPPAnalyzer",
    "OCPPReporter",
    # Data models
    "OCPPMessage",
    "ChargingSession",
    "FaultEvent",
    "AnalysisResult",
    "MessageType",
    # Package metadata
    "__version__",
]