
export function H1({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div className="mb-10">
      <h1 className="text-3xl font-semibold tracking-tight text-neutral-50 sm:text-4xl">{children}</h1>
      {sub && <p className="mt-2 max-w-xl text-neutral-400">{sub}</p>}
    </div>
  );
}

export function Card({ title, children, className = "" }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`mt-12 ${className}`}>
      {title && <h2 className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-neutral-500">{title}</h2>}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div>
      <div className="text-4xl font-semibold tabular-nums tracking-tight text-neutral-50">{value}</div>
      <div className="mt-1 text-xs text-neutral-500">{label}</div>
      {hint && <div className="mt-1 text-xs leading-snug text-neutral-600">{hint}</div>}
    </div>
  );
}

/** A short "how to read this" line under a heading or table. */
export function Note({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <p className={`text-xs leading-relaxed text-neutral-500 ${className}`}>{children}</p>;
}

export function Table({ head, rows, empty = "Nothing yet." }: { head: string[]; rows: React.ReactNode[][]; empty?: React.ReactNode }) {
  if (!rows.length) return <p className="text-sm text-neutral-500">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="text-left text-xs text-neutral-500">
            {head.map((h, i) => <th key={i} className="pb-2 pr-4 font-normal">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-rule align-top">
              {r.map((c, j) => <td key={j} className="py-2.5 pr-4">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const dot = { neutral: "bg-neutral-500", good: "bg-neutral-100", warn: "bg-gold", bad: "bg-neutral-600" }[tone];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-neutral-400">
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {children}
    </span>
  );
}

export const input = "border-b border-neutral-700 bg-transparent px-1 py-1 text-sm text-neutral-100 placeholder:text-neutral-600 focus:border-neutral-300 focus:outline-none";
export const button = "rounded-sm bg-gold px-3 py-1.5 text-sm font-medium text-neutral-950 hover:brightness-110 disabled:opacity-50";
export const ghost = "text-sm text-neutral-400 underline decoration-neutral-700 underline-offset-4 hover:text-neutral-100";

/** A log10 lift as a plain multiple: +1 means 10x the creator's usual views, -0.3 about half. */
export const times = (r: number) => {
  const x = 10 ** r;
  return x >= 10 ? `${Math.round(x)}x` : x >= 1 ? `${x.toFixed(1)}x` : `${x.toFixed(2)}x`;
};

export const reward = (r: number | null | undefined, empty = "not scored yet", suffix = "usual") =>
  r == null ? <span className="text-neutral-600" title="Videos are scored once they are a day old and the creator has a baseline">{empty}</span> : (
    <span className={r > 0 ? "text-neutral-50" : "text-neutral-400"} title={`log10 lift ${r > 0 ? "+" : ""}${r.toFixed(2)}`}>{times(r)} {suffix}</span>
  );

/** Concept names without the research agent's "Clone:" prefix. */
export const formatName = (n: string) => n.replace(/\bClone:\s*/g, "");

/** snake_case classifier labels as words. */
export const human = (s: string | null | undefined) => (s ? s.replaceAll("_", " ") : "");

export const pt = (ts: number) =>
  new Date(ts * 1000).toLocaleString("en-US", { timeZone: "America/Los_Angeles", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " PT";

/** A collapsed section: one summary line, open for the detail. Plain HTML, so it works without JS. */
export function Fold({ summary, children, open = false, className = "" }: { summary: React.ReactNode; children: React.ReactNode; open?: boolean; className?: string }) {
  return (
    <details open={open} className={`group border-t border-rule ${className}`}>
      <summary className="flex cursor-pointer list-none items-center gap-3 py-3 marker:hidden [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1">{summary}</span>
        <span aria-hidden className="shrink-0 text-xs text-neutral-600 transition-transform group-open:rotate-90">▸</span>
      </summary>
      <div className="pb-5 pt-1">{children}</div>
    </details>
  );
}

/** The three steps of the loop, in order; the nav reads this. */
export const STEPS: { href: string; label: string; what: string }[] = [
  { href: "/", label: "Formats", what: "what works in the niche" },
  { href: "/learnings", label: "Learnings", what: "what we learned, what to make next" },
  { href: "/clips", label: "Clips", what: "what got made, how it is doing, back into step 1" },
];
