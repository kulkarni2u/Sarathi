import { useState } from "react";
import type { FormEvent } from "react";
import "./FormModal.css";

export interface FormField {
  name: string;
  label: string;
  placeholder?: string;
  required?: boolean;
  defaultValue?: string;
  hint?: string;
  type?: "text" | "password";
}

interface FormModalProps {
  title: string;
  fields: FormField[];
  submitLabel: string;
  /** Called with trimmed field values. Throw to surface an inline error. */
  onSubmit: (values: Record<string, string>) => Promise<void>;
  onClose: () => void;
}

/**
 * Lightweight modal with a small set of text fields. Manages its own field
 * state, submit-in-flight state, and inline error display; closes itself on
 * successful submit. Used by the "New workspace" / "New project" actions.
 */
export function FormModal({ title, fields, submitLabel, onSubmit, onClose }: FormModalProps) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, f.defaultValue ?? ""])),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const missingRequired = fields.some((f) => f.required && !(values[f.name] ?? "").trim());

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting || missingRequired) return;
    setSubmitting(true);
    setError(null);
    try {
      const trimmed = Object.fromEntries(
        Object.entries(values).map(([key, value]) => [key, value.trim()]),
      );
      await onSubmit(trimmed);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="fm-overlay" role="dialog" aria-modal="true" onMouseDown={onClose}>
      <div className="fm-panel" onMouseDown={(e) => e.stopPropagation()}>
        <form onSubmit={handleSubmit}>
          <div className="fm-head">{title}</div>
          {fields.map((field, index) => (
            <label className="fm-field" key={field.name}>
              <span className="fm-label">
                {field.label}
                {field.required && <span className="fm-req"> *</span>}
              </span>
              <input
                className="fm-input"
                type={field.type ?? "text"}
                value={values[field.name] ?? ""}
                placeholder={field.placeholder}
                autoFocus={index === 0}
                autoComplete={field.type === "password" ? "new-password" : "off"}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [field.name]: e.target.value }))
                }
              />
              {field.hint && <span className="fm-hint">{field.hint}</span>}
            </label>
          ))}
          {error && <div className="fm-error">{error}</div>}
          <div className="fm-actions">
            <button type="button" className="btn ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={submitting || missingRequired}>
              {submitting ? "Saving…" : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
