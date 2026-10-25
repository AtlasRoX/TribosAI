"use client";

import React, { useRef, useState } from "react";
import { AlertTriangle, Crop, FileText, Loader2, RotateCw, X } from "lucide-react";
import type { ComposerImage } from "@/services/visionService";
import { MarkdownRenderer } from "./MarkdownRenderer";
import styles from "./ComposerImages.module.css";

interface ComposerImagesProps {
  images: ComposerImage[];
  onChangeText: (key: string, text: string) => void;
  onRemove: (key: string) => void;
  /** Rotate (no box) or crop (box in fractions of the image), then read the result again. */
  onEdit?: (key: string, edit: { rotate: true } | { crop: { x: number; y: number; w: number; h: number } }) => void;
}

/** Drag a rectangle over the preview to choose what to keep. */
function CropArea({ src, onApply, onCancel }: { src: string; onApply: (box: { x: number; y: number; w: number; h: number }) => void; onCancel: () => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [start, setStart] = useState<{ x: number; y: number } | null>(null);
  const [box, setBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const at = (e: React.PointerEvent) => {
    const r = wrap.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  return (
    <div className={styles.cropWrap}>
      <div
        ref={wrap}
        className={styles.cropArea}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          const p = at(e);
          setStart(p);
          setBox({ x: p.x, y: p.y, w: 0, h: 0 });
        }}
        onPointerMove={(e) => {
          if (!start) return;
          const p = at(e);
          setBox({ x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y) });
        }}
        onPointerUp={() => setStart(null)}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- a local object URL */}
        <img src={src} alt="Drag to choose the part to keep" className={styles.cropImg} draggable={false} />
        {box && box.w > 0 && (
          <div
            className={styles.cropBox}
            style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.w * 100}%`, height: `${box.h * 100}%` }}
          />
        )}
      </div>
      <div className={styles.cropActions}>
        <span className={styles.meta}>Drag over the part to keep</span>
        <button type="button" className={styles.linkBtn} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className={styles.linkBtn} disabled={!box || box.w < 0.03 || box.h < 0.03} onClick={() => box && onApply(box)}>
          Crop and read again
        </button>
      </div>
    </div>
  );
}

/**
 * Images attached to the question, each read into text on the server. The transcription is shown for review before
 * sending (rendered and editable), with any warnings and the numbers only the vision check saw, so a misread digit or a
 * lost derivative dot is caught before the question is solved.
 */
export function ComposerImages({ images, onChangeText, onRemove, onEdit }: ComposerImagesProps) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [cropping, setCropping] = useState(false);
  if (!images.length) return null;
  const open = images.find((i) => i.key === openKey) ?? null;

  return (
    <div className={styles.wrap}>
      <ul className={styles.chips} aria-label="Attached images">
        {images.map((img) => {
          const flagged = img.status === "ready" && Boolean(img.reading?.unconfirmed_numbers.length || img.reading?.warnings.length);
          return (
            <li key={img.key} className={styles.chip} data-open={img.key === openKey || undefined} data-status={img.status}>
              <button
                type="button"
                className={styles.chipMain}
                onClick={() => {
                  setOpenKey(img.key === openKey ? null : img.key);
                  setEditing(false);
                  setCropping(false);
                }}
                aria-expanded={img.key === openKey}
                disabled={img.status === "reading"}
                title={img.status === "ready" ? "Review the text read from this image" : img.error || img.name}
              >
                {img.kind === "pdf" ? (
                  <span className={styles.thumb} aria-hidden="true">
                    <FileText style={{ width: 16, height: 16 }} />
                  </span>
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element -- a local object URL
                  <img src={img.previewUrl} alt="" className={styles.thumb} />
                )}
                <span className={styles.chipText}>
                  <span className={styles.chipName}>{img.name}</span>
                  <span className={styles.chipStatus}>
                    {img.status === "reading" ? (
                      <>
                        <Loader2 className={styles.spin} style={{ width: 11, height: 11 }} aria-hidden="true" /> Reading…
                      </>
                    ) : img.status === "error" ? (
                      "Could not read"
                    ) : flagged ? (
                      <>
                        <AlertTriangle style={{ width: 11, height: 11 }} aria-hidden="true" /> Review text
                      </>
                    ) : (
                      "Text ready · review"
                    )}
                  </span>
                </span>
              </button>
              <button
                type="button"
                className={styles.remove}
                onClick={() => {
                  if (openKey === img.key) setOpenKey(null);
                  onRemove(img.key);
                }}
                aria-label={`Remove ${img.name}`}
                title="Remove"
              >
                <X style={{ width: 12, height: 12 }} aria-hidden="true" />
              </button>
            </li>
          );
        })}
      </ul>

      {open && open.status !== "reading" && (
        <div className={styles.review} role="region" aria-label={`Text read from ${open.name}`}>
          {open.kind === "pdf" ? (
            <div className={styles.pdfPreview}>
              <FileText style={{ width: 28, height: 28 }} aria-hidden="true" />
              <span>{open.reading?.pages ? `${open.reading.pages} page${open.reading.pages === 1 ? "" : "s"} read` : "PDF"}</span>
            </div>
          ) : cropping ? (
            <CropArea
              src={open.previewUrl}
              onCancel={() => setCropping(false)}
              onApply={(box) => {
                setCropping(false);
                onEdit?.(open.key, { crop: box });
              }}
            />
          ) : (
            <div className={styles.previewCol}>
              {/* eslint-disable-next-line @next/next/no-img-element -- a local object URL */}
              <img src={open.previewUrl} alt={`Attached image ${open.name}`} className={styles.preview} />
              {onEdit && open.file && (
                <div className={styles.imageTools}>
                  <button type="button" onClick={() => onEdit(open.key, { rotate: true })} title="Turn a quarter turn clockwise and read again">
                    <RotateCw style={{ width: 12, height: 12 }} aria-hidden="true" /> Rotate
                  </button>
                  <button type="button" onClick={() => setCropping(true)} title="Keep only part of the image and read again">
                    <Crop style={{ width: 12, height: 12 }} aria-hidden="true" /> Crop
                  </button>
                </div>
              )}
            </div>
          )}
          <div className={styles.reviewBody}>
            {open.status === "error" ? (
              <p className={styles.warn}>{open.error || "The image could not be read."}</p>
            ) : (
              <>
                <div className={styles.reviewHead}>
                  <span className={styles.reviewTitle}>Text read from the image</span>
                  <button type="button" className={styles.linkBtn} onClick={() => setEditing((e) => !e)}>
                    {editing ? "Preview" : "Edit"}
                  </button>
                </div>
                {editing ? (
                  <textarea
                    className={styles.editor}
                    value={open.text}
                    onChange={(e) => onChangeText(open.key, e.target.value)}
                    aria-label="Transcription (Markdown with LaTeX)"
                    rows={6}
                    spellCheck={false}
                  />
                ) : (
                  <div className={styles.rendered}>
                    {open.text.trim() ? <MarkdownRenderer content={open.text} /> : <p className={styles.warn}>No text was found.</p>}
                  </div>
                )}
                {open.reading?.unconfirmed_numbers.length ? (
                  <p className={styles.warn}>
                    Check these numbers against the image:{" "}
                    {open.reading.unconfirmed_numbers.map((n) => (
                      <code key={n} className={styles.num}>
                        {n}
                      </code>
                    ))}
                  </p>
                ) : null}
                {open.reading?.warnings.map((w, i) => (
                  <p key={i} className={styles.warn}>
                    {w}
                  </p>
                ))}
                <p className={styles.meta}>
                  {[
                    open.reading?.vision_checked ? "Read and checked against the image" : "Read by text recognition",
                    open.reading ? `${open.reading.seconds.toFixed(1)} s` : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Image thumbnails on a sent user message. */
export function MessageImages({ images }: { images: { name: string; thumbUrl?: string }[] }) {
  if (!images.length) return null;
  return (
    <ul className={styles.sent} aria-label="Attached images">
      {images.map((img, i) => (
        <li key={i} className={styles.sentItem} title={img.name}>
          {img.thumbUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- a stored data URL thumbnail
            <img src={img.thumbUrl} alt={img.name} className={styles.sentThumb} />
          ) : (
            <span className={styles.sentName}>{img.name}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
