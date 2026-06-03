"""
Walk-forward backtest (Phase 8, PRD F8).

A strategy is a parameter set; backtesting it sweeps sliding scan/trade windows
over the historical OHLCV cache. In each window the SAME statcore cointegration
scan selects pairs over the formation (scan) window, then the SAME stateless tick
core (``simulation.run_tick``) trades them over the following test (trade) window —
one source of statistical + signal truth across live / sim / fast-forward /
backtest (PLAN §1). See ``windows`` (window math), ``scan_window`` (per-window
scan), ``engine`` (orchestration + pause/stop/resume + ranking), ``report``.
"""
