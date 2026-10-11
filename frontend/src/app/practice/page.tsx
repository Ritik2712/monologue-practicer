import type { Metadata } from "next";

import { PracticeChecklist } from "@/features/practice/components/PracticeChecklist";

export const metadata: Metadata = {
  title: "Daily Speaking Practice · Monologue Coach",
};

export default function PracticePage() {
  return <PracticeChecklist />;
}
