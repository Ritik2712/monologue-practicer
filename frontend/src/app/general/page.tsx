import type { Metadata } from "next";

import { GeneralPractice } from "@/features/general/components/GeneralPractice";

export const metadata: Metadata = {
  title: "General Practice · Monologue Coach",
};

export default function GeneralPracticePage() {
  return <GeneralPractice />;
}
