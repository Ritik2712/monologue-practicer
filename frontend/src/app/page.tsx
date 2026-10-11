import Link from "next/link";

import { BackendStatus } from "@/components/BackendStatus";

export default function Home() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Monologue Coach</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          A local speaking-practice coach. Everything runs on this device.
        </p>
      </div>

      <Link
        href="/practice"
        className="block rounded-lg border border-zinc-200 p-4 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:border-zinc-800 dark:hover:bg-zinc-900 dark:focus-visible:outline-indigo-400"
      >
        <span className="font-semibold">Daily Speaking Practice</span>
        <span className="mt-1 block text-sm text-zinc-600 dark:text-zinc-400">
          A timed five-step routine with a checklist and a history of recent days.
        </span>
      </Link>

      <Link
        href="/monologue"
        className="block rounded-lg border border-zinc-200 p-4 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:border-zinc-800 dark:hover:bg-zinc-900 dark:focus-visible:outline-indigo-400"
      >
        <span className="font-semibold">Monologue</span>
        <span className="mt-1 block text-sm text-zinc-600 dark:text-zinc-400">
          Compare your take with the original recording, pause by pause and phrase by phrase,
          and listen to both side by side.
        </span>
      </Link>

      <Link
        href="/general"
        className="block rounded-lg border border-zinc-200 p-4 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:border-zinc-800 dark:hover:bg-zinc-900 dark:focus-visible:outline-indigo-400"
      >
        <span className="font-semibold">General Practice</span>
        <span className="mt-1 block text-sm text-zinc-600 dark:text-zinc-400">
          Record or upload your voice and see your pace, pauses, loudness and pitch, phrase by
          phrase, with coaching for the next take.
        </span>
      </Link>

      <BackendStatus />
    </div>
  );
}
