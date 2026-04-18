"""
ocpp-lens command-line interface.

Usage:
    ocpp-lens charger.log
    ocpp-lens charger.log --html report.html --csv report.csv
    ocpp-lens charger.log --sessions-only
    ocpp-lens charger.log --faults-only
"""

import argparse
import sys
from pathlib import Path

from .analyzer import OCPPAnalyzer
from .parser import OCPPLogParser
from .reporter import OCPPReporter


def _print_summary(result) -> None:
    """Print a colourised summary table to stdout."""
    # ANSI colours (graceful fallback if not supported)
    BOLD  = "\033[1m"
    CYAN  = "\033[36m"
    GREEN = "\033[32m"
    YELLOW= "\033[33m"
    RED   = "\033[31m"
    RESET = "\033[0m"

    def coloured(text, colour):
        return f"{colour}{text}{RESET}" if sys.stdout.isatty() else str(text)

    print()
    print(coloured("=" * 52, CYAN))
    print(coloured("  ⚡  OCPP LENS — ANALYSIS SUMMARY", BOLD))
    print(coloured("=" * 52, CYAN))

    if result.charger_vendor or result.charger_model:
        print(f"  Charger  : {result.charger_vendor or ''} {result.charger_model or ''}".rstrip())
    if result.charger_id:
        print(f"  Serial   : {result.charger_id}")
    if result.firmware_version:
        print(f"  Firmware : {result.firmware_version}")
    if result.log_start and result.log_end:
        print(f"  Period   : {result.log_start.strftime('%Y-%m-%d %H:%M')} UTC"
              f" → {result.log_end.strftime('%Y-%m-%d %H:%M')} UTC")

    print(coloured("  " + "-" * 50, CYAN))
    print(f"  Sessions : {coloured(result.total_sessions, CYAN)}"
          f"  ({result.total_sessions - len(result.complete_sessions)} ongoing)")
    print(f"  Energy   : {coloured(str(result.total_energy_kwh) + ' kWh', GREEN)}")
    print(f"  Avg Dur  : {coloured(str(result.avg_session_duration_minutes or 'N/A') + ' min', YELLOW)}")
    print(f"  Faults   : {coloured(result.total_faults, RED if result.total_faults else GREEN)}")
    print(f"  Errors   : {coloured(len(result.call_errors), RED if result.call_errors else GREEN)}")
    print(f"  Messages : {result.total_messages}")
    print(coloured("=" * 52, CYAN))

    if result.sessions:
        print("\n  Recent sessions:")
        for s in result.sessions[-5:]:
            energy = f"{s.energy_kwh} kWh" if s.energy_kwh else "—"
            dur    = f"{s.duration_minutes} min" if s.duration_minutes else "Ongoing"
            print(f"    #{s.transaction_id:>6}  connector={s.connector_id}  "
                  f"tag={s.id_tag:<20}  {dur:<12}  {energy}")

    if result.faults:
        print(f"\n  {coloured('Fault events:', RED)}")
        for f in result.faults[:5]:
            ts = f.timestamp.strftime("%Y-%m-%d %H:%M") if f.timestamp else "—"
            print(f"    [{ts}] connector={f.connector_id}  "
                  f"{f.error_code} ({f.status})")
        if len(result.faults) > 5:
            print(f"    ... and {len(result.faults) - 5} more")

    print()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="ocpp-lens",
        description="Analyze OCPP 1.6 EV charger log files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  ocpp-lens charger.log
  ocpp-lens charger.log --html report.html --csv sessions.csv
  ocpp-lens charger.log --faults-only
        """,
    )

    parser.add_argument(
        "logfile",
        help="Path to the OCPP 1.6 log file (JSON, newline-delimited JSON, or mixed).",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        help="Save an HTML report to FILE.",
    )
    parser.add_argument(
        "--csv",
        metavar="FILE",
        help="Save a CSV report to FILE.",
    )
    parser.add_argument(
        "--sessions-only",
        action="store_true",
        help="Only print charging session details.",
    )
    parser.add_argument(
        "--faults-only",
        action="store_true",
        help="Only print fault event details.",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress terminal output (useful when combined with --html/--csv).",
    )

    args = parser.parse_args(argv)

    log_path = Path(args.logfile)
    if not log_path.exists():
        print(f"ocpp-lens: error: file not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"Parsing {log_path.name} …", end=" ", flush=True)

    try:
        messages = OCPPLogParser().parse_file(log_path)
    except Exception as exc:
        print(f"\nocpp-lens: error parsing file: {exc}", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"{len(messages)} messages found.")

    result = OCPPAnalyzer().analyze(messages)
    reporter = OCPPReporter()

    if not args.quiet:
        _print_summary(result)

    if args.html:
        reporter.to_html(result, args.html)
        if not args.quiet:
            print(f"✓ HTML report → {args.html}")

    if args.csv:
        reporter.to_csv(result, args.csv)
        if not args.quiet:
            print(f"✓ CSV report  → {args.csv}")

    if not args.html and not args.csv and not args.quiet:
        print("Tip: use --html report.html or --csv report.csv to export reports.")


if __name__ == "__main__":
    main()