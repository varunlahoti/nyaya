import type { JudgmentResult } from "@/lib/types";

function scoreColor(score: number): string {
  if (score >= 80) return "#2f7d4f";
  if (score >= 60) return "#b3873f";
  return "#8a8a8a";
}

export function ResultCard({ r }: { r: JudgmentResult }) {
  return (
    <article className="rounded-xl border border-black/10 bg-white/80 p-5 shadow-sm transition hover:shadow-md">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-court/70">
            <span className="rounded bg-court/10 px-2 py-0.5 font-medium">
              #{r.rank}
            </span>
            {r.court && <span>{r.court}</span>}
            {r.date && <span>· {r.date}</span>}
          </div>
          <h3 className="mt-1 font-serif text-lg font-semibold text-ink">
            {r.url ? (
              <a
                href={r.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-brass hover:underline"
              >
                {r.title}
              </a>
            ) : (
              r.title
            )}
          </h3>
          {r.citation && (
            <div className="mt-0.5 text-sm text-court/80">{r.citation}</div>
          )}
        </div>

        <div
          className="score-ring grid h-12 w-12 shrink-0 place-items-center rounded-full"
          style={
            {
              ["--v" as any]: r.relevance_score,
              ["--c" as any]: scoreColor(r.relevance_score),
            } as React.CSSProperties
          }
          title="Relevance to your facts"
        >
          <span className="grid h-9 w-9 place-items-center rounded-full bg-white text-sm font-semibold text-ink">
            {r.relevance_score}
          </span>
        </div>
      </div>

      {r.relevance_note && (
        <p className="mt-3 text-[15px] leading-relaxed text-ink/90">
          <span className="font-medium text-brass">Why it matters — </span>
          {r.relevance_note}
        </p>
      )}
      {r.holding && (
        <p className="mt-2 text-sm leading-relaxed text-ink/70">
          <span className="font-medium">Holding — </span>
          {r.holding}
        </p>
      )}

      <div className="mt-3 flex items-center gap-3 text-xs text-court/60">
        <span className="rounded bg-parchment px-2 py-0.5">{r.source}</span>
        {r.url && (
          <a
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-brass hover:underline"
          >
            Open source →
          </a>
        )}
      </div>
    </article>
  );
}
