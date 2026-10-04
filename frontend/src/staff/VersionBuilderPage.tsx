import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { FieldEditor } from "./FieldEditor";
import { ApiError, staff } from "@/lib/api";
import { keys, usePublish, useSections, useVersion } from "@/lib/queries";
import type { FieldDefinition, Section } from "@/lib/types";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  MoveButtons,
  SaveState,
  Spinner,
  StatusBadge,
} from "@/components/ui";

export function VersionBuilderPage() {
  const { versionId } = useParams();
  const client = useQueryClient();
  const version = useVersion(versionId);
  const sections = useSections(versionId);
  const publish = usePublish(versionId as string, version.data?.survey);

  const isDraft = version.data?.status === "draft";

  // Each section's unsaved content, so a condition editor in one section can
  // reference a field just added to another.
  const [live, setLive] = useState<Record<string, Record<string, FieldDefinition>>>({});

  const createSection = useMutation({
    mutationFn: () =>
      staff.createSection(versionId as string, {
        key: `s${(sections.data?.length ?? 0) + 1}`,
        title: `Section ${(sections.data?.length ?? 0) + 1}`,
        order: (sections.data?.length ?? 0) + 1,
        content: {},
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: keys.sections(versionId as string) }),
  });

  if (version.isPending || sections.isPending) return <Spinner />;
  if (version.error) return <ErrorBanner message={String(version.error)} />;

  const ordered = [...(sections.data ?? [])].sort((a, b) => a.order - b.order);

  // Fields a condition may reference: everything defined in an earlier
  // section, plus earlier fields in the same one. This is what keeps the
  // dependency graph acyclic, which the backend verifies at publish.
  //
  // Read from `live` rather than from the query cache, so a field added a
  // moment ago is immediately referenceable. Before this, a new field only
  // became selectable after its section round-tripped to the server, which
  // made the condition editor look broken.
  function candidatesBefore(sectionIndex: number, fieldId?: string) {
    const result: Array<{ id: string; definition: FieldDefinition }> = [];
    ordered.forEach((section, index) => {
      if (index > sectionIndex) return;
      const content = live[section.id] ?? section.content ?? {};
      for (const [id, definition] of sortedFields(content)) {
        if (index === sectionIndex && fieldId && id === fieldId) return;
        result.push({ id, definition });
      }
    });
    return result;
  }

  function reorderSections(index: number, delta: number) {
    const target = ordered[index + delta];
    const current = ordered[index];
    if (!target || !current) return;
    void Promise.all([
      staff.updateSection(current.id, { order: target.order }),
      staff.updateSection(target.id, { order: current.order }),
    ]).then(() => client.invalidateQueries({ queryKey: keys.sections(versionId as string) }));
  }

  const publishError = publish.error instanceof ApiError ? publish.error : null;
  const publishErrors = publishError
    ? Object.values(publishError.errors).flatMap((value) =>
        Array.isArray(value) ? value : [String(value)],
      )
    : [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              Version {version.data?.version_number}
            </h1>
            <StatusBadge status={version.data?.status ?? ""} />
          </div>
          <p className="mt-1 text-sm text-muted">
            {isDraft
              ? "Edit freely. Publishing validates the whole document and freezes it."
              : "Published and immutable. Create a new draft to make changes."}
          </p>
        </div>

        {isDraft && (
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={() => createSection.mutate()}
              disabled={createSection.isPending}
            >
              Add section
            </Button>
            <Button onClick={() => publish.mutate()} disabled={publish.isPending}>
              {publish.isPending ? "Publishing…" : "Publish"}
            </Button>
          </div>
        )}
      </div>

      {publishErrors.length > 0 && (
        <ErrorBanner
          title="This version cannot be published yet"
          message="Every problem found is listed, so they can be fixed in one pass."
          details={publishErrors}
        />
      )}

      {publish.isSuccess && (
        <div className="rounded-lg border border-ok/30 bg-ok-soft p-3 text-sm text-ok">
          Published. This version is now frozen and open to respondents.
        </div>
      )}

      {!ordered.length ? (
        <EmptyState
          title="No sections yet"
          body="A survey is organised into sections. Each holds fields, and a section can be shown conditionally."
          action={
            isDraft ? (
              <Button onClick={() => createSection.mutate()}>Add the first section</Button>
            ) : undefined
          }
        />
      ) : (
        <div className="space-y-4">
          {ordered.map((section, index) => (
            <SectionCard
              key={section.id}
              section={section}
              index={index}
              total={ordered.length}
              editable={isDraft}
              fieldCandidates={(fieldId) => candidatesBefore(index, fieldId)}
              versionId={versionId as string}
              onContentChange={(content) =>
                setLive((previous) => ({ ...previous, [section.id]: content }))
              }
              onMove={(delta) => reorderSections(index, delta)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Entries in the author's order. jsonb hands the keys back sorted, so the
 *  position has to come from the field itself; the id breaks ties so two
 *  fields sharing an order never swap between renders. */
function sortedFields(
  content: Record<string, FieldDefinition> | undefined,
): Array<[string, FieldDefinition]> {
  return Object.entries(content ?? {}).sort(
    ([aId, a], [bId, b]) => (a.order ?? 0) - (b.order ?? 0) || aId.localeCompare(bId),
  );
}

function SectionCard({
  section,
  index,
  total,
  editable,
  fieldCandidates,
  versionId,
  onContentChange,
  onMove,
}: {
  section: Section;
  index: number;
  total: number;
  editable: boolean;
  fieldCandidates: (fieldId?: string) => Array<{ id: string; definition: FieldDefinition }>;
  versionId: string;
  onContentChange: (content: Record<string, FieldDefinition>) => void;
  onMove: (delta: number) => void;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState(section);
  const [dirty, setDirty] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [justAdded, setJustAdded] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const save = useMutation({
    mutationFn: (next: Section) =>
      staff.updateSection(section.id, {
        key: next.key,
        title: next.title,
        order: next.order,
        content: next.content,
      }),
    onSuccess: () => {
      setDirty(false);
      client.invalidateQueries({ queryKey: keys.sections(versionId) });
    },
  });

  const remove = useMutation({
    mutationFn: () => staff.deleteSection(section.id),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.sections(versionId) }),
  });

  // Autosave rather than a Save button. The builder is a form over a form:
  // an explicit save step meant a field had to round-trip before another
  // section could reference it, which made conditions look broken.
  useEffect(() => {
    if (!dirty || !editable) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => save.mutate(draft), 700);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, dirty, editable]);

  function patch(changes: Partial<Section>) {
    setDraft((previous) => {
      const next = { ...previous, ...changes };
      if (changes.content) onContentChange(changes.content);
      return next;
    });
    setDirty(true);
  }

  function setField(fieldId: string, definition: FieldDefinition | null) {
    const content = { ...draft.content };
    if (definition === null) delete content[fieldId];
    else content[fieldId] = definition;
    patch({ content });
  }

  /** Reordering rewrites each field's `order`, because key order does not
   *  survive the server: `content` is a jsonb column and jsonb sorts object
   *  keys. Writing positions back on every move also repairs a section
   *  authored before `order` existed, where every field reads 0. */
  function moveField(fieldId: string, delta: number) {
    const entries = sortedFields(draft.content);
    const from = entries.findIndex(([id]) => id === fieldId);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= entries.length) return;

    const next = [...entries];
    [next[from], next[to]] = [next[to], next[from]];
    patch({
      content: Object.fromEntries(
        next.map(([id, definition], position) => [id, { ...definition, order: position }]),
      ),
    });
  }

  const fields = sortedFields(draft.content);
  const error = save.error instanceof ApiError ? save.error : null;

  return (
    <Card className="overflow-hidden">
      {/* Header band: the visual break between one section and the next. */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-4 py-3">
        {editable && (
          <MoveButtons
            label={`section ${index + 1}`}
            canUp={index > 0}
            canDown={index < total - 1}
            onUp={() => onMove(-1)}
            onDown={() => onMove(1)}
          />
        )}

        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent ring-1 ring-accent-line/50">
          {index + 1}
        </span>

        <input
          aria-label="Section title"
          className="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-base font-semibold transition-colors hover:border-line focus:border-accent focus:bg-surface focus:outline-none"
          value={draft.title}
          disabled={!editable}
          onChange={(e) => patch({ title: e.target.value })}
        />

        <input
          aria-label="Section key"
          className="w-28 shrink-0 rounded-lg border border-transparent bg-transparent px-2 py-1 font-mono text-xs text-muted transition-colors hover:border-line focus:border-accent focus:bg-surface focus:outline-none"
          value={draft.key}
          disabled={!editable}
          onChange={(e) => patch({ key: e.target.value })}
        />

        <span className="shrink-0 text-xs text-muted">
          {fields.length} field{fields.length === 1 ? "" : "s"}
        </span>

        {editable && (
          <SaveState saving={save.isPending} dirty={dirty} error={error?.forField("key")} />
        )}

        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? "Expand section" : "Collapse section"}
          aria-expanded={!collapsed}
          className="rounded-md p-1 text-muted transition-colors hover:bg-line-soft hover:text-ink"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            aria-hidden
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            className={`transition-transform ${collapsed ? "" : "rotate-180"}`}
          >
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        {editable && (
          <Button size="sm" variant="ghost" onClick={() => remove.mutate()}>
            Delete
          </Button>
        )}
      </div>

      {error && !error.forField("key") && (
        <p role="alert" className="border-b border-line bg-danger-soft px-4 py-2 text-sm text-danger">
          {error.summary}
        </p>
      )}

      {!collapsed && (
        <div className="space-y-3 bg-page/60 p-4">
          {fields.length === 0 && (
            <p className="py-2 text-center text-sm text-muted">
              No questions in this section yet.
            </p>
          )}

          {fields.map(([fieldId, definition], position) => (
            <div key={fieldId} className="flex items-start gap-2">
              {editable && (
                <div className="shrink-0 pt-1">
                  <MoveButtons
                    index={position + 1}
                    label={`question ${position + 1}`}
                    canUp={position > 0}
                    canDown={position < fields.length - 1}
                    onUp={() => moveField(fieldId, -1)}
                    onDown={() => moveField(fieldId, 1)}
                  />
                </div>
              )}
              <div className="min-w-0 flex-1">
                <FieldEditor
                  fieldId={fieldId}
                  field={definition}
                  candidates={fieldCandidates(fieldId)}
                  defaultOpen={fieldId === justAdded}
                  onChange={(next) => setField(fieldId, next)}
                  onRemove={() => setField(fieldId, null)}
                />
              </div>
            </div>
          ))}

          {editable && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() =>
                // The client mints the field id, so a whole survey -- fields,
                // conditions and option filters all cross-referencing -- can
                // be authored and saved in one payload. The server validates
                // every id at publish.
                {
                  const id = crypto.randomUUID();
                  setJustAdded(id);
                  setField(id, {
                    type: "text",
                    key: `q${fields.length + 1}`,
                    label: "New question",
                    order: fields.length,
                  });
                }
              }
            >
              Add question
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
