"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/practice", label: "Daily Practice" },
  { href: "/monologue", label: "Monologue" },
  { href: "/general", label: "General Practice" },
] as const;

export function MainNav() {
  const pathname = usePathname();

  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      {LINKS.map(({ href, label }) => {
        const current = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <li key={href}>
            <Link
              href={href}
              aria-current={current ? "page" : undefined}
              className={`rounded px-1 py-2 underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400 ${
                current ? "font-semibold underline" : "text-zinc-700 dark:text-zinc-300"
              }`}
            >
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
