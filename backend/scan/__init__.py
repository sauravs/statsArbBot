"""Cointegration scan: orchestration, progress state, and dual-write.

The scan consumes :mod:`statcore` (the single source of statistical truth) over
every market pair, then dual-writes survivors to CSV and the ``CointScanResult``
DB table (PRD §3.1). Progress is tracked through a single, lock-guarded
:class:`ScanState` so concurrent start requests cannot launch overlapping scans
(fixing the prototype's race on a shared, unguarded dict).
"""

from .orchestrator import run_scan
from .state import SCAN_STATE, ScanState

__all__ = ["run_scan", "SCAN_STATE", "ScanState"]
