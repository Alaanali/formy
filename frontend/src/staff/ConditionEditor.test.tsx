/**
 * The editor's job is to make an invalid rule unbuildable, so the author
 * never discovers the problem at publish time.
 */

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConditionEditor } from "./ConditionEditor";
import { allowedOps } from "@/lib/operators";
import type { FieldDefinition } from "@/lib/types";

const CANDIDATES: Array<{ id: string; definition: FieldDefinition }> = [
  {
    id: "f-country",
    definition: {
      type: "dropdown",
      label: "Country",
      options: [{ value: "sa", label: "Saudi Arabia" }, { value: "eg", label: "Egypt" }],
    },
  },
  { id: "f-age", definition: { type: "number", label: "Age" } },
];

describe("operator filtering", () => {
  it("offers only operators the backend accepts for that type", () => {
    // `gt` on a dropdown is meaningless and the backend rejects it at
    // publish, so it is never offered.
    expect(allowedOps("dropdown")).not.toContain("gt");
    expect(allowedOps("number")).toContain("gte");
    expect(allowedOps("text")).toContain("contains");
    expect(allowedOps("display")).toEqual([]);
  });

  it("shows only the legal operators for the selected field", async () => {
    render(
      <ConditionEditor
        rule={{ all: [{ field: "f-country", op: "eq", value: "sa" }] }}
        candidates={CANDIDATES}
        onChange={vi.fn()}
        emptyLabel="Always"
      />,
    );

    const operator = screen.getByLabelText("Operator") as HTMLSelectElement;
    const options = [...operator.options].map((option) => option.value);

    expect(options).toEqual(expect.arrayContaining(["eq", "ne", "answered"]));
    expect(options).not.toContain("gt");
  });
});

describe("value input", () => {
  it("offers declared options for a choice field instead of free text", () => {
    render(
      <ConditionEditor
        rule={{ all: [{ field: "f-country", op: "eq", value: "sa" }] }}
        candidates={CANDIDATES}
        onChange={vi.fn()}
        emptyLabel="Always"
      />,
    );

    const value = screen.getByLabelText("Value") as HTMLSelectElement;
    expect([...value.options].map((o) => o.value)).toEqual(["", "sa", "eg"]);
  });

  it("sends a number as a number, not a string", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <ConditionEditor
        rule={{ all: [{ field: "f-age", op: "gte" }] }}
        candidates={CANDIDATES}
        onChange={onChange}
        emptyLabel="Always"
      />,
    );

    await user.type(screen.getByLabelText("Value"), "21");

    // A string operand against a number field is what makes the browser and
    // the server disagree about visibility, so the backend rejects it.
    const last = onChange.mock.calls.at(-1)![0];
    expect(typeof last.all[0].value).toBe("number");
  });
});

describe("editing", () => {
  it("resets the operator when the referenced field changes type", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <ConditionEditor
        rule={{ all: [{ field: "f-age", op: "gte", value: 21 }] }}
        candidates={CANDIDATES}
        onChange={onChange}
        emptyLabel="Always"
      />,
    );

    await user.selectOptions(screen.getByLabelText("Field"), "f-country");

    // `gte` is illegal for a dropdown, so keeping it would build a rule the
    // backend refuses.
    const next = onChange.mock.calls.at(-1)![0];
    expect(next.all[0].op).not.toBe("gte");
    expect(allowedOps("dropdown")).toContain(next.all[0].op);
  });

  it("emits an empty group when the last leaf is removed", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <ConditionEditor
        rule={{ all: [{ field: "f-country", op: "eq", value: "sa" }] }}
        candidates={CANDIDATES}
        onChange={onChange}
        emptyLabel="Always"
      />,
    );

    await user.click(screen.getByRole("button", { name: /remove condition/i }));

    // Not `true`: the caller decides what no-conditions means, because an
    // absent `visible` is visible while an absent `required` is not required.
    expect(onChange).toHaveBeenCalledWith({ all: [] });
  });

  it("explains itself when there is nothing earlier to depend on", () => {
    render(
      <ConditionEditor rule={true} candidates={[]} onChange={vi.fn()} emptyLabel="Always" />,
    );

    expect(screen.getByText(/nothing earlier to depend on/i)).toBeInTheDocument();
  });
});

describe("an empty group must not become 'always'", () => {
  it("keeps the group when the match mode changes with no conditions yet", () => {
    // Picking "conditional" in the required editor seeds {all: []}. Changing
    // all/any before adding a condition emitted `true`, which the required
    // editor reads as "always required" -- so the radio jumped back.
    const onChange = vi.fn();
    render(
      <ConditionEditor
        rule={{ all: [] }}
        candidates={[CANDIDATES[0]]}
        emptyLabel="Required when…"
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Match mode"), { target: { value: "any" } });

    expect(onChange).toHaveBeenCalledWith({ any: [] });
  });

  it("keeps the group when the last condition is removed", () => {
    const onChange = vi.fn();
    render(
      <ConditionEditor
        rule={{ all: [{ field: CANDIDATES[0].id, op: "eq", value: "sa" }] }}
        candidates={[CANDIDATES[0]]}
        emptyLabel="Required when…"
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByLabelText("Remove condition"));

    expect(onChange).toHaveBeenCalledWith({ all: [] });
  });
});
