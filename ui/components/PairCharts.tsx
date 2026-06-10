"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  createSeriesMarkers,
  ColorType,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { getPairSeries, type PairSeries, type TimePoint } from "@/lib/api";

// UI theme tokens (PLAN §2) — canvas charts need the hexes directly.
const C = {
  bg: "#0a0b0d",
  card: "#12141a",
  border: "#21262d",
  muted: "#8b949e",
  text: "#e4e6ea",
  green: "#00d4a1",
  red: "#ff4757",
  yellow: "#ffd32a",
  blue: "#4a90e2",
};

const PANEL_HEIGHT = 240;

function toLine(points: TimePoint[]) {
  return points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
}

/** A USD price for the raw-price legend — more decimals for sub-$1 markets. */
function fmtPrice(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const dp = v >= 100 ? 2 : v >= 1 ? 3 : 5;
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })}`;
}

/** A plain numeric readout (spread / Z / rebased price) for a panel legend. */
function fmtNum(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

/** Read a line series' value at the crosshair (undefined on a whitespace bar). */
function valueAt(
  param: MouseEventParams,
  series: ISeriesApi<"Line">,
): number | null {
  const p = param.seriesData.get(series) as { value?: number } | undefined;
  return p?.value ?? null;
}

/**
 * Wire a panel's header legend to the crosshair (issues #68, #73): show the
 * hovered bar's value(s) while hovering, the latest value otherwise. Returns an
 * unsubscribe for cleanup — ``chart.remove()`` also tears the handler down, but
 * detaching explicitly keeps a re-render from ever leaving a stale subscription.
 */
function bindCrosshair<T>(
  chart: IChartApi,
  latest: T,
  atHover: (param: MouseEventParams) => T,
  set: (v: T) => void,
): () => void {
  set(latest);
  const handler = (param: MouseEventParams) => {
    set(!param.time || param.point === undefined ? latest : atHover(param));
  };
  chart.subscribeCrosshairMove(handler);
  return () => chart.unsubscribeCrosshairMove(handler);
}

type PriceLevel = { price: number; color: string; text: string };

/**
 * Render the band / threshold identities as labels pinned to the LEFT edge of a
 * panel, aligned to each level's line (issue #69). lightweight-charts only draws
 * a price-line's title as part of its right-axis label, which covers the price
 * tick values — so we keep ``axisLabelVisible: false`` (clean right ticks) and
 * place our own left-edge labels here. ``reposition`` re-aligns them whenever the
 * price scale changes (zoom / resize); returns a cleanup that removes the nodes.
 */
function attachEdgeLabels(
  container: HTMLDivElement,
  series: ISeriesApi<"Line">,
  levels: PriceLevel[],
  side: "left" | "right" = "left",
) {
  const edge = side === "right" ? "right:2px" : "left:2px";
  const els = levels.map((lvl) => {
    const el = document.createElement("div");
    el.textContent = lvl.text;
    el.style.cssText =
      `position:absolute;${edge};transform:translateY(-50%);font-size:10px;` +
      "font-weight:600;line-height:1;pointer-events:none;z-index:3;padding:1px 3px;" +
      "border-radius:3px;white-space:nowrap;";
    el.style.color = lvl.color;
    el.style.background = "rgba(18,20,26,0.72)"; // C.card, semi-opaque
    container.appendChild(el);
    return el;
  });
  const reposition = () => {
    levels.forEach((lvl, i) => {
      const y = series.priceToCoordinate(lvl.price);
      if (y == null) {
        els[i].style.display = "none";
      } else {
        els[i].style.display = "block";
        els[i].style.top = `${y}px`;
      }
    });
  };
  return { reposition, remove: () => els.forEach((e) => e.remove()) };
}

/**
 * Z-score line data spanning the *full* time axis (taken from the spread series,
 * which has every bar): the warm-up bars the backend omits become whitespace
 * points. This keeps the Z-score panel's bar indexing identical to the price /
 * spread panels, so fitContent and the logical-range sync align all three by
 * time rather than drifting by the rolling window length.
 */
function zLineData(data: PairSeries) {
  const zByTime = new Map(data.zscore.series.map((p) => [p.time, p.value]));
  return data.spread.series.map((p) => {
    const t = p.time as UTCTimestamp;
    const v = zByTime.get(p.time);
    return v === undefined ? { time: t } : { time: t, value: v };
  });
}

/**
 * Snap an entry timestamp (epoch seconds) to the latest bar at/under it, so a
 * "your entry" marker lands on a real bar. Entry is usually recorded at ~now,
 * so it typically snaps to the most recent bar (the right edge). Returns null
 * for an empty series.
 */
function snapToBar(series: TimePoint[], target: number): number | null {
  if (series.length === 0) return null;
  let chosen = series[0].time;
  for (const p of series) {
    if (p.time <= target) chosen = p.time;
    else break;
  }
  return chosen;
}

/**
 * Optional "your entry" overlay drawn when the pair-detail page is opened from a
 * recorded manual trade (Manual Trades panel). All fields are optional; each
 * overlay is drawn only when its value is a finite number.
 */
export type EntryOverlay = {
  z?: number; // Z-score at entry → horizontal line on the Z panel
  priceBase?: number; // base leg entry price → line on the raw panel (left axis)
  priceQuote?: number; // quote leg entry price → line on the raw panel (right axis)
  spread?: number; // spread value at entry → line on the spread panel
  time?: number; // entry epoch seconds → marker mirrored across all panels
};

function baseChartOptions() {
  return {
    layout: {
      background: { type: ColorType.Solid, color: C.card },
      textColor: C.muted,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: C.border },
      horzLines: { color: C.border },
    },
    rightPriceScale: { borderColor: C.border },
    timeScale: {
      borderColor: C.border,
      timeVisible: true,
      secondsVisible: false,
    },
    crosshair: { vertLine: { color: C.muted }, horzLine: { color: C.muted } },
    autoSize: true,
    height: PANEL_HEIGHT,
  };
}

/**
 * The 3-panel pair-detail chart (PRD F3): normalized price overlay, spread with
 * ±1σ/±2σ bands, and the rolling Z-score with entry/stop threshold lines and
 * entry/exit markers. All panels share one time axis (synced visible range).
 */
export default function PairCharts({
  base,
  quote,
  entry,
}: {
  base: string;
  quote: string;
  entry?: EntryOverlay;
}) {
  const [data, setData] = useState<PairSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Per-panel header readouts (issues #68, #73): updated to the hovered bar on
  // crosshair move, else the latest value. Raw + normalized carry both legs.
  const [rawAt, setRawAt] = useState<{ base: number | null; quote: number | null }>({
    base: null,
    quote: null,
  });
  const [normAt, setNormAt] = useState<{ base: number | null; quote: number | null }>({
    base: null,
    quote: null,
  });
  const [spreadAt, setSpreadAt] = useState<number | null>(null);
  const [zAt, setZAt] = useState<number | null>(null);

  const normRef = useRef<HTMLDivElement>(null);
  const rawRef = useRef<HTMLDivElement>(null);
  const spreadRef = useRef<HTMLDivElement>(null);
  const zRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getPairSeries(base, quote)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Failed to load pair series");
      });
    return () => {
      cancelled = true;
    };
  }, [base, quote]);

  useEffect(() => {
    if (
      !data ||
      !normRef.current ||
      !rawRef.current ||
      !spreadRef.current ||
      !zRef.current
    )
      return;

    // Crosshair-move subscriptions (issues #68, #73), detached on cleanup.
    const crosshairUnsubs: Array<() => void> = [];

    // ── Panel 1: normalized price overlay (both legs rebased to 100) ──────────
    const normChart = createChart(normRef.current, baseChartOptions());
    const baseLine = normChart.addSeries(LineSeries, {
      color: C.green,
      lineWidth: 2,
      title: data.base_market,
    });
    const quoteLine = normChart.addSeries(LineSeries, {
      color: C.blue,
      lineWidth: 2,
      title: data.quote_market,
    });
    baseLine.setData(toLine(data.normalized.base));
    quoteLine.setData(toLine(data.normalized.quote));
    const lastNorm = {
      base: data.normalized.base.at(-1)?.value ?? null,
      quote: data.normalized.quote.at(-1)?.value ?? null,
    };
    crosshairUnsubs.push(
      bindCrosshair(
        normChart,
        lastNorm,
        (param) => ({
          base: valueAt(param, baseLine),
          quote: valueAt(param, quoteLine),
        }),
        setNormAt,
      ),
    );

    // ── Panel 1b: raw prices on dual axes (issue #68) ─────────────────────────
    // The two legs' real prices live on very different scales (e.g. ETH ≈ $1750
    // vs AVAX ≈ $20), so the base uses the left axis and the quote the right.
    const rawChart = createChart(rawRef.current, {
      ...baseChartOptions(),
      leftPriceScale: { visible: true, borderColor: C.border },
    });
    const baseRaw = rawChart.addSeries(LineSeries, {
      color: C.green,
      lineWidth: 2,
      priceScaleId: "left",
      title: data.base_market,
    });
    const quoteRaw = rawChart.addSeries(LineSeries, {
      color: C.blue,
      lineWidth: 2,
      priceScaleId: "right",
      title: data.quote_market,
    });
    baseRaw.setData(toLine(data.raw.base));
    quoteRaw.setData(toLine(data.raw.quote));
    const lastRaw = {
      base: data.raw.base.at(-1)?.value ?? null,
      quote: data.raw.quote.at(-1)?.value ?? null,
    };
    // Hover → show both legs' real price at that timestamp; leave → latest close.
    crosshairUnsubs.push(
      bindCrosshair(
        rawChart,
        lastRaw,
        (param) => ({
          base: valueAt(param, baseRaw),
          quote: valueAt(param, quoteRaw),
        }),
        setRawAt,
      ),
    );

    // ── Panel 2: spread with mean and ±1σ / ±2σ bands ─────────────────────────
    const spreadChart = createChart(spreadRef.current, baseChartOptions());
    const spreadLine = spreadChart.addSeries(LineSeries, {
      color: C.yellow,
      lineWidth: 2,
      title: "spread",
    });
    spreadLine.setData(toLine(data.spread.series));
    crosshairUnsubs.push(
      bindCrosshair(
        spreadChart,
        data.spread.series.at(-1)?.value ?? null,
        (param) => valueAt(param, spreadLine),
        setSpreadAt,
      ),
    );
    const { mean, std } = data.spread;
    const spreadLevels: PriceLevel[] = [];
    const band = (
      offset: number,
      color: string,
      style: LineStyle,
      text: string,
    ) => {
      const price = mean + offset;
      spreadLine.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: style,
        // Right-axis value label off so it no longer covers the tick values; the
        // band identity is drawn as a left-edge label instead (issue #69).
        axisLabelVisible: false,
      });
      spreadLevels.push({ price, color, text });
    };
    band(0, C.muted, LineStyle.Solid, "mean");
    band(std, C.blue, LineStyle.Dashed, "+1σ");
    band(-std, C.blue, LineStyle.Dashed, "−1σ");
    band(2 * std, C.red, LineStyle.Dashed, "+2σ");
    band(-2 * std, C.red, LineStyle.Dashed, "−2σ");

    // ── Panel 3: rolling Z-score with threshold lines + entry/exit markers ────
    const zChart = createChart(zRef.current, baseChartOptions());
    const zLine = zChart.addSeries(LineSeries, {
      color: C.text,
      lineWidth: 2,
      title: "Z",
    });
    zLine.setData(zLineData(data));
    // Latest = last *real* Z (the padded series carries whitespace warm-up bars,
    // which read as "—" when hovered).
    crosshairUnsubs.push(
      bindCrosshair(
        zChart,
        data.zscore.series.at(-1)?.value ?? null,
        (param) => valueAt(param, zLine),
        setZAt,
      ),
    );
    const zLevels: PriceLevel[] = [];
    const zLineAt = (
      price: number,
      color: string,
      style: LineStyle,
      text: string,
    ) => {
      zLine.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: style,
        // Left-edge label instead of the right-axis label (issue #69).
        axisLabelVisible: false,
      });
      zLevels.push({ price, color, text });
    };
    zLineAt(0, C.muted, LineStyle.Solid, "0");
    zLineAt(data.entry_threshold, C.green, LineStyle.Dashed, "+entry");
    zLineAt(-data.entry_threshold, C.green, LineStyle.Dashed, "−entry");
    zLineAt(data.exit_threshold, C.muted, LineStyle.Dotted, "+exit");
    zLineAt(-data.exit_threshold, C.muted, LineStyle.Dotted, "−exit");
    zLineAt(data.stop_threshold, C.red, LineStyle.Dashed, "+stop");
    zLineAt(-data.stop_threshold, C.red, LineStyle.Dashed, "−stop");

    // ── "Your entry" overlay (opened from a recorded manual trade) ────────────
    // Yellow lines for the trade's entry Z, entry prices (one per leg/axis on the
    // raw panel), and entry spread; plus a time marker mirrored across all panels.
    // Each piece is drawn only when its value is present, so the scan-table route
    // (no entry context) renders the charts unchanged.
    const rawEntryLabels: {
      series: ISeriesApi<"Line">;
      level: PriceLevel;
      side: "left" | "right";
    }[] = [];
    let snappedEntry: UTCTimestamp | null = null;
    if (entry) {
      const entryLine = (series: ISeriesApi<"Line">, price: number) =>
        series.createPriceLine({
          price,
          color: C.yellow,
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: false,
        });
      if (entry.z != null && Number.isFinite(entry.z)) {
        entryLine(zLine, entry.z);
        zLevels.push({ price: entry.z, color: C.yellow, text: "entry" });
      }
      if (entry.spread != null && Number.isFinite(entry.spread)) {
        entryLine(spreadLine, entry.spread);
        spreadLevels.push({ price: entry.spread, color: C.yellow, text: "entry" });
      }
      if (entry.priceBase != null && Number.isFinite(entry.priceBase)) {
        entryLine(baseRaw, entry.priceBase);
        rawEntryLabels.push({
          series: baseRaw,
          level: { price: entry.priceBase, color: C.yellow, text: "entry" },
          side: "left",
        });
      }
      if (entry.priceQuote != null && Number.isFinite(entry.priceQuote)) {
        entryLine(quoteRaw, entry.priceQuote);
        rawEntryLabels.push({
          series: quoteRaw,
          level: { price: entry.priceQuote, color: C.yellow, text: "entry" },
          side: "right",
        });
      }
      if (entry.time != null && Number.isFinite(entry.time)) {
        const t = snapToBar(data.spread.series, entry.time);
        if (t != null) {
          snappedEntry = t as UTCTimestamp;
          // Mirror the entry-time marker on the non-Z panels; the Z panel folds it
          // into its own marker set below so it coexists with entry/exit arrows.
          const mark: SeriesMarker<Time> = {
            time: snappedEntry,
            position: "aboveBar",
            color: C.yellow,
            shape: "circle",
            text: "entry",
          };
          createSeriesMarkers(baseLine, [mark]);
          createSeriesMarkers(baseRaw, [mark]);
          createSeriesMarkers(spreadLine, [mark]);
        }
      }
    }

    // ── Z-panel markers: model entry/exit arrows + the "your entry" marker ────
    // When opened from a recorded trade (entry overlay present) we suppress the
    // model's simulated long/short/exit/stop markers so the user's own entry is
    // the only marker on the panel — they were easy to mistake for the trade's
    // own exit. Opened from the scan table (no entry), they render as before.
    const zMarkers: SeriesMarker<Time>[] = entry
      ? []
      : data.zscore.markers.map((m) =>
          m.kind === "entry"
            ? {
                time: m.time as UTCTimestamp,
                position: "belowBar" as const,
                color: C.blue,
                shape: "arrowUp" as const,
                text: m.side === "LONG_SPREAD" ? "long" : "short",
              }
            : {
                time: m.time as UTCTimestamp,
                position: "aboveBar" as const,
                color: m.reason === "TAKE_PROFIT" ? C.green : C.red,
                shape: "arrowDown" as const,
                text: m.reason === "TAKE_PROFIT" ? "exit" : "stop",
              },
        );
    if (snappedEntry != null) {
      zMarkers.push({
        time: snappedEntry,
        position: "aboveBar",
        color: C.yellow,
        shape: "circle",
        text: "entry",
      });
    }
    if (zMarkers.length > 0) createSeriesMarkers(zLine, zMarkers);

    // Edge band/threshold labels (issue #69), re-aligned on scale changes.
    const labelManagers: { reposition: () => void; remove: () => void }[] = [];
    spreadRef.current.style.position = "relative";
    zRef.current.style.position = "relative";
    labelManagers.push(attachEdgeLabels(spreadRef.current, spreadLine, spreadLevels));
    labelManagers.push(attachEdgeLabels(zRef.current, zLine, zLevels));
    if (rawEntryLabels.length > 0) {
      const rawEl = rawRef.current;
      rawEl.style.position = "relative";
      for (const { series, level, side } of rawEntryLabels) {
        labelManagers.push(attachEdgeLabels(rawEl, series, [level], side));
      }
    }
    const repositionLabels = () => labelManagers.forEach((m) => m.reposition());

    // ── Sync the visible time range across all panels ─────────────────────────
    const charts: IChartApi[] = [normChart, rawChart, spreadChart, zChart];
    let syncing = false;
    const subs = charts.map((src) => {
      const handler = (range: LogicalRange | null) => {
        if (syncing || range == null) return;
        syncing = true;
        for (const other of charts) {
          if (other !== src) other.timeScale().setVisibleLogicalRange(range);
        }
        syncing = false;
        // The price scale may have re-autoscaled to the new visible data.
        repositionLabels();
      };
      src.timeScale().subscribeVisibleLogicalRangeChange(handler);
      return { src, handler };
    });
    charts.forEach((c) => c.timeScale().fitContent());
    // Initial placement once the panes have painted (priceToCoordinate is ready).
    const raf = requestAnimationFrame(repositionLabels);
    const ro = new ResizeObserver(() => repositionLabels());
    ro.observe(spreadRef.current);
    ro.observe(zRef.current);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      crosshairUnsubs.forEach((unsub) => unsub());
      labelManagers.forEach((m) => m.remove());
      subs.forEach(({ src, handler }) =>
        src.timeScale().unsubscribeVisibleLogicalRangeChange(handler),
      );
      charts.forEach((c) => c.remove());
    };
  }, [data, entry]);

  if (error) {
    return (
      <p className="py-10 text-center text-sm text-red" data-testid="pair-charts-error">
        {error}
      </p>
    );
  }

  if (!data) {
    return (
      <p
        className="py-10 text-center text-sm text-muted"
        data-testid="pair-charts-loading"
      >
        Loading chart data…
      </p>
    );
  }

  return (
    <div data-testid="pair-charts" className="space-y-4">
      <Panel
        title="Normalized price (rebased to 100)"
        legend={
          <>
            <Legend
              color={C.green}
              label={`${data.base_market} ${fmtNum(normAt.base)}`}
            />
            <Legend
              color={C.blue}
              label={`${data.quote_market} ${fmtNum(normAt.quote)}`}
            />
          </>
        }
        innerRef={normRef}
        testid="chart-normalized"
      />
      <Panel
        title="Price (actual) — left axis / right axis"
        legend={
          <>
            <Legend
              color={C.green}
              label={`${data.base_market} ${fmtPrice(rawAt.base)}`}
            />
            <Legend
              color={C.blue}
              label={`${data.quote_market} ${fmtPrice(rawAt.quote)}`}
            />
            {entry && (entry.priceBase != null || entry.priceQuote != null) && (
              <Legend
                color={C.yellow}
                label={`entry ${entry.priceBase != null ? fmtPrice(entry.priceBase) : "—"} / ${entry.priceQuote != null ? fmtPrice(entry.priceQuote) : "—"}`}
              />
            )}
          </>
        }
        innerRef={rawRef}
        testid="chart-raw"
      />
      <Panel
        title="Spread (S1 − β·S2 − α) with ±1σ / ±2σ bands"
        legend={
          <span className="text-muted">
            spread <span className="text-text">{fmtNum(spreadAt)}</span> · mean{" "}
            {data.spread.mean.toFixed(2)} · σ {data.spread.std.toFixed(2)}
            {entry?.spread != null && (
              <>
                {" "}
                · <span className="text-yellow">entry {entry.spread.toFixed(2)}</span>
              </>
            )}
          </span>
        }
        innerRef={spreadRef}
        testid="chart-spread"
      />
      <Panel
        title="Z-score with entry / exit / stop thresholds"
        legend={
          <span className="text-muted">
            Z <span className="text-text">{fmtNum(zAt)}</span> · entry ±
            {data.entry_threshold} · exit ±{data.exit_threshold} · stop ±
            {data.stop_threshold}
            {entry?.z != null && (
              <>
                {" "}
                · <span className="text-yellow">your entry {entry.z.toFixed(2)}</span>
              </>
            )}
          </span>
        }
        innerRef={zRef}
        testid="chart-zscore"
      />
    </div>
  );
}

function Panel({
  title,
  legend,
  innerRef,
  testid,
}: {
  title: string;
  legend: React.ReactNode;
  innerRef: React.RefObject<HTMLDivElement>;
  testid: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="uppercase tracking-wider text-muted">{title}</span>
        <span className="flex items-center gap-3">{legend}</span>
      </div>
      <div ref={innerRef} data-testid={testid} style={{ height: PANEL_HEIGHT }} />
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-muted">
      <span
        className="inline-block h-0.5 w-3 rounded"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}
