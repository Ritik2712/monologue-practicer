"use client";

import Link from "next/link";
import { useState } from "react";

import { Button, buttonClasses } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { BackendNotice } from "@/features/general/components/BackendNotice";
import { everythingExportUrl, monologueExportUrl } from "@/features/general/exportLinks";
import { MUTED, Notice } from "@/features/general/components/parts";
import { RunPanel } from "@/features/general/components/RunPanel";
import { formatDateTime, formatSpan, languageName } from "@/features/general/format";
import type { Monologue } from "@/features/general/types";
import { useBackendHealth, useGeneralStore } from "@/features/general/useGeneralPractice";

import { practiceHref } from "../links";
import { AddMonologue } from "./AddMonologue";

function takesText(monologue: Monologue): string {
  if (monologue.takeCount === 0 || monologue.lastTakeAt === null) return "No takes yet";
  const count = monologue.takeCount === 1 ? "1 take" : `${monologue.takeCount} takes`;
  return `${count} · last practised ${formatDateTime(monologue.lastTakeAt)}`;
}

function deleteDescription(monologue: Monologue | null): string {
  const takes =
    !monologue || monologue.takeCount === 0
      ? "It has no takes."
      : monologue.takeCount === 1
        ? "Your 1 take of it is deleted too, with its measurements, coaching and feedback."
        : `Your ${monologue.takeCount} takes of it are deleted too, with their measurements, coaching and feedback.`;
  return `The original recording and its measurements are deleted from this device. ${takes} Your Daily Practice history and your General Practice analyses are not affected. This cannot be undone.`;
}

/**
 * The monologues you practise: each is the original recording of one, added once. Choosing
 * one opens Daily Practice for it.
 */
export function MonologueList() {
  const { state, store } = useGeneralStore();
  const { health, refresh: refreshHealth } = useBackendHealth();
  const [deleting, setDeleting] = useState<Monologue | null>(null);
  // Keeps the dialog's text in place while it closes.
  const [lastDeleting, setLastDeleting] = useState<Monologue | null>(null);

  const options = state.options.status === "ready" ? state.options.data : null;
  const busy = ["submitting", "tracking", "loading_result"].includes(state.run.phase);
  const { monologues } = state;

  const askToDelete = (monologue: Monologue) => {
    setLastDeleting(monologue);
    setDeleting(monologue);
  };

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Monologues</h1>
        <p className="mt-2 text-zinc-700 dark:text-zinc-300">
          The monologues you practise. Add the original recording of each one once. Then choose
          a monologue to open its Daily Practice: listen to the original, mark its delivery,
          perform it, record your take and see where the two differ.
        </p>
        <p className={`mt-1 text-sm ${MUTED}`}>
          Every recording is analysed on this computer and never leaves it. The app compares
          timing and delivery; it does not copy or imitate anyone&rsquo;s voice.
        </p>
      </header>

      <BackendNotice health={health} onCheckAgain={refreshHealth} />

      {state.notice && (
        <Notice
          kind={state.notice.kind}
          action={<Button onClick={() => store.dismissNotice()}>Dismiss</Button>}
        >
          {state.notice.text}
        </Notice>
      )}

      <section aria-labelledby="monologues-heading" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="monologues-heading" className="text-lg font-semibold">
            Your monologues
          </h2>
          {/* Everything stored: every monologue with its takes, and General Practice. */}
          <a href={everythingExportUrl()} download className={buttonClasses("secondary")}>
            Download every analysis as Markdown
          </a>
        </div>

        {monologues.status === "error" && (
          <Notice kind="error" action={<Button onClick={() => store.refreshMonologues()}>Try again</Button>}>
            The monologues could not be loaded. {monologues.message}
          </Notice>
        )}
        {monologues.status === "loading" && <p className={MUTED}>Loading your monologues…</p>}
        {monologues.status === "ready" && monologues.items.length === 0 && (
          <p className="text-sm">
            No monologue yet. Add the original recording of the one you want to practise.
          </p>
        )}

        {monologues.items.length > 0 && (
          <ul className="flex flex-col gap-3">
            {monologues.items.map((monologue) => (
              <li
                key={monologue.monologueId}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-semibold break-words">{monologue.title}</p>
                  <p className={`mt-1 text-sm ${MUTED}`}>
                    {formatSpan(monologue.durationSeconds)} · {languageName(monologue.language)} ·
                    added {formatDateTime(monologue.createdAt)}
                    {monologue.revision > 1 && ` · original at revision ${monologue.revision}`}
                  </p>
                  <p className="mt-1 text-sm">{takesText(monologue)}</p>
                  {!monologue.audioRetained && (
                    <p className={`mt-1 text-xs ${MUTED}`}>
                      The original&rsquo;s recording was not kept: it can be compared with, but
                      not played.
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link
                    href={practiceHref(monologue.monologueId)}
                    aria-label={`Practise ${monologue.title}`}
                    className={buttonClasses("primary")}
                  >
                    Practise
                  </Link>
                  <a
                    href={monologueExportUrl(monologue.monologueId)}
                    download
                    aria-label={`Download the analyses of ${monologue.title} as Markdown`}
                    className={buttonClasses("secondary")}
                  >
                    Download
                  </a>
                  <Button
                    variant="danger"
                    aria-label={`Delete ${monologue.title}`}
                    onClick={() => askToDelete(monologue)}
                  >
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <AddMonologue
        // Starts open when there is nothing to choose from yet.
        key={monologues.status === "ready" && monologues.items.length === 0 ? "first" : "more"}
        initiallyOpen={monologues.status === "ready" && monologues.items.length === 0}
        store={store}
        options={options}
        busy={busy}
      />

      {/* Adding a monologue is a job like any analysis: this follows it. */}
      <RunPanel
        run={state.run}
        kind={state.runKind}
        role={state.runRole}
        coachingFor={state.coachingFor}
        again={state.reanalysisFor !== null}
        store={store}
      />

      <ConfirmDialog
        open={deleting !== null}
        title={`Delete “${(deleting ?? lastDeleting)?.title ?? "this monologue"}”?`}
        description={deleteDescription(deleting ?? lastDeleting)}
        confirmLabel="Delete monologue"
        onConfirm={() => {
          if (deleting) store.deleteMonologue(deleting.monologueId);
          setDeleting(null);
        }}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
