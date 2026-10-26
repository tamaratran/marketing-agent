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





export async function startRun() {
  await post("/runs", {});
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

export async function addPost(formData: FormData) {
  const url = String(formData.get("url") ?? "").trim();
  const caption = String(formData.get("caption") ?? "").trim();
  if (!url) return;
  await post("/ours/posts", { url, caption });
  revalidatePath("/ours");
}

export async function postClip(formData: FormData) {
  const id = Number(formData.get("script_id"));
  await post(`/renders/${id}/post`);
  revalidatePath("/clips");
  revalidatePath("/");
}

export async function holdClip(formData: FormData) {
  const id = Number(formData.get("script_id"));
  await post(`/renders/${id}/hold`, { reason: String(formData.get("reason") ?? "") });
  revalidatePath("/clips");
  revalidatePath("/");
}

export async function releaseClip(formData: FormData) {
  const id = Number(formData.get("script_id"));
  await post(`/renders/${id}/release`);
  revalidatePath("/clips");
  revalidatePath("/");
}
