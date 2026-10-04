/** Renders one field of any type, with its filtered options. */

import { FileField } from "./FileField";
import type { AnswerValue, FieldDefinition, Option } from "@/lib/types";
import { Labelled, inputClass } from "@/components/ui";

interface Props {
  fieldId: string;
  field: FieldDefinition;
  value: AnswerValue;
  options: Option[];
  required: boolean;
  error?: string;
  /** Needed by file fields, which upload before the answer is saved. */
  submissionId: string;
  resumeToken: string;
  onChange: (value: AnswerValue) => void;
}

export function FieldRenderer({
  fieldId,
  field,
  value,
  options,
  required,
  error,
  submissionId,
  resumeToken,
  onChange,
}: Props) {
  const label = field.label ?? field.key ?? "Question";

  // Delegated rather than inlined: a file answer is uploaded before it is
  // saved, so it has its own lifecycle.
  if (field.type === "file") {
    return (
      <FileField
        fieldId={fieldId}
        field={field}
        value={value}
        required={required}
        error={error}
        submissionId={submissionId}
        resumeToken={resumeToken}
        onChange={onChange}
      />
    );
  }

  if (field.type === "display") {
    return (
      <div className="rounded-lg border border-accent-line/40 bg-accent-soft p-3.5 text-sm text-ink-soft">
        {field.label}
      </div>
    );
  }

  const hint = field.sensitive
    ? "Encrypted before it is stored. It is never shown back to you."
    : field.help;

  return (
    <Labelled
      label={label}
      hint={hint}
      error={error}
      required={required}
      htmlFor={field.type === "radio" || field.type === "checkbox" ? undefined : fieldId}
    >
      {renderControl()}
    </Labelled>
  );

  function renderControl() {
    switch (field.type) {
      case "textarea":
        return (
          <textarea
            id={fieldId}
            className={`${inputClass} min-h-24`}
            value={(value as string) ?? ""}
            maxLength={field.max_length}
            onChange={(e) => onChange(e.target.value)}
          />
        );

      case "number":
        return (
          <input
            id={fieldId}
            type="number"
            inputMode="numeric"
            className={inputClass}
            value={value === null || value === undefined ? "" : String(value)}
            min={field.min}
            max={field.max}
            // Empty means unanswered, which is distinct from zero -- the
            // backend treats 0 as a real answer.
            onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          />
        );

      case "date":
        return (
          <input
            id={fieldId}
            type="date"
            className={inputClass}
            value={(value as string) ?? ""}
            onChange={(e) => onChange(e.target.value || null)}
          />
        );

      case "boolean":
        return (
          <div className="flex gap-4">
            {[
              { label: "Yes", v: true },
              { label: "No", v: false },
            ].map((choice) => (
              <label key={choice.label} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name={fieldId}
                  checked={value === choice.v}
                  onChange={() => onChange(choice.v)}
                />
                {choice.label}
              </label>
            ))}
          </div>
        );

      case "dropdown":
        return (
          <select
            id={fieldId}
            className={inputClass}
            value={(value as string) ?? ""}
            onChange={(e) => onChange(e.target.value || null)}
          >
            <option value="">Choose…</option>
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label ?? option.value}
              </option>
            ))}
          </select>
        );

      case "radio":
        return (
          <div role="radiogroup" aria-label={label} className="space-y-1.5">
            {options.map((option) => (
              <label key={option.value} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name={fieldId}
                  value={option.value}
                  checked={value === option.value}
                  onChange={() => onChange(option.value)}
                />
                {option.label ?? option.value}
              </label>
            ))}
          </div>
        );

      case "checkbox": {
        const selected = Array.isArray(value) ? value : [];
        return (
          <div role="group" aria-label={label} className="space-y-1.5">
            {options.map((option) => (
              <label key={option.value} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  value={option.value}
                  checked={selected.includes(option.value)}
                  onChange={(e) =>
                    onChange(
                      e.target.checked
                        ? [...selected, option.value]
                        : selected.filter((v) => v !== option.value),
                    )
                  }
                />
                {option.label ?? option.value}
              </label>
            ))}
          </div>
        );
      }

      default:
        return (
          <input
            id={fieldId}
            className={inputClass}
            type={field.sensitive ? "password" : "text"}
            value={(value as string) ?? ""}
            maxLength={field.max_length}
            autoComplete={field.sensitive ? "off" : undefined}
            onChange={(e) => onChange(e.target.value)}
          />
        );
    }
  }
}
