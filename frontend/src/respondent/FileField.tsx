/**
 * A file answer, in two phases.
 *
 * The upload happens as soon as the file is chosen, not at submit: the
 * server returns an id and that id becomes the answer. So a respondent can
 * close the tab after choosing a file and the file is still there when they
 * return, and a retry of the submit does not resend the bytes.
 */

import { useRef, useState } from "react";

import { ApiError, respondent } from "@/lib/api";
import { Button, Labelled } from "@/components/ui";
import type { AnswerValue, FieldDefinition, SubmissionFile } from "@/lib/types";

interface Props {
  fieldId: string;
  field: FieldDefinition;
  value: AnswerValue;
  required: boolean;
  error?: string;
  submissionId: string;
  resumeToken: string;
  onChange: (value: AnswerValue) => void;
}

export function FileField({
  fieldId,
  field,
  value,
  required,
  error,
  submissionId,
  resumeToken,
  onChange,
}: Props) {
  const [uploaded, setUploaded] = useState<SubmissionFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function onPick(file: File) {
    setBusy(true);
    setUploadError(null);
    try {
      const record = await respondent.upload(submissionId, resumeToken, fieldId, file);
      setUploaded(record);
      // The id is the answer. Setting it here puts the file through the same
      // autosave path as every other answer.
      onChange(record.id);
    } catch (caught) {
      // The server states exactly why — wrong type, too large, wrong field —
      // and that is more useful than a generic failure.
      setUploadError(
        caught instanceof ApiError
          ? (caught.forField("file") ?? caught.summary)
          : "Could not upload that file.",
      );
      if (input.current) input.current.value = "";
    } finally {
      setBusy(false);
    }
  }

  return (
    <Labelled
      label={field.label ?? field.key ?? "File"}
      hint={
        field.sensitive ? "Only authorised staff can open it." : field.help
      }
      error={error ?? uploadError ?? undefined}
      required={required}
      htmlFor={fieldId}
    >
      {uploaded || value ? (
        <div className="flex items-center gap-3 rounded-lg border border-line px-3 py-2 text-sm">
          <span className="flex-1 truncate">
            {uploaded?.original_name ?? "File attached"}
          </span>
          {uploaded && (
            <span className="text-xs text-muted">{formatSize(uploaded.size_bytes)}</span>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setUploaded(null);
              onChange(null);
              if (input.current) input.current.value = "";
            }}
          >
            Replace
          </Button>
        </div>
      ) : (
        <input
          id={fieldId}
          ref={input}
          type="file"
          disabled={busy}
          className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-accent-soft file:px-3 file:py-1.5 file:text-accent"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void onPick(file);
          }}
        />
      )}
      {busy && <p className="text-xs text-muted">Uploading…</p>}
    </Labelled>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
