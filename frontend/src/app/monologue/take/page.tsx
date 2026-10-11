import type { Metadata } from "next";
import { Suspense } from "react";

import { TakeAnalysis } from "@/features/monologue/components/TakeAnalysis";

export const metadata: Metadata = {
  title: "Take analysis · Monologue Coach",
};

export default function TakeAnalysisPage() {
  // The page reads which take to show from the address, which is only known in the browser.
  return (
    <Suspense fallback={null}>
      <TakeAnalysis />
    </Suspense>
  );
}
