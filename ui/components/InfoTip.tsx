// A tiny "ⓘ" affordance that explains a label on hover/focus (issue #49).
//
// Uses the native `title` tooltip on purpose: the pairs table lives inside an
// `overflow-x-auto` container, so a CSS/portal tooltip would be clipped — the
// OS-rendered title never is, and it's accessible without extra wiring.
export default function InfoTip({ text }: { text: string }) {
  return (
    <span
      title={text}
      tabIndex={0}
      role="img"
      aria-label={text}
      data-testid="info-tip"
      className="ml-1 cursor-help select-none align-middle text-[10px] text-muted/70 hover:text-text"
    >
      ⓘ
    </span>
  );
}
