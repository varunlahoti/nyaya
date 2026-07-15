"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { search, UnauthorizedError } from "@/lib/api";
import { isAuthed, logout } from "@/lib/auth";
import type { SearchResponse } from "@/lib/types";
import { ResultCard } from "@/components/ResultCard";
import { ParsedPanel } from "@/components/ParsedPanel";
import { Attribution } from "@/components/Attribution";

const SAMPLE =
  "The tenant stopped paying rent for 8 months. The landlord issued a notice under the Transfer of Property Act and now seeks eviction. The tenant claims the notice was defective and that he is a statutory tenant.";

export default function Home() {
  const router = useRouter();
  const [facts, setFacts] = useState("");
  const [courtLevel, setCourtLevel] = useState("any");
  const [maxResults, setMaxResults] = useState(8);
  const [deep, setDeep] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resp, setResp] = useState<SearchResponse | null>(null);
  const [ready, setReady] = useState(false);

  // Require a logged-in session; otherwise send to /login.
  useEffect(() => {
    if (!isAuthed()) router.replace("/login");
    else setReady(true);
  }, [router]);

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  async function onSearch() {
    if (facts.trim().length < 20) {
      setError("Please describe the facts in a little more detail (min 20 characters).");
      return;
    }
    setError(null);
    setLoading(true);
    setResp(null);
    try {
      const data = await search({
        facts,
        jurisdiction: "any",
        court_level: courtLevel,
        max_results: maxResults,
        deep,
      });
      setResp(data);
    } catch (e: any) {
      if (e instanceof UnauthorizedError) {
        router.replace("/login");
      } else {
        setError(e.message || "Something went wrong.");
      }
    } finally {
      setLoading(false);
    }
  }

  if (!ready) return null;

  return (
    <main className="mx-auto max-w-4xl px-4 pb-24 pt-6">
      <div className="flex justify-end">
        <button onClick={onLogout} className="text-xs text-court/60 hover:text-brass">
          Sign out
        </button>
      </div>
      <header className="text-center">
        <div className="font-serif text-4xl font-bold tracking-tight text-ink">
          Nyaya <span className="text-brass">न्याय</span>
        </div>
        <p className="mx-auto mt-2 max-w-xl text-court/70">
          Type the facts of your case in plain language. Get the judgments that
          matter — from the Supreme Court, High Courts and Indian Kanoon — each
          with a source link and why it&apos;s relevant.
        </p>
      </header>

      <section className="mt-8 rounded-2xl border border-black/10 bg-white/80 p-5 shadow-sm">
        <label className="text-sm font-medium text-court/80">
          Facts of the case
        </label>
        <textarea
          value={facts}
          onChange={(e) => setFacts(e.target.value)}
          rows={6}
          placeholder="e.g. My client is a tenant facing eviction. The landlord…"
          className="mt-2 w-full resize-y rounded-lg border border-black/15 bg-parchment/60 p-3 text-[15px] leading-relaxed text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/20"
        />
        <div className="mt-2 flex items-center justify-between text-xs text-court/50">
          <button
            onClick={() => setFacts(SAMPLE)}
            className="hover:text-brass hover:underline"
            type="button"
          >
            Try a sample
          </button>
          <span>{facts.length} chars</span>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Select
            label="Judgments from"
            value={courtLevel}
            onChange={setCourtLevel}
            options={[
              ["any", "All courts"],
              ["supreme_court", "Supreme Court only"],
              ["high_court", "High Courts only"],
            ]}
          />
          <Select
            label="Results"
            value={String(maxResults)}
            onChange={(v) => setMaxResults(Number(v))}
            options={[
              ["5", "5 judgments"],
              ["8", "8 judgments"],
              ["10", "10 judgments"],
            ]}
          />
        </div>

        <label className="mt-3 flex items-center gap-2 text-sm text-court/80">
          <input
            type="checkbox"
            checked={deep}
            onChange={(e) => setDeep(e.target.checked)}
            className="h-4 w-4 accent-brass"
          />
          Deep mode — rank on full judgment text (higher quality, slower)
        </label>

        <button
          onClick={onSearch}
          disabled={loading}
          className="mt-4 w-full rounded-lg bg-court px-4 py-3 font-medium text-parchment transition hover:bg-ink disabled:opacity-60"
        >
          {loading ? "Researching case law…" : "Find relevant judgments"}
        </button>

        {error && (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
      </section>

      {loading && <LoadingSkeleton />}

      {resp && (
        <section className="mt-8 space-y-5">
          <div className="flex items-center justify-between text-xs text-court/60">
            <span>
              {resp.results.length} judgments · {resp.latency_ms} ms ·{" "}
              sources: {resp.sources_used.join(", ") || "none"}
              {resp.partial && " · partial"}
            </span>
          </div>

          {resp.notice && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {resp.notice}
            </p>
          )}

          {resp.parsed && <ParsedPanel p={resp.parsed} />}

          {/* MANDATORY: IK attribution on top of results (direct display). */}
          {resp.results.length > 0 &&
            resp.sources_used.includes("indian_kanoon") && (
              <div className="flex justify-end border-b border-black/10 pb-2">
                <Attribution />
              </div>
            )}

          <div className="space-y-4">
            {resp.results.map((r) => (
              <ResultCard key={r.judgment_id} r={r} />
            ))}
          </div>

          <p className="pt-2 text-center text-xs text-court/50">
            {resp.disclaimer}
          </p>
        </section>
      )}

      {/* Persistent attribution for integrated/RAG use of IK data. */}
      <footer className="mt-16 flex flex-col items-center gap-1 border-t border-black/10 pt-6 text-center text-xs text-court/50">
        <Attribution compact />
        <p>
          Case law via Indian Kanoon. Nyaya is a research aid for qualified
          professionals — not legal advice.
        </p>
      </footer>
    </main>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="block text-sm">
      <span className="text-court/70">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-black/15 bg-white px-3 py-2 text-ink outline-none focus:border-brass"
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}

function LoadingSkeleton() {
  return (
    <div className="mt-8 space-y-4">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-28 animate-pulse rounded-xl border border-black/10 bg-white/60"
        />
      ))}
    </div>
  );
}
