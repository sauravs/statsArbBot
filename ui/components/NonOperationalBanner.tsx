// A slim, amber "not yet tested" banner for sections that are functional but
// haven't been validated end-to-end from the operator's side yet (Fast-Forward,
// Simulation, Live Bot). The sections still work — this is purely an honesty
// marker until they're tested in a later phase. Pairs with the dashed/dot marker
// on the dashboard header nav.
export default function NonOperationalBanner({ section }: { section: string }) {
  return (
    <div
      data-testid="non-operational-banner"
      className="mb-4 flex items-center gap-2 rounded-lg border border-dashed border-yellow/50 bg-yellow/5 px-3 py-2 text-xs text-yellow"
    >
      <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-yellow" />
      Non-operational — the {section} section works but hasn’t been tested yet
      (planned for a later phase).
    </div>
  );
}
