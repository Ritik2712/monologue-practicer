import type { Metadata } from "next";
import { Suspense } from "react";

import { PracticeChecklist } from "@/features/practice/components/PracticeChecklist";

export const metadata: Metadata = {
  title: "Daily Speaking Practice · Monologue Coach",
};

export default function PracticePage() {
  // The page reads which monologue to practise from the address, which is only known in
  // the browser.
  return (
    <Suspense fallback={null}>
      <PracticeChecklist />
    </Suspense>
  );
}
