"use client";

import { Button } from "@/components/Button";

import {
  formatDateTime,
  formatMetric,
  formatSpan,
  languageName,
  profileName,
} from "../format";
import type { GeneralState } from "../generalStore";
import { LinkButton, MUTED, Notice } from "./parts";

type HistoryPanelProps = {
  history: GeneralState["history"];
  /** The analysis currently shown in the results, if any. */
  viewedId: string | null;
  onOpen: (analysisId: string) => void;
  onDelete: (analysisId: string) => void;
  onDeleteAudio: (analysisId: string) => void;
  onClear: () => void;
  onRetry: () => void;
};

export function HistoryPanel({
  history,
  viewedId,
  onOpen,
  onDelete,
  onDeleteAudio,
  onClear,
  onRetry,
}: HistoryPanelProps) {
  return (
    <section aria-labelledby="history-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="history-heading" className="text-lg font-semibold">
          Past analyses
        </h2>
        <Button variant="danger" disabled={history.items.length === 0} onClick={onClear}>
          Clear all history
        </Button>
      </div>

      {history.status === "error" && (
        <Notice kind="error" action={<Button onClick={onRetry}>Try again</Button>}>
          The history could not be loaded. {history.message}
        </Notice>
      )}
      {history.status === "loading" && <p className={MUTED}>Loading your history…</p>}
      {history.status === "ready" && history.items.length === 0 && (
        <p className={`text-sm ${MUTED}`}>
          Nothing yet. Each analysis you run is saved here, on this device.
        </p>
      )}

      {history.items.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <caption className="sr-only">Past analyses, newest first</caption>
              <thead className={MUTED}>
                <tr className="border-b border-zinc-200 dark:border-zinc-800">
                  <th scope="col" className="py-2 pr-3 font-medium">When</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Profile</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Length</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Speech-active WPM</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Pauses</th>
                  <th scope="col" className="py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {history.items.map((item) => {
                  const when = formatDateTime(item.createdAt);
                  return (
                    <tr
                      key={item.analysisId}
                      className={`border-b border-zinc-100 align-top dark:border-zinc-900 ${
                        item.analysisId === viewedId ? "bg-indigo-50 dark:bg-indigo-950/40" : ""
                      }`}
                    >
                      <th scope="row" className="py-2 pr-3 font-normal">
                        <span className="whitespace-nowrap">{when}</span>
                        <span className={`block text-xs break-all ${MUTED}`}>
                          {[item.originalFilename, languageName(item.language)].filter(Boolean).join(" · ")}
                        </span>
                        {item.audioRetained && (
                          <span className={`block text-xs ${MUTED}`}>Recording kept</span>
                        )}
                      </th>
                      <td className="py-2 pr-3">{profileName(item.profile)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums whitespace-nowrap">
                        {formatSpan(item.durationSeconds)}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {formatMetric(item.metrics.speechActiveWpm)}
                        {item.metrics.speechActiveWpm?.quality === "estimated" && (
                          <span className={`block text-xs ${MUTED}`}>estimate</span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {formatMetric(item.metrics.pauseCount, 0)}
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-x-3">
                          <LinkButton
                            aria-label={`View the analysis from ${when}`}
                            aria-current={item.analysisId === viewedId ? "true" : undefined}
                            onClick={() => onOpen(item.analysisId)}
                          >
                            {item.analysisId === viewedId ? "Showing" : "View"}
                          </LinkButton>
                          {item.audioRetained && (
                            <LinkButton
                              aria-label={`Delete only the recording from ${when}`}
                              onClick={() => onDeleteAudio(item.analysisId)}
                            >
                              Delete recording
                            </LinkButton>
                          )}
                          <LinkButton
                            aria-label={`Delete the analysis from ${when}`}
                            onClick={() => onDelete(item.analysisId)}
                          >
                            Delete
                          </LinkButton>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {history.total > history.items.length && (
            <p className={`text-sm ${MUTED}`}>
              Showing the latest {history.items.length} of {history.total}.
            </p>
          )}
        </>
      )}
    </section>
  );
}
