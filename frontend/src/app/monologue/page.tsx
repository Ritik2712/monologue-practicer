import type { Metadata } from "next";

import { MonologueList } from "@/features/monologue/components/MonologueList";

export const metadata: Metadata = {
  title: "Monologues · Monologue Coach",
};

export default function MonologuesPage() {
  return <MonologueList />;
}
