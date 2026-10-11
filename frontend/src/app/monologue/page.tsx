import type { Metadata } from "next";

import { MonologuePractice } from "@/features/general/components/MonologuePractice";

export const metadata: Metadata = {
  title: "Monologue · Monologue Coach",
};

export default function MonologuePage() {
  return <MonologuePractice />;
}
