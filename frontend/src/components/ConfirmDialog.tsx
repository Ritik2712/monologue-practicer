"use client";

import { useEffect, useId, useRef } from "react";

import { Button } from "./Button";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * A yes/no question in the browser's native modal <dialog>, which traps focus, closes on
 * Escape and returns focus to the button that opened it.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      // Fires for Escape as well. When we closed it ourselves, `open` is already false.
      onClose={() => {
        if (open) onCancel();
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-lg border border-zinc-200 bg-white p-6 text-zinc-900 shadow-xl backdrop:bg-black/50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
    >
      <h2 id={titleId} className="text-lg font-semibold">
        {title}
      </h2>
      <p id={descriptionId} className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">
        {description}
      </p>
      <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        {/* First in the DOM, so the dialog focuses the safe choice when it opens. */}
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="danger" onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
