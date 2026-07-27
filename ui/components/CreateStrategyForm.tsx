"use client";

import { useState } from "react";
import { createStrategy, type Strategy } from "@/lib/api";
import InfoTip from "./InfoTip";

// Create a backtest strategy (PRD F8.4). A strategy is a parameter set — the
// walk-forward window lengths plus the signal thresholds (entry/exit/stop |Z|),
// Z-window, and an Advanced section for the filter / cost / sizing knobs (issue
// #78; these used to be hidden and silently took server defaults). The date
// range is optional (blank ⇒ full demo history offline).
export default function CreateStrategyForm({
  onCreated,
}: {
  onCreated: (s: Strategy) => void;
}) {
  const [name, setName] = useState("");
  const [capital, setCapital] = useState("10000");
  const [entryZ, setEntryZ] = useState("1.5");
  const [exitZ, setExitZ] = useState("0.5");
  const [stopZ, setStopZ] = useState("4");
  const [scanDays, setScanDays] = useState("90");
  const [tradeDays, setTradeDays] = useState("30");
  const [zwindow, setZwindow] = useState("21");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  // Advanced filter / cost / sizing knobs (issue #78) — defaults mirror the
  // server's StrategyBody so leaving them untouched reproduces today's behaviour.
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [pvalueMax, setPvalueMax] = useState("0.05");
  const [maxHalfLife, setMaxHalfLife] = useState("72");
  const [usdPerTrade, setUsdPerTrade] = useState("100");
  const [maxActivePairs, setMaxActivePairs] = useState(""); // blank ⇒ unlimited
  const [slippagePct, setSlippagePct] = useState("0.05");
  const [takerFeePct, setTakerFeePct] = useState("0.05");
  const [fundingFreqH, setFundingFreqH] = useState("1");
  // Per-strategy backtest universe filter (Phase-3 WS1, path b). Blank ⇒ OFF.
  // A tractability/honesty knob, NOT alpha — filtering up loses money (QA.md).
  const [minDollarVol, setMinDollarVol] = useState(""); // $/hr floor; blank ⇒ off
  const [maxHalfSpread, setMaxHalfSpread] = useState(""); // % ceiling; blank ⇒ off
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const entry = Number(entryZ);
    const exit = Number(exitZ);
    const stop = Number(stopZ);
    // Same ordering rule as the live thresholds (#74): exit < entry < stop.
    if (!(exit < entry && entry < stop)) {
      setError("Thresholds must satisfy exit < entry < stop");
      return;
    }
    const maxPairs = maxActivePairs.trim();
    setBusy(true);
    setError(null);
    try {
      const s = await createStrategy({
        name: name.trim() || "Untitled strategy",
        starting_capital: Number(capital),
        entry_threshold: entry,
        exit_threshold: exit,
        stop_threshold: stop,
        scan_window_days: Number(scanDays),
        trade_window_days: Number(tradeDays),
        zscore_window: Number(zwindow),
        pvalue_max: Number(pvalueMax),
        max_half_life_h: Number(maxHalfLife),
        usd_per_trade: Number(usdPerTrade),
        max_active_pairs: maxPairs === "" ? undefined : Number(maxPairs),
        slippage_pct: Number(slippagePct),
        taker_fee_pct: Number(takerFeePct),
        funding_freq_h: Number(fundingFreqH),
        // Blank ⇒ omit ⇒ OFF (server default). Only send a real, non-negative number.
        ...(minDollarVol.trim() !== "" && Number(minDollarVol) >= 0
          ? { backtest_min_dollar_volume: Number(minDollarVol) }
          : {}),
        ...(maxHalfSpread.trim() !== "" && Number(maxHalfSpread) >= 0
          ? { backtest_max_half_spread_pct: Number(maxHalfSpread) }
          : {}),
        // Interpret the datetime-local wall-clock value as UTC (append "Z"), like
        // the fast-forward form, so the range matches the UTC-anchored history.
        start_time: start ? new Date(`${start}Z`).toISOString() : undefined,
        end_time: end ? new Date(`${end}Z`).toISOString() : undefined,
      });
      onCreated(s);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="create-strategy-form">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">New Strategy</h2>
      <div className="space-y-3">
        <Field label="Name" tip="A label for this strategy — shown in the ranked list. Cosmetic only; defaults to “Untitled strategy” if blank.">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My strategy"
            className="bt-input"
            data-testid="strategy-name"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Starting capital ($)" tip="Account equity the backtest starts with; the equity curve compounds from here. Typical $10k–$100k for a demo run.">
            <input
              type="number"
              min="1"
              step="100"
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
              className="bt-input"
              data-testid="strategy-capital"
            />
          </Field>
          <Field label="Z-score window (bars)" tip="Rolling lookback, in bars, used to standardise the spread into a z-score — the window the entry/exit signals read. Typical 20–60.">
            <input
              type="number"
              min="3"
              step="1"
              value={zwindow}
              onChange={(e) => setZwindow(e.target.value)}
              className="bt-input"
              data-testid="strategy-zwindow"
            />
          </Field>
        </div>

        {/* Signal thresholds — exit < entry < stop (issue #78). */}
        <div className="grid grid-cols-3 gap-3">
          <Field label="Entry |Z| ≥" tip="Open a pair when the spread's |z-score| reaches this. Typical 1.5–2.0; lower (1.0) trades more often, higher trades rarer but cleaner.">
            <input
              type="number"
              min="0.5"
              max="4"
              step="0.1"
              value={entryZ}
              onChange={(e) => setEntryZ(e.target.value)}
              className="bt-input"
              data-testid="strategy-entry-z"
            />
          </Field>
          <Field label="Exit |Z| <" tip="Take-profit: close once |z-score| reverts below this, i.e. the spread is back near its mean. Typical 0.0–0.5.">
            <input
              type="number"
              min="0.1"
              max="2"
              step="0.1"
              value={exitZ}
              onChange={(e) => setExitZ(e.target.value)}
              className="bt-input"
              data-testid="strategy-exit-z"
            />
          </Field>
          <Field label="Stop |Z| ≥" tip="Hard stop: close at a loss if |z-score| diverges to this, signalling a likely cointegration breakdown. Typical 3.0–4.0.">
            <input
              type="number"
              min="1"
              max="10"
              step="0.5"
              value={stopZ}
              onChange={(e) => setStopZ(e.target.value)}
              className="bt-input"
              data-testid="strategy-stop-z"
            />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Scan window (days)" tip="Formation/lookback span each walk-forward window uses to pick cointegrated pairs. Typical 60–120 days.">
            <input
              type="number"
              min="1"
              step="1"
              value={scanDays}
              onChange={(e) => setScanDays(e.target.value)}
              className="bt-input"
              data-testid="strategy-scan-days"
            />
          </Field>
          <Field label="Trade window (days)" tip="Out-of-sample span each window holds the selected pairs before stepping forward. Typical 30–180 days.">
            <input
              type="number"
              min="1"
              step="1"
              value={tradeDays}
              onChange={(e) => setTradeDays(e.target.value)}
              className="bt-input"
              data-testid="strategy-trade-days"
            />
          </Field>
        </div>

        {/* Advanced: filter / cost / sizing knobs that otherwise take server
            defaults. Collapsed by default so the common path stays simple. */}
        <div className="rounded-lg border border-border">
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="flex w-full items-center justify-between px-3 py-2 text-xs text-muted hover:text-text"
            data-testid="strategy-advanced-toggle"
            aria-expanded={showAdvanced}
          >
            <span className="uppercase tracking-wider">Advanced</span>
            <span>{showAdvanced ? "▾" : "▸"}</span>
          </button>
          {showAdvanced && (
            <div
              className="grid grid-cols-2 gap-3 border-t border-border p-3"
              data-testid="strategy-advanced-panel"
            >
              <Field label="p-value max" tip="Cointegration significance cutoff for keeping a pair. 0.05 standard; 0.01 strict (fewer pairs); 0.10 loose (more pairs).">
                <input
                  type="number"
                  min="0.001"
                  max="1"
                  step="0.01"
                  value={pvalueMax}
                  onChange={(e) => setPvalueMax(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-pvalue"
                />
              </Field>
              <Field label="Half-life cap (h)" tip="Maximum mean-reversion half-life to keep a pair. 72h default; raise (e.g. 168h) to admit slower-reverting pairs.">
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={maxHalfLife}
                  onChange={(e) => setMaxHalfLife(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-halflife"
                />
              </Field>
              <Field label="USD per trade" tip="Fixed notional sized into each leg of a pair trade. Typical $100–$1,000.">
                <input
                  type="number"
                  min="1"
                  step="10"
                  value={usdPerTrade}
                  onChange={(e) => setUsdPerTrade(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-usd-per-trade"
                />
              </Field>
              <Field label="Max active pairs (blank ⇒ ∞)" tip="Cap on concurrently open pairs. Blank ⇒ unlimited; typical 5–20 to spread risk across pairs.">
                <input
                  type="number"
                  min="1"
                  max="100"
                  step="1"
                  value={maxActivePairs}
                  onChange={(e) => setMaxActivePairs(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-max-pairs"
                />
              </Field>
              <Field label="Slippage %" tip="Per-leg slippage cost assumption applied on entry and exit. ~0.05% is typical on dYdX.">
                <input
                  type="number"
                  min="0"
                  max="5"
                  step="0.01"
                  value={slippagePct}
                  onChange={(e) => setSlippagePct(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-slippage"
                />
              </Field>
              <Field label="Taker fee %" tip="Per-leg taker fee assumption applied on entry and exit. ~0.05% is typical on dYdX.">
                <input
                  type="number"
                  min="0"
                  max="5"
                  step="0.01"
                  value={takerFeePct}
                  onChange={(e) => setTakerFeePct(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-taker-fee"
                />
              </Field>
              <Field label="Funding freq (h)" tip="How often funding is charged on open positions. dYdX funding is hourly ⇒ 1.">
                <input
                  type="number"
                  min="1"
                  max="24"
                  step="1"
                  value={fundingFreqH}
                  onChange={(e) => setFundingFreqH(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-funding-freq"
                />
              </Field>

              {/* Per-strategy backtest universe filter (Phase-3 WS1, path b).
                  Persisted with the run. Framed as a tractability/honesty knob —
                  NOT a profit lever (the §4 refutation shows filtering up loses
                  money). Blank ⇒ OFF. */}
              <Field
                label="Univ. min $-vol/hr (blank ⇒ off)"
                tip="Backtest universe floor: drop markets whose mean hourly dollar-volume is below this before the scan. Honesty/robustness knob, NOT alpha — filtering up to liquid names LOSES money (the gross lives in the thinnest markets; see docs/QA.md). Blank ⇒ off."
              >
                <input
                  type="number"
                  min="0"
                  step="10000"
                  placeholder="off"
                  value={minDollarVol}
                  onChange={(e) => setMinDollarVol(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-univ-min-dollar-vol"
                />
              </Field>
              <Field
                label="Univ. max half-spread % (blank ⇒ off)"
                tip="Backtest universe ceiling: drop markets whose modelled half-spread exceeds this % before the scan. Honesty/robustness knob, NOT alpha (see docs/QA.md). Blank ⇒ off."
              >
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  placeholder="off"
                  value={maxHalfSpread}
                  onChange={(e) => setMaxHalfSpread(e.target.value)}
                  className="bt-input"
                  data-testid="strategy-univ-max-half-spread"
                />
              </Field>

              <p
                className="col-span-2 text-[11px] leading-snug text-muted"
                data-testid="strategy-univ-filter-note"
              >
                <span className="font-medium text-text">Universe filter</span> is a
                tractability/honesty knob, not a profit lever: pruning to liquid names
                makes the backtest more executable but does <em>not</em> add edge —
                filtering up actually loses money (the gross lives in the thinnest
                markets). Default off; persisted with the run. See{" "}
                <span className="font-mono">docs/QA.md</span>.
              </p>
            </div>
          )}
        </div>

        <Field label="Start (optional — full history if blank)" tip="UTC start of the backtest history. Blank ⇒ full cached history. Keep it within the cached coverage shown on the Backtest page.">
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="bt-input"
            data-testid="strategy-start"
          />
        </Field>
        <Field label="End (optional)" tip="UTC end of the backtest history. Blank ⇒ runs to the latest cached bar.">
          <input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="bt-input"
            data-testid="strategy-end"
          />
        </Field>
      </div>

      {error && (
        <p className="mt-3 text-sm text-red" data-testid="create-strategy-error">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={busy}
        className="mt-4 w-full rounded-lg bg-blue/20 px-3 py-2 text-sm font-medium text-blue transition-colors hover:bg-blue/30 disabled:opacity-50"
        data-testid="create-strategy-btn"
      >
        {busy ? "Creating…" : "Create strategy"}
      </button>

      <style jsx>{`
        :global(.bt-input) {
          width: 100%;
          border-radius: 0.5rem;
          border: 1px solid #21262d;
          background: #0a0b0d;
          padding: 0.5rem 0.75rem;
          font-size: 0.875rem;
          color: #e4e6ea;
        }
        :global(.bt-input:focus) {
          outline: none;
          border-color: rgba(74, 144, 226, 0.6);
        }
      `}</style>
    </div>
  );
}

function Field({
  label,
  tip,
  children,
}: {
  label: string;
  tip?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-muted">
        {label}
        {tip && <InfoTip text={tip} />}
      </span>
      {children}
    </label>
  );
}
