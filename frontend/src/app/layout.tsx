import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { MainNav } from "@/components/MainNav";

import "./globals.css";

export const metadata: Metadata = {
  title: "Monologue Coach",
  description: "Local speaking-practice coach for Hindi and English monologues.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <header className="border-b border-zinc-200 dark:border-zinc-800">
          <nav
            aria-label="Main"
            className="mx-auto flex w-full max-w-4xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3"
          >
            <Link
              href="/"
              className="rounded font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400"
            >
              Monologue Coach
            </Link>
            {/* usePathname can suspend on routes with dynamic params, so it gets a boundary. */}
            <Suspense fallback={null}>
              <MainNav />
            </Suspense>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
