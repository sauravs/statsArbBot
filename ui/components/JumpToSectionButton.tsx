"use client";
import { useCallback, useEffect, useState } from "react";

/**
 * Bidirectional floating jump button (issue: Manual Trading UX).
 *
 * As the Cointegrated Pairs table grows with the number of scanned markets, the
 * "Manual Trades" section gets pushed far down the page and the operator has to
 * drag the scrollbar the whole way. This FAB, pinned to the bottom-right, offers
 * a one-click hop:
 *   - while the target section is still below the fold → "↓ Manual Trades"
 *     (smooth-scrolls down to it),
 *   - once the section has been reached → "↑ Top" (smooth-scrolls back up).
 *
 * It hides itself when the page is short enough not to need scrolling.
 */
export default function JumpToSectionButton({
  targetId,
  downLabel = "Manual Trades",
  upLabel = "Top",
}: {
  targetId: string;
  downLabel?: string;
  upLabel?: string;
}) {
  const [direction, setDirection] = useState<"down" | "up">("down");
  const [visible, setVisible] = useState(false);

  const recompute = useCallback(() => {
    const el = document.getElementById(targetId);
    const doc = document.documentElement;
    // Only worth showing when the page actually scrolls; otherwise the target is
    // already on screen and the button would be noise.
    const scrollable = doc.scrollHeight > window.innerHeight + 40;
    setVisible(scrollable && !!el);
    if (!el) return;
    // "Reached" once the section's top has scrolled into the upper half of the
    // viewport, OR once we're at the very bottom of the page (on a short page the
    // section can't reach the top, but hitting the bottom still means we've
    // arrived — and there the useful action is to go back up).
    const atTopOfViewport =
      el.getBoundingClientRect().top < window.innerHeight * 0.5;
    const atPageBottom =
      window.scrollY + window.innerHeight >= doc.scrollHeight - 8;
    setDirection(atTopOfViewport || atPageBottom ? "up" : "down");
  }, [targetId]);

  useEffect(() => {
    recompute();
    // rAF-throttle so we compute at most once per frame.
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        recompute();
      });
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    // The page grows AFTER mount as data loads (e.g. the scan fills the pairs
    // table with hundreds of rows) — that changes document height without ever
    // firing scroll/resize, so without this the button would stay hidden on a
    // page that only became scrollable once its content arrived. A
    // ResizeObserver on <body> re-checks whenever the content height changes.
    const ro =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(schedule)
        : null;
    ro?.observe(document.body);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      ro?.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [recompute]);

  const onClick = useCallback(() => {
    if (direction === "down") {
      document
        .getElementById(targetId)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [direction, targetId]);

  if (!visible) return null;

  const isDown = direction === "down";
  const label = isDown ? downLabel : upLabel;

  return (
    <button
      type="button"
      onClick={onClick}
      data-testid="jump-nav-btn"
      data-direction={direction}
      aria-label={isDown ? `Jump to ${downLabel}` : `Back to ${upLabel}`}
      title={isDown ? `Jump to ${downLabel}` : `Back to ${upLabel}`}
      className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-full border border-border bg-card/95 px-4 py-2.5 text-sm font-medium text-text shadow-lg backdrop-blur transition-colors hover:border-blue/60 hover:text-blue"
    >
      <span aria-hidden className="text-base leading-none">
        {isDown ? "↓" : "↑"}
      </span>
      <span className="whitespace-nowrap">{label}</span>
    </button>
  );
}
