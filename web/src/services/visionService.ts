/** Image input: a question image is read into text on the server (POST /api/vision/read) before it is sent. */

import { ApiError, apiFetch, detailOf, readJsonBody, type AuthHeaders, type RequestOptions } from "./apiClient.ts";

export type { AuthHeaders };

export interface ImageReading {
  id: string;
  filename: string;
  width: number;
  height: number;
  /** The transcription to solve from (vision model's, else the OCR markdown). */
  text: string;
  ocr_text: string;
  ocr_confidence: number | null;
  /** Reading steps that ran, in plain words ("text recognition", "vision check"). */
  engines: string[];
  vision_checked: boolean;
  /** How the two vision readings ended: agreed, settled (differed; decided against the image), unsettled, single, "". */
  consensus?: "agreed" | "settled" | "unsettled" | "single" | "";
  /** Where the two readings differed, "reading 1 | reading 2" in normalised tokens. */
  differences?: string[];
  /** Numbers in the transcription that OCR never read: check them against the image. */
  unconfirmed_numbers: string[];
  warnings: string[];
  seconds: number;
  /** Pages read (a PDF); 1 for an image. */
  pages?: number;
}

/** One image in the composer, from selection to a reviewed transcription. */
export interface ComposerImage {
  key: string;
  name: string;
  /** A PDF has no image preview; its pages are read on the server. */
  kind?: "image" | "pdf";
  /** The file as selected (or as rotated or cropped), kept so it can be edited and read again. */
  file?: File;
  previewUrl: string;
  /** A small JPEG data URL kept with the sent message (the full image is never stored). */
  thumbUrl: string;
  /** A larger JPEG (long side 1400 px) for the in-app viewer of a sent message. */
  viewUrl?: string;
  status: "reading" | "ready" | "error";
  reading?: ImageReading;
  /** The transcription as the user edited it; this is what is sent. */
  text: string;
  error?: string;
}

/** An image shown on a sent user message: its name, a thumbnail, a viewer-sized copy and the text read from it. */
export interface MessageImage {
  name: string;
  thumbUrl?: string;
  viewUrl?: string;
  /** The transcription that was sent with the question (what Tribos read from the image). */
  text?: string;
}

/** One plain line on how a reading was checked (engine and model names stay on the server). */
export function readingSummary(reading: Pick<ImageReading, "engines" | "vision_checked" | "consensus" | "differences"> | null | undefined): string {
  if (!reading) return "";
  const ocr = reading.engines.filter((e) => e === "text recognition" || e === "word recognition").length;
  const recognizers = ocr >= 2 ? "two text recognizers" : ocr === 1 ? "text recognition" : "";
  const places = reading.differences?.length ?? 0;
  let vision = "";
  if (reading.vision_checked) {
    switch (reading.consensus) {
      case "agreed":
        vision = "two independent vision readings agreed";
        break;
      case "settled":
        vision = `two vision readings differed in ${places || "some"} ${places === 1 ? "place" : "places"}, settled against the image`;
        break;
      case "unsettled":
        vision = "two vision readings differ; check against the image";
        break;
      default:
        vision = "checked against the image";
    }
    if (reading.engines.includes("vision repair")) vision += " (read again for missing lines)";
  }
  if (!vision) return recognizers ? `Read by ${recognizers}` : "";
  const text = recognizers ? `Read by ${recognizers}; ${vision}` : `Read by the vision model; ${vision}`;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/bmp,image/tiff,application/pdf";
export const MAX_IMAGES = 4;
const MAX_MB = 10;

export function isAcceptedImage(file: File): boolean {
  return IMAGE_ACCEPT.split(",").includes(file.type);
}

export function precheckImage(file: File): string | null {
  if (!isAcceptedImage(file)) return "Use a PNG, JPEG, WebP, BMP or TIFF image, or a PDF.";
  if (file.size > MAX_MB * 1024 * 1024) return `Images are limited to ${MAX_MB} MB.`;
  return null;
}

/** A small JPEG thumbnail (long side `side` px) for the message history. */
export async function makeThumbnail(file: File, side = 160): Promise<string> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("unreadable image"));
      el.src = url;
    });
    const scale = Math.min(1, side / Math.max(img.naturalWidth, img.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) return "";
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", side > 400 ? 0.82 : 0.72);
  } catch {
    return "";
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Reads an image (or PDF) into text on the server. `options.onStatus` sees the response status, so the page can
 * raise its sign-in banner on a 401/403 like every other call.
 */
export async function readImage(
  backendUrl: string,
  authHeaders: AuthHeaders,
  file: File,
  options: Pick<RequestOptions, "onStatus"> = {}
): Promise<ImageReading> {
  const form = new FormData();
  form.append("file", file, file.name || "image.png");
  const headers = Object.fromEntries(Object.entries(authHeaders()).filter(([k]) => k.toLowerCase() !== "content-type"));
  const res = await apiFetch(
    `${backendUrl}/api/vision/read`,
    { method: "POST", headers, body: form },
    {
      onStatus: options.onStatus,
      toError: (status, body) => {
        const detail = detailOf(body);
        return new ApiError(status, detail || `Reading the image failed (${status}).`, { detail, body });
      },
    }
  );
  return (await readJsonBody(res)) as ImageReading;
}

/** The image turned a quarter turn clockwise (PNG), for a photo taken sideways. */
export async function rotateImage(file: File): Promise<File> {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.height;
  canvas.height = bitmap.width;
  const ctx = canvas.getContext("2d");
  if (!ctx) return file;
  ctx.translate(canvas.width, 0);
  ctx.rotate(Math.PI / 2);
  ctx.drawImage(bitmap, 0, 0);
  const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
  return blob ? new File([blob], file.name.replace(/\.[a-z]+$/i, "") + ".png", { type: "image/png" }) : file;
}

/** The part of the image inside `box` (fractions 0–1 of its width and height), as PNG. */
export async function cropImage(file: File, box: { x: number; y: number; w: number; h: number }): Promise<File> {
  const bitmap = await createImageBitmap(file);
  const sx = Math.round(box.x * bitmap.width);
  const sy = Math.round(box.y * bitmap.height);
  const sw = Math.max(8, Math.round(box.w * bitmap.width));
  const sh = Math.max(8, Math.round(box.h * bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = sw;
  canvas.height = sh;
  const ctx = canvas.getContext("2d");
  if (!ctx) return file;
  ctx.drawImage(bitmap, sx, sy, sw, sh, 0, 0, sw, sh);
  const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
  return blob ? new File([blob], file.name.replace(/\.[a-z]+$/i, "") + "-crop.png", { type: "image/png" }) : file;
}

/** The question sent when the user attaches an image and types nothing. */
export const DEFAULT_IMAGE_QUESTION = "Solve the problem in the attached image, showing every step.";

/** What a sent message keeps of its images: names and small thumbnails. */
export function sentImages(images: ComposerImage[]): MessageImage[] {
  return images.filter((i) => i.status === "ready").map((i) => ({
    name: i.name,
    thumbUrl: i.thumbUrl || undefined,
    viewUrl: i.viewUrl || undefined,
    text: i.text.trim() ? i.text.trim().slice(0, 8000) : undefined,
  }));
}

/** The request field for the chat: the reviewed transcriptions of the images that were read. */
export function imageContext(images: ComposerImage[]): { name: string; text: string }[] | undefined {
  const ready = images.filter((i) => i.status === "ready" && i.text.trim());
  return ready.length ? ready.map((i) => ({ name: i.name.slice(0, 120), text: i.text.trim().slice(0, 8000) })) : undefined;
}
