"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, register } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, fullName);
      router.push("/");
    } catch (err: any) {
      setError(err.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <div className="text-center">
        <div className="font-serif text-4xl font-bold text-ink">
          Nyaya <span className="text-brass">न्याय</span>
        </div>
        <p className="mt-2 text-court/70">AI legal research for Indian advocates.</p>
      </div>

      <div className="mt-6 rounded-2xl border border-black/10 bg-white/80 p-6 shadow-sm">
        <div className="mb-4 flex rounded-lg bg-parchment/70 p-1 text-sm">
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex-1 rounded-md py-2 font-medium transition ${
                mode === m ? "bg-court text-parchment" : "text-court/70"
              }`}
            >
              {m === "login" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-3">
          {mode === "register" && (
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Full name (e.g. Adv. R. Sharma)"
              className="w-full rounded-lg border border-black/15 bg-parchment/60 p-3 text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/20"
            />
          )}
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full rounded-lg border border-black/15 bg-parchment/60 p-3 text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/20"
          />
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password (min 8 characters)"
            className="w-full rounded-lg border border-black/15 bg-parchment/60 p-3 text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/20"
          />
          {error && <p className="text-sm text-red-700">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-court px-4 py-3 font-medium text-parchment transition hover:bg-ink disabled:opacity-60"
          >
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
      </div>

      <p className="mt-4 text-center text-xs text-court/50">
        Research aid for qualified professionals — not legal advice.
      </p>
    </main>
  );
}
