import type { ReactNode } from "react";

// Tiny renderer for the markdown the agent writes (headings, bullets, tables, bold, links).
// The content is ours, so no sanitising library is needed; unknown syntax falls back to text.
function inline(text: string, key: number): ReactNode {
  const parts: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)|(https?:\/\/\S+)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[1]) parts.push(<strong key={i++} className="text-neutral-100">{m[1]}</strong>);
    else if (m[2]) parts.push(<a key={i++} href={m[3]} target="_blank" className="text-accent hover:underline">{m[2]}</a>);
    else if (m[4]) parts.push(<em key={i++} className="text-neutral-400">{m[4]}</em>);
    else if (m[5]) parts.push(<a key={i++} href={m[5]} target="_blank" className="text-accent hover:underline break-all">{m[5].replace(/^https?:\/\/(www\.)?/, "").slice(0, 60)}</a>);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <span key={key}>{parts}</span>;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: ReactNode[] = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (!l.trim()) continue;
    const h = /^(#{1,4})\s+(.*)/.exec(l);
    if (h) {
      const cls = h[1].length <= 2 ? "mt-4 text-base font-semibold text-neutral-100" : "mt-4 text-xs font-semibold uppercase tracking-wide text-neutral-400";
      out.push(<div key={i} className={cls}>{inline(h[2], i)}</div>);
      continue;
    }
    if (l.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        const cells = lines[i].slice(1, lines[i].endsWith("|") ? -1 : undefined).split("|").map((c) => c.trim());
        if (!cells.every((c) => /^-+$/.test(c))) rows.push(cells);
        i++;
      }
      i--;
      const [head, ...body] = rows;
      out.push(
        <div key={i} className="my-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead><tr>{head.map((c, j) => <th key={j} className="border-b border-neutral-800 py-1 pr-3 font-medium text-neutral-400">{c}</th>)}</tr></thead>
            <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} className="border-b border-neutral-900 py-1 pr-3 align-top">{inline(c, j)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^[-*]\s+/.test(l)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^[-*]\s+/, ""));
      i--;
      out.push(<ul key={i} className="my-1 list-disc space-y-0.5 pl-5">{items.map((it, j) => <li key={j}>{inline(it, j)}</li>)}</ul>);
      continue;
    }
    out.push(<p key={i} className="my-1">{inline(l, i)}</p>);
  }
  return <div className="text-sm leading-relaxed text-neutral-300 [overflow-wrap:anywhere]">{out}</div>;
}
