import { useState } from "react";
import { ConditionEditor } from "./ConditionEditor";
import type { FieldDefinition, FieldType, Rule } from "@/lib/types";
import { Badge, Button, Labelled, controlClass, inputClass } from "@/components/ui";

const TYPES: Array<{ value: FieldType; label: string }> = [
  { value: "text", label: "Short text" },
  { value: "textarea", label: "Long text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "dropdown", label: "Dropdown" },
  { value: "radio", label: "Single choice" },
  { value: "checkbox", label: "Multiple choice" },
  { value: "boolean", label: "Yes / no" },
  { value: "file", label: "File upload" },
  { value: "display", label: "Static text" },
];

const CHOICE_TYPES = new Set<FieldType>(["dropdown", "radio", "checkbox"]);

interface Props {
  fieldId: string;
  field: FieldDefinition;
  candidates: Array<{ id: string; definition: FieldDefinition }>;
  onChange: (field: FieldDefinition) => void;
  onRemove: () => void;
  defaultOpen?: boolean;
}


/**
 * A rule with no conditions means "no condition", which the schema spells as
 * an absent key. The editor emits the empty group as-is, because what that
 * means differs by site: absent `visible` is visible, absent `required` is
 * not required.
 */
function orAbsent(rule: Rule): Rule | undefined {
  if (rule === true) return undefined;
  const group = rule as { all?: unknown[]; any?: unknown[] };
  const leaves = group?.all ?? group?.any;
  return Array.isArray(leaves) && leaves.length === 0 ? undefined : rule;
}

export function FieldEditor({
  fieldId,
  field,
  candidates,
  onChange,
  onRemove,
  defaultOpen = false,
}: Props) {
  const isChoice = CHOICE_TYPES.has(field.type);
  const [open, setOpen] = useState(defaultOpen);

  function patch(changes: Partial<FieldDefinition>) {
    onChange({ ...field, ...changes });
  }

  // Two different rules can both be conditional, so they cannot both just
  // say "conditional" -- that is what the badges read before.
  const conditionallyShown = field.visible !== undefined && field.visible !== true;
  const required =
    field.required === true
      ? { tone: "danger" as const, text: "required" }
      : field.required
        ? { tone: "warn" as const, text: "required when…" }
        : null;

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface shadow-card">
      {/* A one-line summary when closed, so the shape of a survey is legible
          without expanding every question. */}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left transition-colors hover:bg-raised"
      >
        <svg
          width="13"
          height="13"
          viewBox="0 0 16 16"
          aria-hidden
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          className={`shrink-0 text-faint transition-transform ${open ? "rotate-90" : ""}`}
        >
          <path d="M6 3.5 10.5 8 6 12.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {field.label || field.key || "Untitled question"}
        </span>
        <Badge>{field.type}</Badge>
        {required && <Badge tone={required.tone}>{required.text}</Badge>}
        {conditionallyShown && <Badge tone="accent">shown when…</Badge>}
        {field.sensitive && <Badge tone="warn">sensitive</Badge>}
      </button>

      {!open ? null : (
    <div className="space-y-4 border-t border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-3">
          <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
            <Labelled label="Question" htmlFor={`${fieldId}-label`}>
              <input
                id={`${fieldId}-label`}
                className={inputClass}
                value={field.label ?? ""}
                onChange={(e) => patch({ label: e.target.value })}
              />
            </Labelled>

            <Labelled label="Type" htmlFor={`${fieldId}-type`}>
              <select
                id={`${fieldId}-type`}
                className={inputClass}
                value={field.type}
                onChange={(e) => {
                  const type = e.target.value as FieldType;
                  patch({
                    type,
                    // Choice fields must carry options or publish fails, so
                    // switching into one seeds a starter pair.
                    options: CHOICE_TYPES.has(type)
                      ? (field.options ?? [{ value: "a", label: "Option A" }])
                      : undefined,
                  });
                }}
              >
                {TYPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Labelled>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Labelled label="Key" hint="Export column name" htmlFor={`${fieldId}-key`}>
              <input
                id={`${fieldId}-key`}
                className={inputClass}
                value={field.key ?? ""}
                onChange={(e) => patch({ key: e.target.value })}
              />
            </Labelled>

            {field.type === "number" && (
              <>
                <Labelled label="Minimum" htmlFor={`${fieldId}-min`}>
                  <input
                    id={`${fieldId}-min`}
                    type="number"
                    className={inputClass}
                    value={field.min ?? ""}
                    onChange={(e) =>
                      patch({ min: e.target.value === "" ? undefined : Number(e.target.value) })
                    }
                  />
                </Labelled>
                <Labelled label="Maximum" htmlFor={`${fieldId}-max`}>
                  <input
                    id={`${fieldId}-max`}
                    type="number"
                    className={inputClass}
                    value={field.max ?? ""}
                    onChange={(e) =>
                      patch({ max: e.target.value === "" ? undefined : Number(e.target.value) })
                    }
                  />
                </Labelled>
              </>
            )}

            {(field.type === "text" || field.type === "textarea") && (
              <Labelled label="Max length" htmlFor={`${fieldId}-len`}>
                <input
                  id={`${fieldId}-len`}
                  type="number"
                  className={inputClass}
                  value={field.max_length ?? ""}
                  onChange={(e) =>
                    patch({
                      max_length: e.target.value === "" ? undefined : Number(e.target.value),
                    })
                  }
                />
              </Labelled>
            )}
          </div>
        </div>

        <Button variant="ghost" size="sm" onClick={onRemove}>
          Remove
        </Button>
      </div>

      {isChoice && <OptionsEditor field={field} candidates={candidates} onChange={onChange} />}

      {field.type !== "display" && (
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={Boolean(field.sensitive)}
            onChange={(e) => patch({ sensitive: e.target.checked || undefined })}
          />
          <span>
            Sensitive
            <span className="ml-2 text-xs text-muted">
              {field.type === "file"
                ? "Downloading the file needs the PII permission."
                : "Encrypted at rest. It cannot appear in any distribution — results will report how many people answered and nothing more."}
            </span>
          </span>
        </label>
      )}

      <div className="space-y-3 border-t border-line pt-3">
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">
            Visible
          </p>
          <ConditionEditor
            rule={field.visible ?? true}
            candidates={candidates}
            emptyLabel="Always shown."
            onChange={(rule) => patch({ visible: orAbsent(rule) })}
          />
        </div>

        {field.type !== "display" && (
          <div>
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">
              Required
            </p>
            <RequiredEditor field={field} candidates={candidates} onChange={patch} />
          </div>
        )}
      </div>
    </div>
      )}
    </div>
  );
}

function RequiredEditor({
  field,
  candidates,
  onChange,
}: {
  field: FieldDefinition;
  candidates: Props["candidates"];
  onChange: (changes: Partial<FieldDefinition>) => void;
}) {
  const mode =
    field.required === true ? "always" : field.required ? "conditional" : "never";

  return (
    <div className="space-y-2">
      <div className="flex gap-3 text-sm">
        {(["never", "always", "conditional"] as const).map((option) => (
          <label key={option} className="flex items-center gap-1.5">
            <input
              type="radio"
              name={`${field.key}-required`}
              checked={mode === option}
              onChange={() =>
                onChange({
                  required:
                    option === "always" ? true : option === "never" ? undefined : { all: [] },
                })
              }
            />
            {option}
          </label>
        ))}
      </div>

      {mode === "conditional" && (
        <ConditionEditor
          rule={field.required as Rule}
          candidates={candidates}
          emptyLabel="Required when…"
          onChange={(rule) => onChange({ required: orAbsent(rule) })}
        />
      )}
      {mode === "conditional" && (
        <p className="text-xs text-muted">
          A hidden field is never required, whatever this says — otherwise it
          would block submission with an error about something invisible.
        </p>
      )}
    </div>
  );
}

function OptionsEditor({
  field,
  candidates,
  onChange,
}: {
  field: FieldDefinition;
  candidates: Props["candidates"];
  onChange: (field: FieldDefinition) => void;
}) {
  const options = field.options ?? [];
  const [showing, setShowing] = useState<number | null>(null);

  function update(index: number, patch: Partial<(typeof options)[number]>) {
    onChange({
      ...field,
      options: options.map((option, i) => (i === index ? { ...option, ...patch } : option)),
    });
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">Options</p>

      {options.map((option, index) => {
        const conditional = option.when !== undefined && option.when !== true;
        const open = conditional || showing === index;
        return (
          <div key={index} className="rounded-lg border border-line bg-surface p-2">
            {/* One row per option. controlClass rather than inputClass: the
                latter carries w-full, which beats a width set alongside it
                and stacked every option into two full-width inputs. */}
            <div className="flex items-center gap-2">
              <input
                aria-label="Option value"
                className={`${controlClass} w-28 shrink-0 font-mono text-xs`}
                placeholder="value"
                value={option.value}
                onChange={(e) => update(index, { value: e.target.value })}
              />
              <input
                aria-label="Option label"
                className={`${controlClass} min-w-0 flex-1`}
                placeholder="label shown to the respondent"
                value={option.label ?? ""}
                onChange={(e) => update(index, { label: e.target.value })}
              />
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Condition for option ${index + 1}`}
                title="Show this option only when…"
                onClick={() => setShowing(open ? null : index)}
              >
                {conditional ? <Badge tone="accent">when</Badge> : "when…"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Remove option ${index + 1}`}
                onClick={() =>
                  onChange({ ...field, options: options.filter((_, i) => i !== index) })
                }
              >
                ×
              </Button>
            </div>

            {open && (
              <div className="mt-2">
                {/* Option-level conditions are how an answer in one section
                    narrows the choices in another. */}
                <ConditionEditor
                  rule={option.when ?? true}
                  candidates={candidates}
                  emptyLabel="Always offered."
                  onChange={(rule) => update(index, { when: orAbsent(rule) })}
                />
              </div>
            )}
          </div>
        );
      })}

      <Button
        size="sm"
        variant="secondary"
        onClick={() =>
          onChange({
            ...field,
            options: [...options, { value: `option-${options.length + 1}`, label: "" }],
          })
        }
      >
        Add option
      </Button>
    </div>
  );
}
