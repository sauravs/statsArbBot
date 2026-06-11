# Feature Q&A Log

Running log of `/feature-qa` questions and answers.

> **Version-controlled.** This file is tracked in git and promoted to `production` with the
> rest of the repo. Newest entries appended at the bottom.

---

## 2026-06-11 — Normalized price (rebased to 100): what & why

**Q:** related to charting category, what is Normalized price (rebased to 100), what is its importance, why we are using it?

**A:** Each leg's raw price series is rescaled so its **first bar in the chart window equals 100**, then every later point is relative to that: `value = price / price[0] * 100`, applied independently to each leg (`backend/marketdata/pair_series.py:381-386`). A reading of 112 = up 12% since the window start; 95 = down 5%. It feeds **Panel 1** of the pair-detail chart (base green / quote blue) in `ui/components/PairCharts.tsx:259`.

**Importance / why we use it:** the two legs trade at very different absolute prices (e.g. BTC ~$60k vs SOL ~$150). Plotting raw prices on one axis makes the cheap leg a flat line and the expensive one dominate — you can't visually compare their movement. Rebasing both to 100 puts them on the same percentage scale, so you can:
1. See them co-move and then diverge on a like-for-like basis (`docs/USER_GUIDE.md:104`).
2. Get the visual intuition behind the pairs trade — divergence now, expected re-convergence (the human-readable version of the Spread/Z-score math).
3. Sanity-check a signal before acting: is the spread genuinely mean-reverting, or is cointegration breaking down? (`docs/USER_GUIDE.md:108`).

**Key caveat:** the normalized overlay is **purely visual/diagnostic** — it does NOT generate signals. Trade logic runs off the **Spread** (`S1 − β·S2 − α`) and **Z-score** (Panel 3, "the chart you trade off", `docs/USER_GUIDE.md:106`). The rebased-to-100 panel just makes the relationship legible to a human.

---
