import type { ParsedFacts } from "@/lib/types";

export function ParsedPanel({ p }: { p: ParsedFacts }) {
  const hasContent =
    p.summary || p.legal_issues.length || p.statutes.length || p.keywords.length;
  if (!hasContent) return null;

  return (
    <aside className="rounded-xl border border-black/10 bg-court/5 p-5">
      <h2 className="font-serif text-sm font-semibold uppercase tracking-wide text-court/70">
        How the tool read your facts
      </h2>

      {p.summary && (
        <p className="mt-2 text-sm leading-relaxed text-ink/80">{p.summary}</p>
      )}

      {p.legal_issues.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase text-court/60">
            Legal issues
          </div>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink/85">
            {p.legal_issues.map((i, idx) => (
              <li key={idx}>{i}</li>
            ))}
          </ul>
        </div>
      )}

      {p.statutes.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase text-court/60">
            Statutes engaged
          </div>
          <ul className="mt-1 space-y-1 text-sm text-ink/85">
            {p.statutes.map((s, idx) => (
              <li key={idx}>
                <span className="font-medium">{s.act}</span>
                {s.sections.length > 0 && (
                  <span className="text-court/70">
                    {" "}
                    — s. {s.sections.join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {p.keywords.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {p.keywords.map((k, idx) => (
            <span
              key={idx}
              className="rounded-full bg-white px-2.5 py-0.5 text-xs text-court/80 ring-1 ring-black/5"
            >
              {k}
            </span>
          ))}
        </div>
      )}
    </aside>
  );
}
