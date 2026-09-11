import { useEffect, useRef, useState } from "react";
import type { Json, Row } from "../api";

export type Field = {
  key: string;
  label: string;
  kind?: "number" | "text" | "date" | "boolean" | "select" | "json";
  options?: readonly (string | readonly [string, string])[];
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  required?: boolean;
  numericOptions?: boolean;
};
export function FieldGrid({
  fields,
  value,
  onChange,
  disabled = false,
  onJsonValidity,
}: {
  fields: readonly Field[];
  value: Row;
  onChange: (key: string, value: Json) => void;
  disabled?: boolean;
  onJsonValidity?: (key: string, valid: boolean) => void;
}) {
  return (
    <div className="form-grid">
      {fields.map((field) => {
        const current = value[field.key];
        if (field.kind === "boolean")
          return (
            <label className="toggle-field" key={field.key}>
              <input
                type="checkbox"
                checked={current === true}
                disabled={disabled}
                onChange={(e) => onChange(field.key, e.target.checked)}
              />
              <span>
                {field.label}
                {field.hint && <small>{field.hint}</small>}
              </span>
            </label>
          );
        return (
          <label
            key={field.key}
            className={field.kind === "json" ? "wide-field" : ""}
          >
            <span>
              {field.label}
              {field.required && <span aria-hidden="true"> *</span>}
            </span>
            {field.kind === "select" ? (
              <select
                value={String(current ?? "")}
                disabled={disabled}
                required={field.required}
                onChange={(e) =>
                  onChange(
                    field.key,
                    e.target.value === ""
                      ? null
                      : field.numericOptions
                        ? Number(e.target.value)
                        : e.target.value,
                  )
                }
              >
                <option value="">未指定</option>
                {current != null &&
                  !field.options?.some(
                    (item) =>
                      (typeof item === "string" ? item : item[0]) ===
                      String(current),
                  ) && (
                    <option value={String(current)}>
                      {String(current)}（保存済み）
                    </option>
                  )}
                {field.options?.map((item) => {
                  const [key, label] =
                    typeof item === "string" ? [item, item] : item;
                  return (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  );
                })}
              </select>
            ) : field.kind === "json" ? (
              <JsonField
                value={current}
                onChange={(v) => onChange(field.key, v)}
                onValidity={(valid) => onJsonValidity?.(field.key, valid)}
                disabled={disabled}
              />
            ) : (
              <input
                type={field.kind ?? "text"}
                value={
                  typeof current === "number" || typeof current === "string"
                    ? current
                    : ""
                }
                disabled={disabled}
                min={field.min}
                max={field.max}
                step={field.step ?? "any"}
                required={field.required}
                onChange={(e) =>
                  onChange(
                    field.key,
                    field.kind === "number"
                      ? e.target.value === ""
                        ? null
                        : Number(e.target.value)
                      : e.target.value,
                  )
                }
              />
            )}
            {field.hint && <small>{field.hint}</small>}
          </label>
        );
      })}
    </div>
  );
}

export function JsonField({
  value,
  onChange,
  disabled = false,
  onValidity,
}: {
  value: Json | undefined;
  onChange: (value: Json) => void;
  disabled?: boolean;
  onValidity?: (valid: boolean) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value ?? null, null, 2));
  const [error, setError] = useState("");
  const last = useRef(JSON.stringify(value ?? null));
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (JSON.stringify(value ?? null) !== last.current) {
      setText(JSON.stringify(value ?? null, null, 2));
      setError("");
      input.current?.setCustomValidity("");
      last.current = JSON.stringify(value ?? null);
    }
  }, [value]);
  return (
    <>
      <textarea
        ref={input}
        rows={6}
        value={text}
        disabled={disabled}
        spellCheck={false}
        aria-label="JSONデータ"
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed = JSON.parse(e.target.value) as Json;
            last.current = JSON.stringify(parsed);
            onChange(parsed);
            setError("");
            e.target.setCustomValidity("");
            onValidity?.(true);
          } catch {
            const message =
              "JSONの書式を確認してください。修正するまで保存できません。";
            setError(message);
            e.target.setCustomValidity(message);
            onValidity?.(false);
          }
        }}
      />
      {error && <small className="error">{error}</small>}
    </>
  );
}
