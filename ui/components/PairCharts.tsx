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
  orange: "#ff9f43", // legacy manual-view EXIT overlay (kept for the horizontal path)
  blue: "#4a90e2",
  // Backtest per-trade entry/exit VERTICAL time-lines (issue #172): a cyan/violet
  // pair chosen to read clearly against each other and against every panel color
  // (green/blue legs, red σ-bands, yellow spread, grey mean) — the old yellow/orange
  // entry/exit were too close in hue to tell apart.
  entryLine: "#22d3ee", // cyan — trade ENTRY
  exitLine: "#c084fc", // violet — trade EXIT
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

/** "2026-07-03 14:00 UTC" — the compact UTC stamp used in the vertical-line tips. */
function fmtChartTime(t: number): string {
  return new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

/**
 * Draw a trade's entry/exit as a full-height VERTICAL time-line over a panel
 * (issue #172). A trade is a *moment in time*, so a vertical line at the entry /
 * exit timestamp reads far better than a horizontal price-line (which marks a
 * level across all time and was easy to confuse with the σ / threshold bands, and
 * whose old yellow/orange were nearly the same hue). Like the edge labels, the
 * line is an absolutely-positioned HTML overlay repositioned via
 * ``timeToCoordinate`` on zoom / resize; it hides itself when the timestamp falls
 * outside the visible range (or the panel — spread/z on a legacy trade — has no
 * data). Hovering the line reveals the exact time + the panel's value at that
 * point. Returns { reposition, remove } for the effect to drive / clean up.
 */
function attachVerticalLine(
  container: HTMLDivElement,
  chart: IChartApi,
  time: UTCTimestamp,
  opts: {
    color: string;
    label: string;
    value: string | null;
    testid: string;
    chipTop: string;
  },
): { reposition: () => void; remove: () => void } {
  const wrap = document.createElement("div");
  wrap.setAttribute("data-testid", opts.testid);
  // A 10px-wide hit target centered on the 2px line — easy to hover, while only
  // this thin strip captures pointer events (the rest of the pane still pans).
  wrap.style.cssText =
    "position:absolute;top:0;height:100%;width:10px;transform:translateX(-50%);" +
    "pointer-events:auto;cursor:default;z-index:4;display:none;";

  const line = document.createElement("div");
  line.style.cssText =
    "position:absolute;left:50%;top:0;height:100%;width:2px;" +
    "transform:translateX(-50%);pointer-events:none;";
  line.style.background = opts.color;
  wrap.appendChild(line);

  const chip = document.createElement("div");
  chip.textContent = opts.label;
  // Entry/exit chips sit at different heights (chipTop) so they never collide when
  // a short trade puts the two lines close together.
  chip.style.cssText =
    `position:absolute;top:${opts.chipTop};left:50%;transform:translateX(-50%);font-size:9px;` +
    "font-weight:700;line-height:1;padding:1px 4px;border-radius:3px;white-space:nowrap;" +
    "pointer-events:none;letter-spacing:0.04em;color:#0a0b0d;";
  chip.style.background = opts.color;
  wrap.appendChild(chip);

  const tip = document.createElement("div");
  tip.setAttribute("data-testid", "bt-chart-vline-tip");
  tip.style.cssText =
    `position:absolute;top:${parseInt(opts.chipTop, 10) + 15}px;display:none;font-size:10px;line-height:1.35;` +
    "padding:4px 7px;border-radius:5px;white-space:nowrap;pointer-events:none;z-index:5;" +
    "background:rgba(10,11,13,0.94);border:1px solid #21262d;box-shadow:0 2px 8px rgba(0,0,0,0.4);";
  const tipLabel = document.createElement("div");
  tipLabel.textContent = opts.label;
  tipLabel.style.cssText = `font-weight:700;letter-spacing:0.04em;color:${opts.color};`;
  const tipTime = document.createElement("div");
  tipTime.textContent = fmtChartTime(time);
  tipTime.style.color = "#8b949e";
  tip.appendChild(tipLabel);
  tip.appendChild(tipTime);
  if (opts.value) {
    const tipVal = document.createElement("div");
    tipVal.textContent = opts.value;
    tipVal.style.color = "#e4e6ea";
    tip.appendChild(tipVal);
  }
  wrap.appendChild(tip);

  // Flip the tooltip to the left when the line sits in the panel's right portion,
  // so it never overflows the right edge.
  const placeTip = () => {
    const x = chart.timeScale().timeToCoordinate(time);
    if (x != null && x > container.clientWidth - 150) {
      tip.style.left = "auto";
      tip.style.right = "6px";
    } else {
      tip.style.left = "6px";
      tip.style.right = "auto";
    }
  };
  wrap.addEventListener("mouseenter", () => {
    placeTip();
    tip.style.display = "block";
  });
  wrap.addEventListener("mouseleave", () => {
    tip.style.display = "none";
  });

  const reposition = () => {
    const x = chart.timeScale().timeToCoordinate(time);
    if (x == null) {
      wrap.style.display = "none";
    } else {
      wrap.style.display = "block";
      wrap.style.left = `${x}px`;
    }
  };
  container.appendChild(wrap);
  return { reposition, remove: () => wrap.remove() };
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
  exit,
  series,
}: {
  base: string;
  quote: string;
  entry?: EntryOverlay;
  // A backtest trade's exit overlay (issue #166) — drawn in orange, mirroring the
  // yellow entry overlay across all panels.
  exit?: EntryOverlay;
  // Pre-fetched series (issue #166): when provided, PairCharts renders this instead
  // of fetching the live recent-window series for (base, quote). Lets the backtest
  // per-trade chart drive the same panels over a historical window.
  series?: PairSeries;
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
    // Pre-fetched series (backtest per-trade chart) → render it directly, no fetch.
    if (series) {
      setData(series);
      setError(null);
      return;
    }
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
  }, [base, quote, series]);

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

    // ── Trade overlays: "entry" (yellow) and, for a backtest trade, "exit" ─────
    // (orange). Each draws price-lines for its Z / per-leg prices / spread and a
    // time marker mirrored across all panels. Each piece is drawn only when its
    // value is present, so the scan-table route (no overlays) is unchanged.
    const rawEntryLabels: {
      series: ISeriesApi<"Line">;
      level: PriceLevel;
      side: "left" | "right";
    }[] = [];
    const baseMarks: SeriesMarker<Time>[] = [];
    const rawMarks: SeriesMarker<Time>[] = [];
    const spreadMarks: SeriesMarker<Time>[] = [];
    const zOverlayMarks: SeriesMarker<Time>[] = [];
    // Vertical entry/exit time-lines (issue #172), repositioned alongside the edge
    // labels. Populated only in "trade mode" — a backtest per-trade chart, which
    // always passes an `exit` overlay. The live/manual pair view passes only
    // `entry` (no exit) → it keeps the original horizontal price-line overlay.
    const vlineManagers: { reposition: () => void; remove: () => void }[] = [];
    const tradeMode = Boolean(exit);

    const drawOverlay = (
      ov: EntryOverlay | undefined,
      color: string,
      label: string,
    ) => {
      if (!ov) return;
      const line = (series: ISeriesApi<"Line">, price: number) =>
        series.createPriceLine({
          price,
          color,
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: false,
        });
      if (ov.z != null && Number.isFinite(ov.z)) {
        line(zLine, ov.z);
        zLevels.push({ price: ov.z, color, text: label });
      }
      if (ov.spread != null && Number.isFinite(ov.spread)) {
        line(spreadLine, ov.spread);
        spreadLevels.push({ price: ov.spread, color, text: label });
      }
      if (ov.priceBase != null && Number.isFinite(ov.priceBase)) {
        line(baseRaw, ov.priceBase);
        rawEntryLabels.push({
          series: baseRaw,
          level: { price: ov.priceBase, color, text: label },
          side: "left",
        });
      }
      if (ov.priceQuote != null && Number.isFinite(ov.priceQuote)) {
        line(quoteRaw, ov.priceQuote);
        rawEntryLabels.push({
          series: quoteRaw,
          level: { price: ov.priceQuote, color, text: label },
          side: "right",
        });
      }
      if (ov.time != null && Number.isFinite(ov.time)) {
        const t = snapToBar(data.spread.series, ov.time);
        if (t != null) {
          const mark: SeriesMarker<Time> = {
            time: t as UTCTimestamp,
            position: "aboveBar",
            color,
            shape: "circle",
            text: label,
          };
          baseMarks.push(mark);
          rawMarks.push(mark);
          spreadMarks.push(mark);
          zOverlayMarks.push(mark);
        }
      }
    };
    // ── Trade mode (backtest per-trade chart): vertical entry/exit time-lines ──
    // Same data, a clearer encoding — a distinct-colored vertical line at each of
    // the trade's timestamps, mirrored across all panels, hover-revealing the exact
    // time + that panel's value. No horizontal price-lines / circle markers here.
    const priceStr = (ov: EntryOverlay): string | null => {
      if (ov.priceBase == null && ov.priceQuote == null) return null;
      const b = ov.priceBase != null ? fmtPrice(ov.priceBase) : "—";
      const q = ov.priceQuote != null ? fmtPrice(ov.priceQuote) : "—";
      return `${data.base_market} ${b} · ${data.quote_market} ${q}`;
    };
    const drawVerticalOverlay = (
      ov: EntryOverlay | undefined,
      color: string,
      label: string,
      side: "entry" | "exit",
    ) => {
      if (!ov || ov.time == null || !Number.isFinite(ov.time)) return;
      const t = ov.time as UTCTimestamp;
      const testid = `bt-chart-vline-${side}`;
      const chipTop = side === "entry" ? "3px" : "16px"; // stagger so chips never collide
      const px = priceStr(ov);
      const add = (
        container: HTMLDivElement | null,
        chart: IChartApi,
        value: string | null,
      ) => {
        if (!container) return;
        container.style.position = "relative";
        vlineManagers.push(
          attachVerticalLine(container, chart, t, {
            color,
            label,
            value,
            testid,
            chipTop,
          }),
        );
      };
      add(normRef.current, normChart, px);
      add(rawRef.current, rawChart, px);
      // Spread/z panels are empty for legacy (non-faithful) trades → their time
      // scale has no range and the line auto-hides; give a tooltip value only when
      // the overlay actually carries one.
      add(
        spreadRef.current,
        spreadChart,
        ov.spread != null && Number.isFinite(ov.spread)
          ? `spread ${ov.spread.toFixed(2)}`
          : null,
      );
      add(
        zRef.current,
        zChart,
        ov.z != null && Number.isFinite(ov.z) ? `Z ${ov.z.toFixed(2)}` : null,
      );
    };

    if (tradeMode) {
      drawVerticalOverlay(entry, C.entryLine, "ENTRY", "entry");
      drawVerticalOverlay(exit, C.exitLine, "EXIT", "exit");
    } else {
      // Live/manual pair view — unchanged horizontal "your entry" overlay.
      drawOverlay(entry, C.yellow, "entry");
      drawOverlay(exit, C.orange, "exit");
    }
    // Mirror the overlay time markers on the non-Z panels; the Z panel folds them
    // into its own marker set below so they coexist with model arrows.
    if (baseMarks.length > 0) createSeriesMarkers(baseLine, baseMarks);
    if (rawMarks.length > 0) createSeriesMarkers(baseRaw, rawMarks);
    if (spreadMarks.length > 0) createSeriesMarkers(spreadLine, spreadMarks);

    // ── Z-panel markers: model entry/exit arrows + the trade overlay markers ──
    // When opened from a recorded trade (an entry/exit overlay present) we suppress
    // the model's simulated long/short/exit/stop markers so the trade's own entry
    // and exit are the only markers on the panel. Opened from the scan table (no
    // overlay), they render as before.
    const hasOverlay = Boolean(entry || exit);
    const zMarkers: SeriesMarker<Time>[] = hasOverlay
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
    zMarkers.push(...zOverlayMarks);
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
    const repositionLabels = () => {
      labelManagers.forEach((m) => m.reposition());
      vlineManagers.forEach((m) => m.reposition());
    };

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
    // Also watch the price panels so the vertical trade-lines track width changes.
    ro.observe(normRef.current);
    ro.observe(rawRef.current);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      crosshairUnsubs.forEach((unsub) => unsub());
      labelManagers.forEach((m) => m.remove());
      vlineManagers.forEach((m) => m.remove());
      subs.forEach(({ src, handler }) =>
        src.timeScale().unsubscribeVisibleLogicalRangeChange(handler),
      );
      charts.forEach((c) => c.remove());
    };
  }, [data, entry, exit]);

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

  // Legend readouts match the overlay colors: cyan/violet for a backtest trade
  // (vertical lines), the original yellow/orange for the live/manual entry overlay.
  const entryColor = exit ? C.entryLine : C.yellow;
  const exitColor = C.exitLine;

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
                color={entryColor}
                label={`entry ${entry.priceBase != null ? fmtPrice(entry.priceBase) : "—"} / ${entry.priceQuote != null ? fmtPrice(entry.priceQuote) : "—"}`}
              />
            )}
            {exit && (exit.priceBase != null || exit.priceQuote != null) && (
              <Legend
                color={exitColor}
                label={`exit ${exit.priceBase != null ? fmtPrice(exit.priceBase) : "—"} / ${exit.priceQuote != null ? fmtPrice(exit.priceQuote) : "—"}`}
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
                · <span style={{ color: entryColor }}>entry {entry.spread.toFixed(2)}</span>
              </>
            )}
            {exit?.spread != null && (
              <>
                {" "}
                · <span style={{ color: exitColor }}>exit {exit.spread.toFixed(2)}</span>
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
                · <span style={{ color: entryColor }}>entry {entry.z.toFixed(2)}</span>
              </>
            )}
            {exit?.z != null && (
              <>
                {" "}
                · <span style={{ color: exitColor }}>exit {exit.z.toFixed(2)}</span>
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
