import { FileUp, UploadCloud, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { MiddleTruncate } from "@/components/MiddleTruncate";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";
import {
  SOURCE_TYPES,
  SOURCE_TYPE_LABELS,
  inferSourceType,
} from "@/lib/sourceType";
import type { ContentItem, SourceType } from "@/lib/types";
import { MAX_UPLOAD_BYTES, runUpload } from "@/lib/upload";
import { formatBytes } from "@/lib/utils";

interface UploadTask {
  id: string;
  file: File;
  /** The resolved type sent to the backend; `null` until the owner picks one. */
  sourceType: SourceType | null;
  /** Whether inference picked the type (vs. an explicit owner override). */
  inferred: boolean;
  status: "staged" | "uploading";
  progress: number;
}

let taskSeq = 0;

function stageFile(file: File): UploadTask {
  const inferred = inferSourceType(file.name, file.type);
  return {
    id: `task-${++taskSeq}`,
    file,
    sourceType: inferred,
    inferred: inferred !== null,
    status: "staged",
    progress: 0,
  };
}

/**
 * The dashboard upload surface: a drag/drop + file-picker dropzone that stages
 * files, lets the owner confirm or override the inferred source type, then runs
 * presign → direct-to-S3 (XHR, progress bar) → finalize for each. Finalized
 * items are handed to {@link onUploaded} so the library prepends them; failures
 * surface the structured error `code` + `message` as a toast (no polling).
 */
export function UploadDropzone({
  onUploaded,
}: {
  onUploaded: (item: ContentItem) => void;
}) {
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const addFiles = useCallback((files: FileList | File[]) => {
    const staged = Array.from(files).map(stageFile);
    if (staged.length > 0) setTasks((prev) => [...prev, ...staged]);
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDragging(false);
      if (event.dataTransfer?.files?.length) {
        addFiles(event.dataTransfer.files);
      }
    },
    [addFiles],
  );

  const setTaskType = useCallback((id: string, sourceType: SourceType) => {
    setTasks((prev) =>
      prev.map((t) =>
        t.id === id ? { ...t, sourceType, inferred: false } : t,
      ),
    );
  }, []);

  const removeTask = useCallback((id: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const patchTask = useCallback((id: string, patch: Partial<UploadTask>) => {
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  }, []);

  const runOne = useCallback(
    async (task: UploadTask) => {
      if (!task.sourceType) return;
      patchTask(task.id, { status: "uploading", progress: 0 });
      try {
        const item = await runUpload(task.file, task.sourceType, (p) => {
          const pct = p.total > 0 ? Math.round((p.loaded / p.total) * 100) : 0;
          patchTask(task.id, { progress: pct });
        });
        removeTask(task.id);
        onUploaded(item);
        toast({
          variant: "success",
          title: `Uploaded ${item.original_filename}`,
          description: "It is available at its private link.",
        });
      } catch (err) {
        patchTask(task.id, { status: "staged", progress: 0 });
        const apiError = err instanceof ApiError ? err : null;
        toast({
          variant: "error",
          title: `Upload failed: ${task.file.name}`,
          description:
            apiError?.message ??
            (err instanceof Error ? err.message : "Something went wrong."),
          code: apiError?.code,
        });
      }
    },
    [onUploaded, patchTask, removeTask, toast],
  );

  const uploadAll = useCallback(() => {
    for (const task of tasks) {
      if (
        task.status === "staged" &&
        task.sourceType &&
        task.file.size <= MAX_UPLOAD_BYTES
      ) {
        void runOne(task);
      }
    }
  }, [tasks, runOne]);

  const readyCount = tasks.filter(
    (t) =>
      t.status === "staged" &&
      t.sourceType !== null &&
      t.file.size <= MAX_UPLOAD_BYTES,
  ).length;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload</CardTitle>
        <CardDescription>
          Drag &amp; drop or pick HTML / Markdown files. Override the inferred
          type if needed.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload files: drag and drop or click to choose"
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-none border-2 border-dashed p-8 text-center transition-colors ${
            dragging
              ? "border-retro-accent bg-retro-accent-weak"
              : "border-retro-line/60 hover:border-retro-line"
          }`}
        >
          <UploadCloud className="h-8 w-8 text-retro-faint" aria-hidden />
          <div className="text-sm font-medium">
            Drop files here, or click to choose
          </div>
          <div className="text-xs text-retro-muted">
            HTML or Markdown, up to {MAX_UPLOAD_BYTES / (1024 * 1024)} MB each
          </div>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".html,.htm,.md,.markdown,.txt,text/html,text/markdown"
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.length) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {tasks.length > 0 && (
          <ul className="flex flex-col gap-2">
            {tasks.map((task) => {
              const oversized = task.file.size > MAX_UPLOAD_BYTES;
              return (
                <li
                  key={task.id}
                  className="flex flex-col gap-2 rounded-none border border-retro-line bg-retro-surface p-3 shadow-hard"
                >
                  <div className="flex items-center gap-3">
                    <FileUp
                      className="h-4 w-4 shrink-0 text-retro-faint"
                      aria-hidden
                    />
                    <div className="min-w-0 flex-1">
                      <MiddleTruncate
                        name={task.file.name}
                        className="text-sm font-medium"
                      />
                      <div className="text-xs text-retro-muted">
                        {formatBytes(task.file.size)}
                      </div>
                    </div>

                    {task.status === "uploading" ? (
                      <StatusBadge status="uploaded" />
                    ) : (
                      <>
                        <label className="sr-only" htmlFor={`type-${task.id}`}>
                          Source type for {task.file.name}
                        </label>
                        <Select
                          id={`type-${task.id}`}
                          value={task.sourceType ?? ""}
                          onChange={(e) =>
                            setTaskType(task.id, e.target.value as SourceType)
                          }
                          aria-invalid={task.sourceType === null}
                        >
                          {task.sourceType === null && (
                            <option value="" disabled>
                              Choose type…
                            </option>
                          )}
                          {SOURCE_TYPES.map((type) => (
                            <option key={type} value={type}>
                              {SOURCE_TYPE_LABELS[type]}
                              {task.inferred && task.sourceType === type
                                ? " (inferred)"
                                : ""}
                            </option>
                          ))}
                        </Select>
                        <button
                          type="button"
                          onClick={() => removeTask(task.id)}
                          aria-label={`Remove ${task.file.name}`}
                          className="text-retro-faint hover:text-retro-ink"
                        >
                          <X className="h-4 w-4" aria-hidden />
                        </button>
                      </>
                    )}
                  </div>

                  {task.status === "uploading" && (
                    <Progress value={task.progress} />
                  )}
                  {oversized && task.status === "staged" && (
                    <div className="text-xs font-medium text-retro-danger">
                      Too large — exceeds the{" "}
                      {MAX_UPLOAD_BYTES / (1024 * 1024)} MB limit.
                    </div>
                  )}
                  {task.sourceType === null && task.status === "staged" && (
                    <div className="text-xs font-medium text-retro-danger">
                      Couldn&apos;t infer a type — choose one to upload.
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {tasks.length > 0 && (
          <div className="grid grid-cols-2 gap-3">
            <Button
              onClick={uploadAll}
              disabled={readyCount === 0}
              className="w-full"
            >
              <UploadCloud className="h-4 w-4" aria-hidden />
              Upload {readyCount > 0 ? `${readyCount} ` : ""}
              file{readyCount === 1 ? "" : "s"}
            </Button>
            <Button
              variant="outline"
              onClick={() => setTasks([])}
              disabled={tasks.some((t) => t.status === "uploading")}
              className="w-full"
            >
              Clear
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
