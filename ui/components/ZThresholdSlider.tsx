"use client";

// Single-handle Z-threshold control (PRD F4.1): value 0.5–4.0, rendered on a
// −5…+5 axis with a shaded neutral band between ∓threshold. A pair counts as an
// "active signal" when |Z| ≥ threshold (F4.2), so the band is the inactive zone.

const MIN = 0.5;
const MAX = 4.0;
const AXIS = 5; // axis spans −5…+5

function axisPct(v: number): number {
  return ((v + AXIS) / (2 * AXIS)) * 100;
}

export default function ZThresholdSlider({
  value,
  onChange,
}: {
  value: number;
  onChange: (n: number) => void;
}) {
  const t = Math.min(MAX, Math.max(MIN, value));
  const bandLeft = axisPct(-t);
  const bandWidth = axisPct(t) - axisPct(-t);

  return (
    <div className="w-full max-w-sm" data-testid="z-threshold-slider">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-muted">Active when |Z| ≥ threshold</span>
        <span className="tabular-nums text-text" data-testid="z-threshold-value">
          ±{t.toFixed(1)}
        </span>
      </div>

      {/* −5…+5 axis with the shaded neutral (inactive) band between ∓threshold */}
      <div className="relative h-6 overflow-hidden rounded border border-border bg-bg">
        <div
          className="absolute inset-y-0 bg-muted/25"
          style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }}
          data-testid="z-neutral-band"
        />
        <div className="absolute inset-y-0 w-px bg-border" style={{ left: "50%" }} />
        <div
          className="absolute inset-y-0 w-0.5 bg-blue"
          style={{ left: `${axisPct(-t)}%` }}
        />
        <div
          className="absolute inset-y-0 w-0.5 bg-blue"
          style={{ left: `${axisPct(t)}%` }}
        />
      </div>
      <div className="mt-0.5 flex justify-between text-[10px] tabular-nums text-muted">
        <span>−5</span>
        <span>0</span>
        <span>+5</span>
      </div>

      {/* single-handle control */}
      <input
        type="range"
        min={MIN}
        max={MAX}
        step={0.1}
        value={t}
        aria-label="Z-threshold"
        onChange={(e) => onChange(parseFloat(e.target.value) || MIN)}
        className="mt-2 w-full accent-blue"
        data-testid="z-threshold-input"
      />
    </div>
  );
}
