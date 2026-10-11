import { Button } from "@/components/Button";

import { formatDayLabel } from "../format";
import { recentDateKeys } from "../localDate";
import { isPristine, summarizeDay } from "../practiceState";
import type { PracticeSnapshot } from "../practiceStore";
import type { DailyPracticeRecord } from "../types";

const RECENT_DAYS = 7;

type PracticeHistoryProps = {
  snapshot: PracticeSnapshot;
  onClearHistory: () => void;
};

export function PracticeHistory({ snapshot, onClearHistory }: PracticeHistoryProps) {
  const { todayKey, record, history } = snapshot;

  const byDate = new Map(history.map((day) => [day.localDate, day]));
  if (!isPristine(record)) byDate.set(record.localDate, record);

  const recentKeys = recentDateKeys(todayKey, RECENT_DAYS);
  const olderDays = history.filter((day) => !recentKeys.includes(day.localDate));

  return (
    <section aria-labelledby="history-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="history-heading" className="text-lg font-semibold">
          Last {RECENT_DAYS} days
        </h2>
        <Button variant="danger" disabled={history.length === 0} onClick={onClearHistory}>
          Clear history
        </Button>
      </div>

      <HistoryTable
        caption={`Practice in the last ${RECENT_DAYS} days`}
        rows={recentKeys.map((key) => ({ key, day: byDate.get(key) }))}
        todayKey={todayKey}
      />

      {olderDays.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer rounded px-1 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400">
            Older days ({olderDays.length})
          </summary>
          <HistoryTable
            caption="Older practice days"
            rows={olderDays.map((day) => ({ key: day.localDate, day }))}
            todayKey={todayKey}
          />
        </details>
      )}
    </section>
  );
}

type HistoryTableProps = {
  caption: string;
  rows: { key: string; day: DailyPracticeRecord | undefined }[];
  todayKey: string;
};

function HistoryTable({ caption, rows, todayKey }: HistoryTableProps) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-zinc-600 dark:text-zinc-400">
          <tr className="border-b border-zinc-200 dark:border-zinc-800">
            <th scope="col" className="py-2 pr-4 font-medium">
              Date
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Monologue
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Steps completed
            </th>
            <th scope="col" className="py-2 font-medium">
              Completion
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ key, day }) => {
            const summary = day ? summarizeDay(day) : null;
            return (
              <tr key={key} className="border-b border-zinc-100 dark:border-zinc-900">
                <th scope="row" className="py-2 pr-4 font-normal whitespace-nowrap">
                  {formatDayLabel(key, todayKey)}
                </th>
                {summary ? (
                  <>
                    <td className="py-2 pr-4 break-words">
                      {summary.monologues.length > 0 ? summary.monologues.join(", ") : "—"}
                    </td>
                    <td className="py-2 pr-4">
                      {summary.best.completed} of {summary.best.total}
                      {summary.best.skipped > 0 && ` (${summary.best.skipped} skipped)`}
                      {/* The figures are those of the round that got furthest. */}
                      {summary.rounds > 1 && ` · best of ${summary.rounds} rounds`}
                    </td>
                    <td className="py-2 tabular-nums">
                      {summary.best.percent}%
                      {summary.fullRounds === 1 && " · full routine"}
                      {summary.fullRounds > 1 && ` · full routine × ${summary.fullRounds}`}
                    </td>
                  </>
                ) : (
                  <td colSpan={3} className="py-2 text-zinc-600 dark:text-zinc-400">
                    No practice recorded
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
