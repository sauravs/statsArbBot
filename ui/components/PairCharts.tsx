"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  createSeriesMarkers,
  ColorType,
  LineSeries,
  LineStyle,
  type IChartApi,
  type LogicalRange,
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
}: {
  base: string;
  quote: string;
}) {
  const [data, setData] = useState<PairSeries | null>(null);
  const [error, setError] = useState<string | null>(null);

  const normRef = useRef<HTMLDivElement>(null);
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
      !spreadRef.current ||
      !zRef.current
    )
      return;

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

    // ── Panel 2: spread with mean and ±1σ / ±2σ bands ─────────────────────────
    const spreadChart = createChart(spreadRef.current, baseChartOptions());
    const spreadLine = spreadChart.addSeries(LineSeries, {
      color: C.yellow,
      lineWidth: 2,
      title: "spread",
    });
    spreadLine.setData(toLine(data.spread.series));
    const { mean, std } = data.spread;
    const band = (
      offset: number,
      color: string,
      style: LineStyle,
      title: string,
    ) =>
      spreadLine.createPriceLine({
        price: mean + offset,
        color,
        lineWidth: 1,
        lineStyle: style,
        axisLabelVisible: true,
        title,
      });
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
    const zLineAt = (
      price: number,
      color: string,
      style: LineStyle,
      title: string,
    ) =>
      zLine.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: style,
        axisLabelVisible: true,
        title,
      });
    zLineAt(0, C.muted, LineStyle.Solid, "0");
    zLineAt(data.entry_threshold, C.green, LineStyle.Dashed, "+entry");
    zLineAt(-data.entry_threshold, C.green, LineStyle.Dashed, "−entry");
    zLineAt(data.exit_threshold, C.muted, LineStyle.Dotted, "+exit");
    zLineAt(-data.exit_threshold, C.muted, LineStyle.Dotted, "−exit");
    zLineAt(data.stop_threshold, C.red, LineStyle.Dashed, "+stop");
    zLineAt(-data.stop_threshold, C.red, LineStyle.Dashed, "−stop");

    if (data.zscore.markers.length > 0) {
      const markers: SeriesMarker<Time>[] = data.zscore.markers.map((m) =>
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
      createSeriesMarkers(zLine, markers);
    }

    // ── Sync the visible time range across all three panels ───────────────────
    const charts: IChartApi[] = [normChart, spreadChart, zChart];
    let syncing = false;
    const subs = charts.map((src) => {
      const handler = (range: LogicalRange | null) => {
        if (syncing || range == null) return;
        syncing = true;
        for (const other of charts) {
          if (other !== src) other.timeScale().setVisibleLogicalRange(range);
        }
        syncing = false;
      };
      src.timeScale().subscribeVisibleLogicalRangeChange(handler);
      return { src, handler };
    });
    charts.forEach((c) => c.timeScale().fitContent());

    return () => {
      subs.forEach(({ src, handler }) =>
        src.timeScale().unsubscribeVisibleLogicalRangeChange(handler),
      );
      charts.forEach((c) => c.remove());
    };
  }, [data]);

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
            <Legend color={C.green} label={data.base_market} />
            <Legend color={C.blue} label={data.quote_market} />
          </>
        }
        innerRef={normRef}
        testid="chart-normalized"
      />
      <Panel
        title="Spread (S1 − β·S2 − α) with ±1σ / ±2σ bands"
        legend={
          <span className="text-muted">
            mean {data.spread.mean.toFixed(2)} · σ {data.spread.std.toFixed(2)}
          </span>
        }
        innerRef={spreadRef}
        testid="chart-spread"
      />
      <Panel
        title="Z-score with entry / exit / stop thresholds"
        legend={
          <span className="text-muted">
            entry ±{data.entry_threshold} · exit ±{data.exit_threshold} · stop ±
            {data.stop_threshold}
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
