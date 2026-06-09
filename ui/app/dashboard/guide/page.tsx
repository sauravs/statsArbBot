import { readFileSync } from "node:fs";
import path from "node:path";
import Link from "next/link";
import type { ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Static page: the markdown is read once at build time and baked into HTML, so no
// filesystem access happens at runtime (important for the standalone Docker image,
// whose build context is ./ui — see scripts/sync-guide.mjs for how the copy under
// content/ is kept in sync with the canonical docs/TRADING_CONCEPTS.md).
export const dynamic = "force-static";

function loadGuide(): string {
  return readFileSync(
    path.join(process.cwd(), "content", "TRADING_CONCEPTS.md"),
    "utf8",
  );
}

// Wrap GFM tables so wide tables scroll instead of breaking the layout on narrow
// windows; everything else is handled by the @tailwindcss/typography `prose` styles.
const markdownComponents = {
  table: (props: ComponentProps<"table">) => (
    <div className="overflow-x-auto">
      <table {...props} />
    </div>
  ),
};

export default function GuidePage() {
  const markdown = loadGuide();

  return (
    <main className="min-h-screen bg-bg text-text">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="text-2xl">📊</span>
          <h1 className="text-lg font-bold tracking-tight">statsArbBot</h1>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <Link
            href="/dashboard"
            className="rounded-lg border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            ← Dashboard
          </Link>
        </div>
      </header>

      <section className="mx-auto max-w-4xl px-6 py-10">
        <article
          className="
            prose prose-invert max-w-none
            prose-headings:text-text prose-headings:font-semibold
            prose-h1:text-3xl prose-h1:font-bold prose-h1:mb-3
            prose-h2:mt-12 prose-h2:border-b prose-h2:border-border prose-h2:pb-2
            prose-p:text-text/90 prose-li:text-text/90
            prose-strong:text-text
            prose-a:text-blue prose-a:no-underline hover:prose-a:underline
            prose-code:text-green prose-code:bg-card prose-code:rounded
            prose-code:px-1.5 prose-code:py-0.5 prose-code:font-normal
            prose-code:before:content-none prose-code:after:content-none
            prose-pre:bg-card prose-pre:border prose-pre:border-border prose-pre:text-text/90
            prose-blockquote:border-l-4 prose-blockquote:border-blue
            prose-blockquote:bg-card prose-blockquote:rounded-r-lg
            prose-blockquote:px-5 prose-blockquote:py-1 prose-blockquote:not-italic
            prose-blockquote:text-text/90
            prose-hr:border-border
            prose-table:text-sm
            prose-thead:border-border prose-th:text-text prose-th:font-semibold
            prose-td:text-text/90 prose-td:border-border
          "
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {markdown}
          </ReactMarkdown>
        </article>
      </section>
    </main>
  );
}
