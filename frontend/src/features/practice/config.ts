export type PracticeStepConfig = {
  id: string;
  title: string;
  instruction: string;
  durationSeconds: number;
  /** Extra line shown under the instruction, e.g. to flag a feature that is not built yet. */
  note?: string;
  /** A screen elsewhere in the app that helps with this step. */
  link?: { href: string; label: string };
};

/**
 * The daily routine. Change titles, instructions, durations or the number of steps here;
 * the page, the total time and the progress maths all read from this one object.
 */
export const PRACTICE_ROUTINE: { readonly steps: readonly PracticeStepConfig[] } = {
  steps: [
    {
      id: "listen",
      title: "Listen and observe",
      instruction:
        "Study the original actor's pauses, emphasis, pace, breathing, pitch, and vocal intensity.",
      durationSeconds: 180,
      note: "The Monologue screen plays the original and shows its measured pauses, pace, loudness and pitch. Breathing and emphasis by slowing down are not measured: those are still for your ear.",
      link: { href: "/monologue", label: "Open Monologue to study the original recording" },
    },
    {
      id: "mark",
      title: "Mark the delivery",
      instruction: "Mark the words to emphasise, where to pause, and where the voice changes.",
      durationSeconds: 180,
    },
    {
      id: "perform",
      title: "Perform the monologue",
      instruction: "Practise the delivery, rhythm, and emotional progression, not just the words.",
      durationSeconds: 240,
    },
    {
      id: "compare",
      title: "Record and compare",
      instruction: "Record yourself and compare your recording with the original.",
      durationSeconds: 180,
      note: "The Monologue screen records your take and sets it against the original: where each of you pauses, how fast each phrase is said, and both versions to listen to.",
      link: { href: "/monologue", label: "Open Monologue to record and compare your take" },
    },
    {
      id: "correct",
      title: "Correct and repeat",
      instruction: "Choose the two biggest delivery mistakes and perform the passage again.",
      durationSeconds: 120,
    },
  ],
};
