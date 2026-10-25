"use server";

import { revalidatePath } from "next/cache";
import { API } from "@/lib/api";

async function post(path: string, body?: unknown) {
  const token = process.env.MKT_API_TOKEN;
  if (!token) throw new Error("MKT_API_TOKEN is not set on the web app");
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json();
}

export async function addCreator(form: FormData) {
  await post("/creators", {
    handle: String(form.get("handle")).replace(/^@/, ""),
    channel: form.get("channel") || "discord",
    rate_per_1k: Number(form.get("rate_per_1k") || 1),
    followers: form.get("followers") ? Number(form.get("followers")) : null,
    notes: form.get("notes") || "",
  });
  revalidatePath("/creators");
}

export async function setBriefStatus(id: number, status: string) {
  await post(`/briefs/${id}/status?status=${status}`);
  revalidatePath("/briefs");
}

export async function addPost(form: FormData) {
  await post("/posts", {
    creator: String(form.get("creator")).replace(/^@/, ""),
    url: form.get("url"),
    brief_id: form.get("brief_id") ? Number(form.get("brief_id")) : null,
    script_id: form.get("script_id") ? Number(form.get("script_id")) : null,
  });
  revalidatePath("/creators");
  revalidatePath("/payouts");
}

export async function markPaid(videoId: string, amount: number, views: number) {
  await post(`/payouts/${videoId}/paid`, { amount_usd: amount, views });
  revalidatePath("/payouts");
}

export async function startRun(form: FormData) {
  await post("/runs", {
    niche: form.get("niche") || "wearables",
    tags: String(form.get("tags") || "smartring whoop ouraring").split(/[\s,]+/).filter(Boolean),
    product: form.get("product"),
    renders: Number(form.get("renders") || 1),
  });
  revalidatePath("/runs");
}

export async function repollNow() {
  const r = await post("/repoll");
  revalidatePath("/findings");
  revalidatePath("/");
  return r;
}

export async function analyzeNow() {
  const r = await post("/analyze");
  revalidatePath("/findings");
  revalidatePath("/");
  return r;
}
