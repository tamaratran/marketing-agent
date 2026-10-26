export function H1({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-xl font-semibold">{children}</h1>
      {sub && <p className="mt-1 text-sm text-neutral-400">{sub}</p>}
    </div>
  );
}

export function Card({ title, children, className = "" }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-neutral-800 bg-neutral-900/60 p-4 ${className}`}>
      {title && <h2 className="mb-3 text-sm font-medium text-neutral-300">{title}</h2>}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/60 p-4">
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-neutral-400">{label}</div>
      {hint && <div className="mt-1 text-[11px] leading-snug text-neutral-600">{hint}</div>}
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
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-neutral-500">
            {head.map((h, i) => <th key={i} className="pb-2 pr-4 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-neutral-800/80 align-top">
              {r.map((c, j) => <td key={j} className="py-2 pr-4">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const t = { neutral: "bg-neutral-800 text-neutral-300", good: "bg-emerald-900/60 text-emerald-300", warn: "bg-amber-900/60 text-amber-300", bad: "bg-red-900/60 text-red-300" }[tone];
  return <span className={`rounded px-1.5 py-0.5 text-xs ${t}`}>{children}</span>;
}

export const input = "rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600";
export const button = "rounded bg-neutral-100 px-3 py-1 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50";
export const ghost = "rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-800";

/** A log10 lift as a plain multiple: +1 means 10x the creator's usual views, -0.3 about half. */
export const times = (r: number) => {
  const x = 10 ** r;
  return x >= 10 ? `${Math.round(x)}x` : x >= 1 ? `${x.toFixed(1)}x` : `${x.toFixed(2)}x`;
};

export const reward = (r: number | null | undefined, empty = "not scored yet") =>
  r == null ? <span className="text-neutral-600" title="Videos are scored once they are a day old and the creator has a baseline">{empty}</span> : (
    <span className={r > 0 ? "text-emerald-300" : "text-red-300"} title={`log10 lift ${r > 0 ? "+" : ""}${r.toFixed(2)}`}>{times(r)} usual</span>
  );

/** snake_case classifier labels as words. */
export const human = (s: string | null | undefined) => (s ? s.replaceAll("_", " ") : "");

export const pt = (ts: number) =>
  new Date(ts * 1000).toLocaleString("en-US", { timeZone: "America/Los_Angeles", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " PT";
