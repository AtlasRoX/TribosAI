"use client";

// Create or edit a project: name, description, an emoji and a colour (from fixed swatches), and the instructions the
// project adds to every chat in it. Focus stays in the dialog; Esc cancels.

import React, { useEffect, useState } from "react";
import { PROJECT_COLORS, PROJECT_EMOJIS, safeColor } from "@/lib/sidebarData";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { errorMessage } from "@/services/apiClient";
import type { Project, ProjectInput } from "@/types/agentic";
import styles from "./Projects.module.css";

export function ProjectDialog({ project, onSave, onClose }: {
  project?: Project | null;
  onSave: (input: ProjectInput) => Promise<unknown>;
  onClose: () => void;
}) {
  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [instructions, setInstructions] = useState(project?.instructions ?? "");
  const [icon, setIcon] = useState(project?.icon || PROJECT_EMOJIS[0]);
  const [color, setColor] = useState(safeColor(project?.color));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const ref = useFocusTrap<HTMLFormElement>(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      await onSave({ name: name.trim(), description, instructions, icon, color });
      onClose();
    } catch (err) {
      setError(errorMessage(err, "The project could not be saved."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.overlay} role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form ref={ref} className={styles.dialog} role="dialog" aria-modal="true" aria-label={project ? "Edit project" : "New project"}
        onSubmit={submit}>
        <h2 className={styles.dialogTitle}>{project ? "Edit project" : "New project"}</h2>
        <label className={styles.field}>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required autoFocus />
        </label>
        <div className={styles.field}>
          Icon
          <div className={styles.swatches} role="radiogroup" aria-label="Project icon">
            {PROJECT_EMOJIS.map((e) => (
              <button key={e} type="button" role="radio" aria-checked={icon === e} className={icon === e ? styles.swatchOn : styles.swatch}
                onClick={() => setIcon(e)}>{e}</button>
            ))}
          </div>
        </div>
        <div className={styles.field}>
          Colour
          <div className={styles.swatches} role="radiogroup" aria-label="Project colour">
            {PROJECT_COLORS.map((c) => (
              <button key={c} type="button" role="radio" aria-checked={color === c} aria-label={c}
                className={color === c ? styles.swatchOn : styles.swatch} style={{ background: c }} onClick={() => setColor(c)} />
            ))}
          </div>
        </div>
        <label className={styles.field}>
          Description
          <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
        </label>
        <label className={styles.field}>
          Instructions for every chat in this project
          <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={8000} rows={4}
            placeholder="e.g. Use SI units; cite the design standard; S355 unless stated." />
        </label>
        {error && <p className={styles.error} role="alert">{error}</p>}
        <div className={styles.dialogButtons}>
          <button type="button" className={styles.btn} onClick={onClose}>Cancel</button>
          <button type="submit" className={styles.btnPrimary} disabled={saving || !name.trim()}>{saving ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </div>
  );
}
