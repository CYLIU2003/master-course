// ── EditorDrawer ──────────────────────────────────────────────
// Slide-in panel from the right for editing records.
// Supports title, tabs, save/cancel actions, and unsaved warning.

import type { ReactNode } from "react";

interface EditorDrawerProps {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  onSave?: () => void;
  onDelete?: () => void;
  onDuplicate?: () => void;
  isDirty?: boolean;
  isSaving?: boolean;
  children: ReactNode;
  width?: string;
}

export function EditorDrawer({
  open,
  title,
  subtitle,
  onClose,
  onSave,
  onDelete,
  onDuplicate,
  isDirty = false,
  isSaving = false,
  children,
  width = "w-[480px]",
}: EditorDrawerProps) {
  if (!open) return null;

  const handleClose = () => {
    if (isDirty && !confirm("未保存の変更があります。閉じますか？")) return;
    onClose();
  };

  return (
    <div
      className={`${width} shrink-0 flex flex-col border-l border-border bg-surface-raised overflow-hidden`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-slate-800">
            {title}
          </h3>
          {subtitle && (
            <p className="truncate text-xs text-slate-400">{subtitle}</p>
          )}
        </div>
        <div className="ml-2 flex items-center gap-1">
          {isDirty && (
            <span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" title="未保存" />
          )}
          <button
            onClick={handleClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      {/* Body (scrollable) */}
      <div className="flex-1 overflow-y-auto p-4">{children}</div>

      {/* Footer actions */}
      <div className="flex items-center justify-between border-t border-border px-4 py-3">
        <div className="flex gap-2">
          {onDelete && (
            <button
              onClick={onDelete}
              className="rounded px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
            >
              削除
            </button>
          )}
          {onDuplicate && (
            <button
              onClick={onDuplicate}
              className="rounded px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
            >
              複製
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleClose}
            className="rounded px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
          >
            キャンセル
          </button>
          {onSave && (
            <button
              onClick={onSave}
              disabled={isSaving}
              className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              {isSaving ? "保存中..." : "保存"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
