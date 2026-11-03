"use client";

import React, { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, Crop, FileText, Loader2, RotateCw, X } from "lucide-react";
import type { ComposerImage } from "@/services/visionService";
import { useFocusTrap } from "@/lib/useFocusTrap";
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

type SentImage = { name: string; thumbUrl?: string; viewUrl?: string; text?: string };

/** Image thumbnails on a sent user message; a click opens the image beside the text Tribos read from it. */
export function MessageImages({ images }: { images: SentImage[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!images.length) return null;
  return (
    <>
      <ul className={styles.sent} aria-label="Attached images">
        {images.map((img, i) => (
          <li key={i} className={styles.sentItem}>
            <button
              type="button"
              className={styles.sentButton}
              onClick={() => setOpen(i)}
              title={`${img.name}: open the image and what was read from it`}
              aria-label={`Open ${img.name} and the text read from it`}
            >
              {img.thumbUrl ? (
                // eslint-disable-next-line @next/next/no-img-element -- a stored data URL thumbnail
                <img src={img.thumbUrl} alt={img.name} className={styles.sentThumb} />
              ) : (
                <span className={styles.sentName}>{img.name}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
      {open !== null && images[open] && typeof document !== "undefined" &&
        // Rendered into <body>: inside the message column a transformed ancestor trapped the fixed overlay.
        createPortal(<ImageViewer image={images[open]} onClose={() => setOpen(null)} />, document.body)}
    </>
  );
}

function ImageViewer({ image, onClose }: { image: SentImage; onClose: () => void }) {
  const ref = useFocusTrap<HTMLDivElement>(true);
  const [copied, setCopied] = useState(false);
  const src = image.viewUrl || image.thumbUrl;

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(image.text || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className={styles.viewerBackdrop} onClick={onClose} role="presentation">
      <div
        ref={ref}
        className={styles.viewer}
        role="dialog"
        aria-modal="true"
        aria-label={`${image.name} and the text read from it`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className={styles.viewerHead}>
          <span className={styles.viewerTitle}>{image.name}</span>
          <button type="button" className={styles.viewerClose} onClick={onClose} aria-label="Close">
            <X style={{ width: 16, height: 16 }} aria-hidden="true" />
          </button>
        </header>
        <div className={styles.viewerBody}>
          <div className={styles.viewerImage}>
            {src ? (
              // eslint-disable-next-line @next/next/no-img-element -- a stored data URL copy of the image
              <img src={src} alt={image.name} />
            ) : (
              <span className={styles.sentName}>No preview was kept for this image.</span>
            )}
            {!image.viewUrl && image.thumbUrl && (
              <p className={styles.viewerNote}>Only a small preview was kept for this older message.</p>
            )}
          </div>
          <section className={styles.viewerText} aria-label="What Tribos read from the image">
            <div className={styles.viewerTextHead}>
              <span>What Tribos read</span>
              {image.text && (
                <button type="button" className="msg-action-btn" onClick={copy}>
                  {copied ? "Copied" : "Copy text"}
                </button>
              )}
            </div>
            {image.text ? (
              <div className={styles.viewerTranscript}>
                <MarkdownRenderer content={image.text} />
              </div>
            ) : (
              <p className={styles.viewerNote}>
                The text read from this image was not kept with this message (it was sent before this view existed).
              </p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
