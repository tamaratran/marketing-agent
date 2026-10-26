"use client";
/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { frameUrl } from "@/lib/api";

/** Poster frame for a video we downloaded; videos we only polled have no frame and show a blank tile. */
export function Thumb({ id, size = 56, href }: { id: string; size?: number; href?: string }) {
  const [missing, setMissing] = useState(false);
  const ref = useRef<HTMLImageElement>(null);
  // The server-rendered <img> can fail before React hydrates, so onError never fires; check once mounted.
  useEffect(() => {
    const el = ref.current;
    if (el && el.complete && el.naturalWidth === 0) setMissing(true);
  }, []);
  const h = Math.round((size * 16) / 9);
  const img = missing ? (
    <div className="flex items-center justify-center rounded bg-neutral-800 text-center text-[9px] leading-tight text-neutral-500" style={{ width: size, height: h }} title="We only polled this video's stats, so there is no frame">
      no preview
    </div>
  ) : (
    <img ref={ref} src={frameUrl(id)} alt="" width={size} height={h} loading="lazy" onError={() => setMissing(true)} className="rounded bg-neutral-800 object-cover" style={{ width: size, height: h }} />
  );
  return href ? <Link href={href} className="block shrink-0">{img}</Link> : img;
}
