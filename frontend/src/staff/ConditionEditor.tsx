/**
 * Builds a v1 condition: a flat all/any group of {field, op, value} leaves.
 *
 * Operators are filtered to those the backend accepts for the referenced
 * field's type, and the value control matches that type. The backend
 * validates all of this again at publish -- the point here is that an author
 * cannot build an invalid rule in the first place, rather than discovering
 * it when publishing fails.
 */

import { OP_LABEL, allowedOps } from "@/lib/operators";
import type { FieldDefinition, Leaf, Operator, Rule } from "@/lib/types";
import { Button, controlClass, inputClass } from "@/components/ui";

interface Props {
  rule: Rule;
  /** Fields that may be referenced: those evaluated before this one. */
  candidates: Array<{ id: string; definition: FieldDefinition }>;
  onChange: (rule: Rule) => void;
  emptyLabel: string;
}

export function ConditionEditor({ rule, candidates, onChange, emptyLabel }: Props) {
  const isGroup = rule !== null && typeof rule === "object";
  const mode: "all" | "any" = isGroup && "any" in rule ? "any" : "all";
  const leaves: Leaf[] = isGroup ? ((rule as { all?: Leaf[]; any?: Leaf[] })[mode] ?? []) : [];

  const usable = candidates.filter((c) => allowedOps(c.definition.type).length > 0);

  // An empty group is emitted as an empty group. It used to be collapsed to
  // `true`, which is right for visibility -- an absent rule means visible --
  // and wrong for `required`, where absent means NOT required. Changing the
  // match mode, or removing the last condition, flipped the required editor
  // back to "always". What "no conditions" means is the caller's decision.
  function emit(nextMode: "all" | "any", nextLeaves: Leaf[]) {
    onChange({ [nextMode]: nextLeaves } as Rule);
  }

  if (!isGroup) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted">{emptyLabel}</span>
        <Button
          size="sm"
          variant="secondary"
          disabled={usable.length === 0}
          onClick={() =>
            emit("all", [{ field: usable[0].id, op: allowedOps(usable[0].definition.type)[0] }])
          }
        >
          Add condition
        </Button>
        {usable.length === 0 && (
          <span className="text-xs text-muted">
            Nothing earlier to depend on yet.
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2.5 rounded-xl border border-line bg-raised p-3.5">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted">Show when</span>
        <select
          className={controlClass}
          value={mode}
          onChange={(e) => emit(e.target.value as "all" | "any", leaves)}
          aria-label="Match mode"
        >
          <option value="all">all</option>
          <option value="any">any</option>
        </select>
        <span className="text-muted">of these hold:</span>
      </div>

      {leaves.map((leaf, index) => {
        const referenced = candidates.find((c) => c.id === leaf.field);
        const ops = allowedOps(referenced?.definition.type);

        function update(patch: Partial<Leaf>) {
          const next = leaves.map((item, i) => (i === index ? { ...item, ...patch } : item));
          emit(mode, next);
        }

        return (
          <div key={index} className="flex flex-wrap items-center gap-2">
            <select
              className={controlClass}
              value={leaf.field}
              aria-label="Field"
              onChange={(e) => {
                const next = candidates.find((c) => c.id === e.target.value);
                const nextOps = allowedOps(next?.definition.type);
                // Switching field can invalidate the operator, so reset both
                // it and the value rather than leaving an illegal pair.
                update({ field: e.target.value, op: nextOps[0], value: undefined });
              }}
            >
              {usable.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.definition.label ?? candidate.definition.key ?? candidate.id}
                </option>
              ))}
            </select>

            <select
              className={controlClass}
              value={leaf.op}
              aria-label="Operator"
              onChange={(e) => update({ op: e.target.value as Operator })}
            >
              {ops.map((op) => (
                <option key={op} value={op}>
                  {OP_LABEL[op]}
                </option>
              ))}
            </select>

            {leaf.op !== "answered" && (
              <ValueInput
                definition={referenced?.definition}
                value={leaf.value}
                onChange={(value) => update({ value })}
              />
            )}

            <Button
              size="sm"
              variant="ghost"
              aria-label="Remove condition"
              onClick={() => emit(mode, leaves.filter((_, i) => i !== index))}
            >
              Remove
            </Button>
          </div>
        );
      })}

      <Button
        size="sm"
        variant="secondary"
        disabled={usable.length === 0}
        onClick={() =>
          emit(mode, [
            ...leaves,
            { field: usable[0].id, op: allowedOps(usable[0].definition.type)[0] },
          ])
        }
      >
        Add another
      </Button>
    </div>
  );
}

function ValueInput({
  definition,
  value,
  onChange,
}: {
  definition: FieldDefinition | undefined;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const type = definition?.type;

  // Choice fields offer their declared options: the backend rejects an
  // operand that is not one of them, so free text would only produce a
  // publish-time error.
  if (type === "dropdown" || type === "radio" || type === "checkbox") {
    return (
      <select
        className={controlClass}
        value={(value as string) ?? ""}
        aria-label="Value"
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Choose…</option>
        {(definition?.options ?? []).map((option) => (
          <option key={option.value} value={option.value}>
            {option.label ?? option.value}
          </option>
        ))}
      </select>
    );
  }

  if (type === "boolean") {
    return (
      <select
        className={controlClass}
        value={value === true ? "true" : value === false ? "false" : ""}
        aria-label="Value"
        onChange={(e) => onChange(e.target.value === "true")}
      >
        <option value="">Choose…</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }

  if (type === "number") {
    return (
      <input
        type="number"
        aria-label="Value"
        className={`${inputClass} w-28 py-1`}
        value={value === undefined || value === null ? "" : String(value)}
        // Sent as a number, not a string. A string operand against a number
        // field is rejected at publish, and it is the mismatch that would
        // make the browser and the server disagree about visibility.
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
    );
  }

  return (
    <input
      type={type === "date" ? "date" : "text"}
      aria-label="Value"
      className={`${inputClass} w-40 py-1`}
      value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
