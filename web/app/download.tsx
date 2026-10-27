"use client";
import { useState } from "react";

/** Saves the clip as a file; a plain <a download> is ignored for cross-origin URLs and just opens the video. */
export function Download({ src, children = "Download", className = "text-gold hover:underline" }: { src: string; children?: React.ReactNode; className?: string }) {
  const [busy, setBusy] = useState(false);
  const save = async (e: React.MouseEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const url = URL.createObjectURL(await (await fetch(src)).blob());
      const a = Object.assign(document.createElement("a"), { href: url, download: src.split("/").pop() ?? "clip.mp4" });
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      window.open(src, "_blank");
    } finally {
      setBusy(false);
    }
  };
  return <a href={src} onClick={save} className={className}>{busy ? "Saving..." : children}</a>;
}
