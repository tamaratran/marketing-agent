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





export async function startRun(form: FormData) {
  await post("/runs", {
    niche: form.get("niche") || process.env.MKT_NICHE || "wearables",
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
