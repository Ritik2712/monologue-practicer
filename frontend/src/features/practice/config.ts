export type PracticeStepConfig = {
  id: string;
  title: string;
  instruction: string;
  durationSeconds: number;
  /** Extra line shown under the instruction, e.g. to say what the app does not measure. */
  note?: string;
  /** What the step's tools are, to finish the sentence "Show …" on the button that opens them. */
  tools: string;
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
      note: "Breathing, and emphasis made by slowing down, are not measured: those are still for your ear.",
      tools: "the original recording",
    },
    {
      id: "mark",
      title: "Mark the delivery",
      instruction: "Mark the words to emphasise, where to pause, and where the voice changes.",
      durationSeconds: 180,
      tools: "the script of the original",
    },
    {
      id: "perform",
      title: "Perform the monologue",
      instruction: "Practise the delivery, rhythm, and emotional progression, not just the words.",
      durationSeconds: 240,
      tools: "the script to perform from",
    },
    {
      id: "compare",
      title: "Record and compare",
      instruction: "Record yourself and compare your recording with the original.",
      durationSeconds: 180,
      tools: "recording and the comparison",
    },
    {
      id: "correct",
      title: "Correct and repeat",
      instruction: "Choose the two biggest differences from the original and perform the passage again.",
      durationSeconds: 120,
      tools: "the biggest differences",
    },
  ],
};
