# Monologue Coach — Audio Science and AI Documentation

How a recording is turned into numbers — speaking rate, pauses, loudness, pitch — how those
numbers are turned into coaching, with a local AI model doing the wording and ordinary code
checking it, how one recording is compared with another, and how the user's feedback
adjusts a few settings.

- Start with [DOCUMENTATION.md](DOCUMENTATION.md) for the big picture and the general glossary.
- How jobs are queued, run, cancelled and stored is in
  [DOCUMENTATION_BACKEND.md](DOCUMENTATION_BACKEND.md). This file is about **what is
  measured, how the coaching is produced, and why it is done that way**.

Everything described here is built.

**Phase 9 added two things to measure and changed one.** New: the voice's **resonance**
(section 9a), and where the voice **sits**, in pitch and in resonance, against three stated
ranges (section 9b). Changed: the pitch tracker is less strict about what it counts as
voiced, because the old strictness left deeper voices with too little to measure (section
9). A speaker can also choose a **goal**, to keep their voice lower or higher, which the
coaching then follows (section 13).

**Phase 8 changed no measurement.** It joined the Monologue screen and Daily Practice into
one flow, which is a matter of screens and storage (frontend and backend documents). What
it means for this document is small and is marked where it applies: a take is now
compared only with the original it was recorded for (section 14, decision S73), and the
original is shown as a script built only from what was measured (section 14, decision
S74).

**Last updated:** end of Phase 9. The measurements, the coaching (section 13), the
comparison of a take with a reference recording (section 14) and feedback with calibration
(section 15) are all built. Phase 7 added to section 15: pointing at a missed pause by a
word, feedback on a reference recording, and what the feedback adds up to, including three
ways of using the AI model for it that were measured and only one of which was kept.

## Contents

1. [The pipeline at a glance](#1-the-pipeline-at-a-glance)
2. [Sound as numbers](#2-sound-as-numbers)
3. [Finding speech](#3-finding-speech)
4. [Segments, pauses and sections](#4-segments-pauses-and-sections)
5. [Words](#5-words)
6. [Speaking rate: three different WPMs](#6-speaking-rate-three-different-wpms)
7. [Pause statistics](#7-pause-statistics)
8. [Loudness](#8-loudness)
9. [Pitch](#9-pitch)
   - [9a. Resonance](#9a-resonance)
   - [9b. Where a voice sits: the three ranges](#9b-where-a-voice-sits-the-three-ranges)
10. [Emphasis candidates, hesitation sounds, breaths](#10-emphasis-candidates-hesitation-sounds-breaths)
11. [How much to trust a number](#11-how-much-to-trust-a-number)
12. [The settings](#12-the-settings)
13. [Coaching and the AI model](#13-coaching-and-the-ai-model)
14. [Comparing with a reference recording](#14-comparing-with-a-reference-recording)
15. [Feedback and calibration](#15-feedback-and-calibration)
16. [Accuracy and limits](#16-accuracy-and-limits)
17. [Science decisions](#17-science-decisions)
18. [Glossary](#18-glossary)

The measuring code is in `backend/app/pipeline/`. The coaching code is in
`backend/app/coaching/`, and the one file that talks to the AI model is `backend/app/llm.py`.
The code that compares two recordings is in `backend/app/comparison/`. The code that turns
feedback into adjusted settings is in `backend/app/feedback.py` and
`backend/app/calibration/`. The code that counts up what the feedback says is in
`backend/app/feedback_summary.py`.

## 1. The pipeline at a glance

```
 recording.m4a
      │
      ▼
 ┌──────────────┐  audio.py         any file  ->  one long list of numbers (mono, 16 kHz)
 │ 1. Decode    │
 └──────┬───────┘
        ▼
 ┌──────────────┐  vad.py           "speech from 0.0 to 3.1 s, from 4.7 to 8.1 s, …"
 │ 2. Find      │
 │    speech    │
 └──────┬───────┘
        ▼
 ┌──────────────┐  segmentation.py  speech regions  ->  segments + the pauses between them
 │ 3. Segments  │
 │    & pauses  │
 └──────┬───────┘
        ▼
 ┌──────────────┐  transcribe.py    speech  ->  words, each with a start and end time
 │ 4. Words     │                   (skipped entirely if step 2 found no speech)
 └──────┬───────┘
        ▼
 ┌──────────────┐  metrics.py       words per minute, pause statistics
 │ 5. Measure   │  acoustics.py     loudness, pitch, emphasis candidates
 │              │  resonance.py     resonance (how deep or bright the voice sounds)
 │              │  voice_range.py   pitch and resonance placed in three ranges
 │              │  fillers.py       hesitation sounds
 └──────┬───────┘
        ▼
 ┌──────────────┐  runner.py        everything assembled into one result, with quality
 │ 6. Result    │                   labels and warnings
 └──────┬───────┘
        ▼
 ┌──────────────┐  coaching/        the result  ->  findings  ->  corrections, drills,
 │ 7. Coaching  │                   targets (section 13). Changes nothing above it.
 └──────────────┘
```

Steps 1 to 6 are the **measurements**. Step 7 reads them and never alters them. A
reference recording goes through steps 1 to 6 and stops there. Setting one measured
recording against another is a separate step, described in section 14.

Two different tools look at the same audio, and each is trusted for what it is good at:

| Tool | Trusted for | Not trusted for |
| --- | --- | --- |
| Voice activity detector (step 2) | **When** there is speech and when there is silence | What was said |
| Speech recogniser (step 4) | **What** was said, and so how many words | Exactly where a silence starts and ends |

So pause lengths come from step 2, word counts come from step 4, and speaking rate
combines the two.

## 2. Sound as numbers

A microphone measures air pressure many thousands of times per second. Each measurement is
a **sample**: a number between -1 and 1. A recording is just a very long list of samples.

Every file, whatever its format, is first converted to the same form:

| Property | Value | Why |
| --- | --- | --- |
| Channels | 1 (mono) | A voice does not need stereo |
| Sample rate | 16,000 samples per second | What both the speech detector and the speech recogniser expect; enough for speech |
| Sample type | decimal numbers from -1 to 1 | The standard form for audio maths |

One second of audio is therefore 16,000 numbers; a two-minute recording is about 2 million.

**Clipping.** If the voice is too loud for the microphone, samples pile up at exactly -1 or 1
and the sound is distorted. The pipeline counts the share of samples at that ceiling
(`clippingRatio`) and warns if it is more than 0.1%.

Code: `audio.py` (`decode_audio`, `clipping_ratio`).

## 3. Finding speech

**Voice activity detection (VAD)** answers one question for every instant of the recording:
is someone speaking?

The pipeline uses **Silero VAD**, a small neural network that runs locally. It listens in
steps of about 32 milliseconds and gives each step a probability of being speech. Steps
above 0.5 count as speech. Its output is a list of **speech regions**:

```
 speech:   ████████████░░░░░░██████████████░░██░░░░░░░░░░░░░░░░░░░░░░░░█████
 seconds:  0           3.1   4.7           8.1 9.0-9.4                15.6 16.9
```

Why a neural network and not simply "loud means speech": a loudness threshold calls a fan,
a door or a cough "speech", and calls a quiet word "silence". One of the tests feeds the
detector a steady tone as loud as a voice; it correctly reports no speech at all.

One setting was changed from the library's default on purpose. By default each speech
region is widened by 400 ms on both sides, which is helpful for transcription but would
shorten every pause by up to 0.8 seconds. Here the widening is 30 ms, so pause lengths stay
close to the truth.

Code: `vad.py`.

## 4. Segments, pauses and sections

The detector's raw regions are too fine: it may see a 150 ms gap inside "wait… what". Those
are ordinary gaps between words, not pauses. So regions are joined:

| Term | Definition |
| --- | --- |
| **Segment** | Speech regions joined across every gap shorter than 0.5 s. Roughly, one phrase said in one go. |
| **Pause** | The silence between two segments. Always at least 0.5 s. |
| **Section** | A group of segments. A new section starts after every pause of 5 s or more. |
| **Short silence** | A gap between speech regions that is shorter than 0.5 s. It stays inside its segment and counts as speaking time. |

The 0.5 s here is the **minimum pause**. It is the one threshold in this section that the
user's feedback can move, between 0.25 s and 0.8 s (section 15). Wherever this document says
"0.5 s" for a pause, read "the minimum pause the result was made with": every result
records its own.

Short silences are measured and stored with every result, although no figure is built from
them. They are there for one purpose: when the user says "a pause was missed here", the app
can look up what the detector actually heard at that spot (section 15).

Each pause gets a size label:

| Label | Length | Typical meaning (not decided by the app) |
| --- | --- | --- |
| `short` | 0.5 s up to 1 s | A breath, a comma |
| `medium` | 1 s up to 5 s | A deliberate beat, a full stop, a thought |
| `long` | 5 s or more | A structural break; starts a new section |

The app measures how long a pause is. It does **not** decide whether it was dramatic,
accidental or a breath. That is a judgement about intention, and it stays separate from the
measurement.

**The 5-second boundary is not the pause detector.** A pause of 0.7 s and a pause of 6 s are
both pauses and both go into every pause statistic. The 5-second rule only adds the label
`long` and starts a new section.

**Silence at the two ends is not a pause.** Silence before the first word and after the last
word is reported separately (`leadingSilenceSeconds`, `trailingSilenceSeconds`) and is left
out of pause statistics. Nothing was interrupted; the recording simply had not started yet
or had already finished.

### A real example

This is the app's actual output for a 17-second test recording (synthesised speech with
silences inserted on purpose):

```
 seg-1          pause 1.6 s    seg-2            0.8 s  seg-3      pause 6.1 s        seg-4
 ████████████   ░░░░░░░░░░░░   ██████████████   ░░░░   ██   ░░░░░░░░░░░░░░░░░░░░░░   █████
 0.0 ── 3.1                    4.7 ── 8.1              9.0-9.4                       15.6-16.9
 └────────────────────── section 0 ─────────────────────────┘                      └ section 1 ┘
                 medium                          short               long
```

Code: `segmentation.py` (`build_segments`, `classify_pause`, `find_short_silences`).

## 5. Words

### Recognising them

Speech is turned into text by **Whisper**, an open speech-recognition model, running locally
through the **faster-whisper** library. The model size is `small` (about 480 MB).

Whisper works on windows of up to 30 seconds. For each word it also reports a start time,
an end time and a **confidence** between 0 and 1.

Three choices in how it is run (reasons in section 17):

- **Silence is removed first.** Whisper tends to invent words when given silence. If step 2
  found no speech at all, Whisper is not run.
- **Each window stands alone.** Whisper is not shown its own previous output, so one mistake
  cannot snowball into the next window.
- **A window is redone only when it has clearly gone wrong.** If the text of a window is
  wildly repetitive, Whisper tries that window again with a little randomness, up to five
  more times. The bar for "wildly repetitive" is set higher than Whisper's default, so that
  a practised passage said several times is not mistaken for a fault.

### Language

| You choose | Whisper is told | The result says |
| --- | --- | --- |
| `auto` | to detect it | the detected language and how sure it was |
| `en` | English | English (declared) |
| `hi` | Hindi | Hindi (declared); text is in Devanagari |
| `hinglish` | Hindi | Hinglish (declared), with a warning |

Whisper has no mixed-language mode. For Hinglish it is run as Hindi, which writes English
words in Devanagari. That is a best effort, so every word-based number for a Hinglish
recording is labelled an estimate.

### Putting words into segments

Whisper's word times are good but not exact, and a word's time can drift into a pause. The
rule is:

> A word belongs to the segment that contains the **middle** of the word. If the middle
> falls in a pause, the word goes to the nearest segment.

The pipeline counts how many words had to be moved that way. If it is more than 10% of all
words, the two tools disagree about timing more than they should, and word-based numbers
are downgraded to estimates with the warning `word_timing_uncertain`.

### When the recogniser gets stuck

Whisper has a known failure: on a difficult stretch it can lock onto one character or word
and repeat it, producing output like `हुँँँँँँँँँँँँ…` in place of several seconds of speech.
This happened in testing (section 17, decision S9).

Two things guard against it:

- the retry described above, which usually produces a proper transcript on a later attempt;
- a check on the result: any "word" longer than 40 characters, or with one character
  repeated eight or more times in a row, marks the transcript as garbled. The result then
  carries the warning `garbled_transcription` and every word-based number becomes an
  estimate.

### What counts as a word

Anything Whisper outputs that contains at least one letter or digit. `danger,` is a word;
`…` and `।` on their own are not. Hindi words are counted the same way as English ones.

Code: `transcribe.py`, `segmentation.py` (`assign_words`, `count_words`).

## 6. Speaking rate: three different WPMs

"Words per minute" sounds like one number. It is three, and mixing them up is the most
common mistake in measuring speech.

| Name | Formula | What it tells you |
| --- | --- | --- |
| **Segment WPM** | words in the segment ÷ length of that segment in minutes | How fast you spoke in that phrase |
| **Speech-active WPM** | all words ÷ total speaking time in minutes | How fast you speak when you are speaking |
| **Whole-clip WPM** | all words ÷ full length of the recording in minutes | How many words fit in the recording, silences included |

**Speaking time** is the total length of all segments. Gaps shorter than 0.5 s are inside a
segment and count as speaking. Pauses, and the silence at the two ends, do not.

### Why it matters

For the 17-second example above:

| | Words | Time | WPM |
| --- | --- | --- | --- |
| Speech-active | 31 | 8.34 s of speaking | 31 ÷ (8.34 ÷ 60) = **223** |
| Whole clip | 31 | 17.06 s in total | 31 ÷ (17.06 ÷ 60) = **109** |

Same recording, same words: 223 or 109. Half the recording is silence. If only the
whole-clip number were shown, a fast speaker who pauses dramatically would look slow. That
is why the whole-clip figure is always labelled "including pauses" and is never used to
judge speed.

The worked example from the project brief is one of the tests: 12 words in a 4.0-second
segment is 12 ÷ (4 ÷ 60) = 180 WPM.

### When a segment's WPM can be trusted

Short phrases give wild numbers: one word said in 0.44 s is "135 WPM", and two words in
0.4 s would be "300 WPM". A segment's WPM is marked **reliable** only if all of these hold:

| Condition | Flag when it fails |
| --- | --- |
| The segment is at least 2 s long | `short_segment` |
| It has at least 3 words | `few_words` |
| Whisper's average confidence in its words is at least 0.5 | `low_confidence` |

An unreliable segment still shows its number, labelled as an estimate, with the flags that
explain why. Hiding it would be as misleading as trusting it.

### Outliers are flagged, never changed

A segment faster than 180 WPM gets the flag `wpm_outlier`. That flag means "worth a second
look": it could be genuinely fast speech, or the recogniser may have heard extra words. The
measured value is left exactly as it is. It is never capped or "corrected".

### Pace variation

Calculated across the reliable segments only (it needs at least two):

- **Pace variation**: the standard deviation of their WPMs. Near 0 means every phrase at the
  same speed; larger means the speed changes a lot from phrase to phrase.
- **Slowest and fastest** segment WPM.

### Faster or slower than your own typical pace

- **Typical pace** is the *median* WPM of your reliable segments in this recording. It needs
  at least three of them. A median is used so that one rushed line does not drag "typical"
  upwards.
- Each reliable segment is then labelled against it:

| Label | Rule | Example with a typical pace of 160 WPM |
| --- | --- | --- |
| `faster` | at least 25% above typical | 200 WPM or more |
| `typical` | within 25% either way | between 120 and 200 |
| `slower` | at least 25% below typical | 120 WPM or less |

- Short or uncertain segments get no label: their WPM swings too much to compare.

This compares you with **yourself in this recording**, not with a target speed. A phrase
marked "faster" is not a mistake; it is the place to listen to and decide whether the change
of pace was what you wanted.

Code: `metrics.py` (`words_per_minute`, `segment_pace`, `summarize_pace`).

## 7. Pause statistics

All pauses of 0.5 s or more, whatever their label.

| Metric | Formula | Example (pauses of 1.60, 0.84 and 6.15 s in a 17.06 s clip) |
| --- | --- | --- |
| Pause count | number of pauses | 3 |
| Total pause time | sum of their lengths | 8.59 s |
| Average pause | total ÷ count | 2.86 s |
| Median pause | the middle one when sorted | 1.60 s |
| Longest pause | the largest | 6.15 s |
| Pause ratio | total pause time ÷ clip length | 8.59 ÷ 17.06 = 0.50 |

Average and median are both shown because one very long pause pulls the average up (2.86 s
here) while the median still shows what a typical pause is (1.60 s).

A recording with speech but no pauses has a count of 0 and no average. A recording with no
speech has no pause numbers at all: "unavailable", which is different from zero.

Code: `metrics.py` (`summarize_pauses`).

## 8. Loudness

### What is measured

Loudness is measured as **RMS energy**: take a short window of samples (25 ms), square each
one, average them, take the square root. That gives one number per window for how strong
the signal is. It is then written in **decibels relative to full scale (dBFS)**:

```
level in dBFS = 10 × log10(average of the squared samples)
```

0 dBFS is the loudest a digital recording can be; everything else is negative. A speaking
voice in a recording is often somewhere around -30 to -10 dBFS. Every 20 dB is ten times the
amplitude, which one of the tests checks directly.

### What it does not mean

**This is not real-world loudness.** The same voice gives different numbers on a phone held
close, a laptop across the room, or with a different recording volume. So loudness can only
be compared **within one recording** — "this phrase is 4 dB louder than your typical phrase"
— and never between recordings or against a target. Every loudness value in the result is
labelled `dBFS (relative)`, and the notes say it is not calibrated.

### The loudness numbers

| Output | What it is |
| --- | --- |
| `energyTimeline` | Level every 0.25 s across the recording, for drawing a curve (at most 1,200 points; longer recordings use wider steps) |
| `meanEnergyDb` per segment | The level of that phrase |
| `energyDeltaDb` per segment | That phrase compared with the recording's median phrase. Positive is louder |
| `energyVariation` | Standard deviation of the level across quarter-second stretches of speech. Higher means more dynamic delivery |
| `signalToNoise` | How far the voice stands above the background (see below) |

### Background noise

The **signal-to-noise ratio** compares the level of speech with the level of the background:
the parts at least 0.1 s away from any speech. The background is summarised by its median,
so that the tail of a word or a single click does not count as "noise".

It needs at least half a second of background, otherwise it is unavailable. It is always
labelled an estimate. Below 10 dB the result carries the warning `noisy`, because pauses are
harder to detect when the background is nearly as loud as the voice.

Code: `acoustics.py` (`measure_energy`, `summarize_energy`, `energy_timeline`).

## 9. Pitch

### What is measured

When you say a vowel, your vocal folds open and close a certain number of times per second.
That rate is the **fundamental frequency**, written F0 and measured in hertz (Hz). It is
what we hear as how high or low a voice is. Typical speaking pitch is roughly 85–180 Hz for
deeper voices and 165–255 Hz for higher ones.

Only **voiced** sounds have a pitch: vowels and sounds like "m" or "z". Sounds like "s", "f"
and "t" are noise and have none. So pitch exists for part of the speech only.

The pipeline uses the **pYIN** algorithm (from the librosa library) on the speech segments
only. For each 16 ms step it gives a pitch and a probability that the step is voiced. Steps
with probability below 0.3 are thrown away. The search range is 65–500 Hz.

**The 0.3 was 0.5 until Phase 9, and the change was measured.** Phase 9 is about where a
voice sits, and the first run on a deeper voice came back with "pitch unavailable": a
7-second recording had kept fewer than the 30 voiced steps a pitch needs. The tracker is
simply less sure of itself on a deep voice, where a step holds fewer cycles of the sound.
Counted on fourteen synthesised voices, two sentences each:

| Voice | Steps in all | Kept at 0.5 | Kept at 0.3 | Median pitch at 0.5 | at 0.3 |
| --- | --- | --- | --- | --- | --- |
| Daniel (deeper) | 771 | 50 (6%) | 143 (19%) | 121 Hz | 119 Hz |
| Reed (deeper) | 857 | 52 (6%) | 148 (17%) | 107 Hz | 108 Hz |
| Fred (deeper) | 913 | 106 (12%) | 305 (33%) | 103 Hz | 100 Hz |
| Rishi (deeper) | 865 | 172 (20%) | 336 (39%) | 116 Hz | 115 Hz |
| Samantha (higher) | 776 | 340 (44%) | 435 (56%) | 182 Hz | 181 Hz |
| Karen (higher) | 783 | 459 (59%) | 534 (68%) | 188 Hz | 189 Hz |
| Lekha (higher, Hindi) | 769 | 308 (40%) | 436 (57%) | 230 Hz | 224 Hz |

At 0.3 a deeper voice keeps two to three times as many steps, and across all fourteen the
median pitch moved by 6 Hz at most and by 3 Hz or less for thirteen of them. Dropping the
test altogether kept more steps still, but the spread of pitch then grew for some voices
(Daniel from 2.4 to 3.1 semitones, Samantha from 2.5 to 3.2), which is the stray,
badly tracked steps coming in. The value is recorded with every result as the setting
`pitch_voiced_probability`, and the settings version went from 1 to 2 with it. A result
made before the change is not recalculated; analysing a kept recording again uses the new
value.

### The pitch numbers

| Output | What it is |
| --- | --- |
| `pitchMedianHz` | The speaker's typical pitch |
| `pitchRangeHz` | From the 5th to the 95th percentile, in Hz |
| `pitchRangeSemitones` | The same range in semitones |
| `pitchVariationSemitones` | Standard deviation around the speaker's own median, in semitones |
| `medianPitchHz` per segment | Typical pitch of that phrase |
| `pitchDeltaSemitones` per segment | That phrase compared with the speaker's median |

### Why percentiles

Pitch trackers occasionally jump an octave by mistake. Using the 5th and 95th percentile
instead of the lowest and highest value ignores those few wrong steps.

### Why semitones

A **semitone** is one step on a piano keyboard; twelve of them double the frequency.
Semitones measure pitch as a ratio rather than a difference:

```
semitones between two pitches = 12 × log2(higher ÷ lower)
```

This makes voices comparable. A deep voice moving from 100 to 150 Hz and a high voice moving
from 200 to 300 Hz both moved 7 semitones — the same amount of expression — although one
moved 50 Hz and the other 100 Hz. One of the tests checks this with an octave: the same
shape of movement at two registers gives the same number of semitones.

### No target pitch, unless the speaker sets one

The app never says of its own accord that a pitch is too high or too low, and no delivery
profile has a target pitch. A voice's register is a property of the person.

Since Phase 9 there is one exception, and it is the speaker's: they may choose a goal, to
keep their voice in the lower range or in the higher one (section 9b). With a goal, the
coaching points at the phrases that left that range. With none, where the voice sits is
measured and stated, and nothing is made of it.

### When pitch is unavailable

With fewer than 30 voiced steps (about half a second) there is too little to describe a
voice. Pitch is then "unavailable" with the warning `pitch_unavailable`, rather than a
number computed from almost nothing.

Code: `acoustics.py` (`measure_pitch`, `summarize_pitch`, `semitones`).

## 9a. Resonance

### What it is

Pitch is the note a voice speaks on. **Resonance** is how deep or bright the voice sounds
on that note. Two people can say the same vowel on the same note and still sound
different, the way a cello and a violin do. That difference is resonance, and listeners
use it, together with pitch, when they hear a voice as deeper or lighter.

It comes from the shape of the throat and mouth. The space above the vocal folds
strengthens some bands of frequency and weakens others. The strengthened bands are called
**formants**, numbered from the lowest: F1, F2, F3… A longer vocal tract puts its formants
lower and closer together, and the voice sounds deeper; a shorter one puts them higher and
further apart, and the voice sounds brighter. For a plain tube 17.5 cm long, closed at one
end, they fall at 500, 1,500 and 2,500 Hz: 1,000 Hz apart.

```
 strength
    │   F1        F2          F3
    │   ▲         ▲           ▲            a deeper voice: formants closer together
    │  ╱ ╲       ╱ ╲         ╱ ╲
    │ ╱   ╲     ╱   ╲       ╱   ╲
    └─┴────┴───┴─────┴─────┴─────┴──────▶ frequency
     500      1500        2500 Hz        spacing ≈ 1000 Hz

    │     F1          F2            F3
    │     ▲           ▲             ▲      a brighter voice: formants further apart
    │    ╱ ╲         ╱ ╲           ╱ ╲
    └────┴──┴───────┴───┴─────────┴───┴─▶ frequency
       600        1800          3000 Hz  spacing ≈ 1200 Hz
```

### The figure reported: formant spacing

The app reports one number for resonance: the **average spacing of the first three
formants**, in Hz. Lower is deeper, higher is brighter.

It is found like this:

1. The recording is reduced to the part of the sound below 4,000 Hz.
2. Every hundredth of a second, a 25 ms slice is taken, but only inside speech, and only
   where the sound is within 20 dB of the loud parts of the speech. Those are the vowels;
   quiet consonants, breaths and background have no clear resonance to measure.
3. For each slice, **linear prediction (LPC)** finds the resonances. LPC fits a small
   filter to the slice, and the peaks of that filter are the formants. A peak wider than
   500 Hz, or lower than 90 Hz, is not counted as one. A slice in which three formants
   cannot be found is left out.
4. Over a phrase, or the whole recording, the **median** of each formant is taken, so the
   odd badly tracked slice does not move the answer.
5. The spacing is the step of the evenly spaced ladder that fits those three medians best:

```
 spacing = (0.5 × F1 + 1.5 × F2 + 2.5 × F3) ÷ 8.75
```

   A ladder at 500, 1,500, 2,500 gives (250 + 2,250 + 6,250) ÷ 8.75 = 1,000. F3 weighs
   five times as much as F1 in this, on purpose: F1 and F2 change a great deal from one
   vowel to the next ("ee" against "aw"), and F3 much less, so the figure describes the
   voice more than the words being said.

One of the tests builds a crude vowel with exactly known formants, a buzz passed through
three resonators, and checks that the real analysis finds them: formants at 500, 1,500 and
2,500 Hz come back as a spacing of 1,000 Hz within 20, and 600, 1,800 and 3,000 as 1,200.
The same vowel on a 100 Hz note and on a 220 Hz note gives the same resonance within 30 Hz,
which is the point of measuring it apart from pitch.

### Why three formants under 4,000 Hz, and not more

The usual recipe for formants looks up to 5,000 or 5,500 Hz and finds four or five. That
was built first, and measured against the alternative on fourteen synthesised voices (six
deeper, eight higher; two sentences each), clean and with hiss added:

| Method | Clean: deeper voices | Clean: higher voices | Gap between them | Worst shift with pink noise 30 dB below the voice | 20 dB below |
| --- | --- | --- | --- | --- | --- |
| 4 formants under 5,500 Hz | 903 to 998 Hz | 1,117 to 1,289 Hz | 119 Hz | +277 Hz | +320 Hz |
| **3 formants under 4,000 Hz** | 943 to 1,017 Hz | 1,103 to 1,298 Hz | 86 Hz | 25 Hz | 34 Hz |
| 3 formants under 4,200 Hz | 947 to 1,087 Hz | 1,105 to 1,319 Hz | 18 Hz | 56 Hz | 98 Hz |
| 3 formants under 3,800 Hz | 950 to 1,025 Hz | 1,104 to 1,247 Hz | 79 Hz | 21 Hz | 43 Hz |
| 3 formants under 4,000 Hz, peaks up to 700 Hz wide | 939 to 994 Hz | 1,104 to 1,252 Hz | 110 Hz | 37 Hz | 77 Hz |

The first row separates the clean voices best and falls apart with the faintest hiss: one
deeper voice moved by 277 Hz, more than twice the gap. Above 4,000 Hz a voice has little
energy, so a "formant" found there is as likely to be the background. The second row gives
up a little separation on clean recordings and barely moves in noise. It is the one used.

The same settings are used for every voice. The usual recipe also changes its upper limit
by the sex of the speaker; here that would be deciding the answer before measuring it.

### How far it can be trusted

**A whole recording.** With the method above, every one of 28 clean clips (5 to 8 seconds
each) landed in the range of its voice: the deeper voices measured 944 to 1,033 Hz, the
higher ones 1,103 to 1,304 Hz.

**A short phrase** is harder, because a few seconds hold only a few vowels and the mix of
vowels moves the figure. The same recordings cut into short stretches:

| Length of stretch | Deeper voices placed lower / neutral / higher | Higher voices placed lower / neutral / higher |
| --- | --- | --- |
| 1.0 s | 92% / 4% / 4% | 1% / 16% / 83% |
| 1.5 s | 88% / 10% / 2% | 2% / 15% / 84% |
| 2.5 s | 89% / 11% / 0% | 0% / 11% / 89% |

So a phrase lands in the *opposite* range a few times in a hundred when it is short and
not at all at 2.5 seconds, and in the neutral range about one time in seven. A phrase with
under about a second and a half of usable sound (roughly two and a half seconds of speech)
is therefore labelled an **estimate**. Under a fifth of a second of usable sound, no
figure is given.

**Background hiss** pushes the figure up, towards "brighter", because it is read as
resonance that is not there. White noise added to the clean clips:

| Voice above background | Typical shift | Worst shift | What the app does |
| --- | --- | --- | --- |
| 30 dB | +12 Hz | +54 Hz | Measured |
| 20 dB | +30 Hz | +74 Hz | **Estimate**, with a warning, under 30 dB |
| about 15 dB | — | +175 Hz (one deeper voice read as "higher") | **Not given**, under 20 dB |
| 10 dB | +97 Hz | +272 Hz | Not given |

The lower range is only 100 Hz wide, so the limits are set where a shift can cross it. They
were first set at 20 and 10 dB. The end-to-end run then put a deeper voice with hiss 14 dB
below it through the real pipeline, and its resonance came back as 1,192 Hz, "higher",
labelled an estimate. An estimate in the wrong range is still a wrong answer, and here it
would tell a speaker their voice is brighter than it is, so both limits were raised. A
low rumble, by contrast, hardly matters: noise weighted towards low frequencies moved the
figure by 15 Hz at most, even at 10 dB.

**Other things tried:** saving the clips as compressed AAC moved the figure by 18 Hz at
most; making the recording 20 or 35 dB quieter, by 6 Hz at most. The analysis runs at
about 85 times real time on this machine.

**What has not been tried: a person.** All of this is from synthesised voices. They are
built from real recordings and have real formants, but a human voice recorded on a laptop
microphone in a room may sit differently in these figures, and nothing here has been
checked against one. See "Accuracy and limits".

Code: `resonance.py` (`measure_resonance`, `formant_spacing`, `ResonanceTrack`).

## 9b. Where a voice sits: the three ranges

Pitch and resonance are each placed in one of three ranges:

| Range | Typically heard as | Pitch (median, Hz) | Resonance (formant spacing, Hz) |
| --- | --- | --- | --- |
| **Lower** | a masculine voice | under 145 | under 1,040 |
| **Neutral** | either | 145 to 175 | 1,040 to 1,100 |
| **Higher** | a feminine voice | over 175 | over 1,100 |

**What a range says, and what it does not.** It says how a voice with that pitch or that
resonance is *typically heard*. It does not say who is speaking, and the app never states
or guesses that. Plenty of men speak above 145 Hz and plenty of women below 175; a range
is a description of a sound.

**Where the numbers come from.**

- *Pitch.* The speaking pitch usually given for adult men is roughly 85 to 155 Hz and for
  adult women roughly 165 to 255 Hz, with a stretch in between, around 145 to 175 Hz, in
  which listeners do not agree. These are round figures from voice science and voice
  training, used here as this app's ranges. They were not measured by this project.
- *Resonance.* There is no such well-known table for formant spacing measured this
  particular way, so the ranges were set from this app's own measurements above: the
  deeper synthesised voices fell between 944 and 1,033 Hz and the higher ones between
  1,103 and 1,304 Hz, with nothing in between. The neutral range, 1,040 to 1,100 Hz, is
  that gap. This is a much thinner basis than the pitch ranges have, and it is fourteen
  synthesised voices, not people.

### The percentage

Each placement also has a percentage. It is a **position inside the range**, not a
probability and not a score:

```
            LOWER RANGE              NEUTRAL            HIGHER RANGE
  ├──────────────────────────┼──────────────┼────────────────────────────────┤
  85 Hz                    145 Hz         175 Hz                          255 Hz
  100%  ◀───────────────── 0%   0% ─▶100%◀─ 0%   0% ──────────────────────▶ 100%
  the deep end        the edge     the middle      the edge            the high end
```

| In the… | 0% is | 100% is | Formula |
| --- | --- | --- | --- |
| Lower range | the edge next to the neutral range | the deep end, and anything beyond it | (edge − value) ÷ (edge − deep end) |
| Higher range | the edge next to the neutral range | the high end, and anything beyond it | (value − edge) ÷ (high end − edge) |
| Neutral range | either edge | the middle | 1 − distance from the middle ÷ half the width |

Worked examples for pitch: 118 Hz is (145 − 118) ÷ (145 − 85) = **45%** of the way into
the lower range. 200 Hz is (200 − 175) ÷ (255 − 175) = **31%** into the higher range.
160 Hz is the middle of the neutral range: **100%**. For resonance the ends are 940 and
1,300 Hz: 990 Hz is (1,040 − 990) ÷ 100 = **50%** into the lower range.

"45% of the way into the lower range" means exactly that and no more. It does not mean
"45% likely to be heard as masculine". Nothing here measures how listeners hear a voice.

### Pitch and resonance together: one marker

Each phrase, and the recording as a whole, also gets one word:

| Pitch | Resonance | Together | Why |
| --- | --- | --- | --- |
| lower | lower | **lower** | |
| higher | higher | **higher** | |
| neutral | neutral | **neutral** | |
| neutral | lower | **lower** | One has no lean, so the other decides |
| lower | higher | **mixed** | A listener is given two different cues |
| lower | not measured | **lower** | Only one was measured; it decides |

"Mixed" matters for anyone working on their voice. A lower pitch with a bright resonance
can still be heard as a lighter voice, and pitch alone would never show it.

### What is stored

Every result carries, for the whole recording and for each phrase: the value in Hz, the
range, the percentage, and whether it is measured or an estimate. It also carries the
ranges themselves, with a version number, so a result can always be explained by the
ranges that placed it. The goal, if the speaker chose one, is stored beside them; it
changes how the result is *read* and changes no number in it.

Code: `voice_range.py` (`VoiceRangeSettings`, `place`, `overall_marker`); `runner.py`
(`_VoiceReader`).

## 10. Emphasis candidates, hesitation sounds, breaths

### Emphasis candidates

A word is listed as a **candidate** for emphasis if it stands out from the speaker's own
typical word in at least one way:

| Reason | Rule |
| --- | --- |
| `louder` | at least 3 dB above the median word level in this recording |
| `higher_pitch` | at least 2 semitones above the speaker's median pitch |

At most the 10 strongest are kept. There must be at least 5 measurable words, otherwise
there is no "typical word" to compare with and nothing is listed.

They are called candidates deliberately. The measurements say a word was louder or higher.
They cannot say the speaker *meant* to stress it, and a word can be emphasised in ways this
does not detect, such as slowing down or a pause before it.

### Hesitation sounds

The transcript is searched for sounds that are never real words: `um`, `uh`, `er`, `hmm`
and their Hindi counterparts such as `अं` and `हम्म`.

Two limits, both stated in the result:

- Words such as "like", "you know", "मतलब" and "तो" are **not** counted. They are sometimes
  fillers and sometimes meaningful, and a transcript cannot tell which.
- Speech recognisers often leave hesitation sounds out of their text. So the count is a
  **lower bound** and is always labelled an estimate.

### Breaths

**Not detected.** `breathCount` is always "unavailable". A silence does not prove a breath
was taken, and reliably telling a breath from other quiet noise needs a method this project
does not have yet. Reporting a guess as a count would be dishonest, so nothing is reported.

Code: `acoustics.py` (`find_emphasis_candidates`), `fillers.py`.

## 11. How much to trust a number

Every metric in the result carries a **quality** label.

| Quality | Meaning | Example |
| --- | --- | --- |
| `measured` | Computed directly from the signal by a method suited to it | Pause lengths; WPM of a long, clearly recognised segment |
| `estimated` | A real calculation, but on shaky input or by a rough method | WPM of a one-second segment; anything word-based in Hinglish; signal-to-noise |
| `unavailable` | Could not be worked out. The value is empty, never 0 | Pitch of a whisper; WPM when no words were recognised; breaths |

"Unavailable" being empty rather than zero matters: "0 pauses" is a real finding, "pauses
unknown" is not.

The result also carries **warnings** about the recording as a whole:

| Code | Raised when | Effect |
| --- | --- | --- |
| `no_speech` | The detector found no speech | Transcription is skipped; most metrics unavailable |
| `no_words` | Speech was found but no words recognised | Word-based metrics unavailable; pauses still measured |
| `very_short` | The recording is under 3 s | Advisory |
| `hinglish_best_effort` | Language was set to Hinglish | Word-based metrics become estimates |
| `uncertain_transcription` | Average word confidence is under 0.5 | Word-based metrics become estimates |
| `garbled_transcription` | A "word" is over 40 characters, or repeats one character 8+ times | Word-based metrics become estimates |
| `word_timing_uncertain` | More than 10% of words had to be moved into a segment | Word-based metrics become estimates |
| `language_uncertain` | Auto-detected language confidence is under 0.6 | Advisory |
| `clipping` | More than 0.1% of samples are at the ceiling | Advisory: loudness and pitch less reliable |
| `noisy` | Signal-to-noise is under 10 dB | Advisory: pauses may be less accurate |
| `pitch_unavailable` | Under 30 voiced steps | Pitch metrics unavailable |

Things that come from the sound alone — pause lengths, speaking time, loudness — stay
`measured` even when the transcript is doubtful, because they do not depend on it.

## 12. The settings

All thresholds are in one place, `settings.py`, as `AnalysisSettings`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `min_pause_ms` | 500 | A silence at least this long is a pause |
| `medium_pause_ms` | 1000 | From here a pause is `medium` |
| `long_silence_ms` | 5000 | From here a pause is `long` and starts a new section |
| `min_segment_ms` | 2000 | Shortest segment whose WPM is trusted |
| `min_segment_words` | 3 | Fewest words for a trusted WPM |
| `wpm_outlier` | 180 | Faster than this is flagged for review |
| `low_confidence` | 0.5 | Below this, recognition is treated as doubtful |
| `pace_deviation_ratio` | 0.25 | How far from typical pace counts as faster or slower |
| `min_segments_for_typical_pace` | 3 | Reliable segments needed before a typical pace is given |
| `vad_threshold` | 0.5 | Speech probability needed to count as speech |
| `vad_min_speech_ms` | 100 | Shorter bursts of "speech" are ignored |
| `vad_min_silence_ms` | 100 | Shorter gaps do not split a speech region |
| `vad_speech_pad_ms` | 30 | Widening of each speech region |
| `pitch_voiced_probability` | 0.3 | How sure the pitch tracker must be that a step is voiced before its pitch is used (section 9). 0.5 until Phase 9 |
| `version` | 2 | Goes up whenever a default changes. 1 until Phase 9 |
| `calibration_version` | 1 | Which version of the user's calibration supplied `min_pause_ms`. 1 means the default |

**Every result stores a full copy of the settings that produced it.** Months later it is
still possible to say "this was measured with a 0.5 s pause threshold".

Of all these, feedback can adjust exactly one: `min_pause_ms` (section 15). The value in
this table is its default. When feedback moves it, results made afterwards use the new
value and say so; results made before are not recalculated and keep the settings they
record.

Settings that contradict each other are refused when created; for example, a minimum pause
longer than the long-silence boundary.

**The voice ranges are a second, separate group**, `VoiceRangeSettings` in `voice_range.py`,
with a version number of their own (1). They are the eight values of section 9b: for pitch
85, 145, 175 and 255 Hz, and for resonance 940, 1,040, 1,100 and 1,300 Hz. They are kept
apart because they do not change what is measured, only how a measurement is described, and
a copy is stored with every result in the same way. Feedback cannot adjust them.

The constants of the resonance measurement itself (4,000 Hz, three formants, the 500 Hz
width, the 20 and 30 dB noise limits) are fixed in `resonance.py`, each with the reason
beside it. They are part of the method, like the 16 ms pitch step, and are not copied into
each result; changing one would mean raising the settings version.

## 13. Coaching and the AI model

All code for this section is in `backend/app/coaching/` and `backend/app/llm.py`.

### The idea in one picture

```
 measurements (sections 1 to 12)
        │
        ▼
 ┌──────────────┐  findings.py   "You spoke at 240 WPM while speaking. That is fast:
 │ 1. Findings  │                 over 200 WPM."  +  is it an issue, a strength, or neither
 └──────┬───────┘                 for the chosen profile?        (ordinary code, no AI)
        │
        ├─────────────────────────────────────────────┐
        ▼                                             ▼
 ┌──────────────┐  prompt.py                   ┌──────────────┐  rules.py
 │ 2. Ask the   │  llm.py                      │ Templates    │  the same findings,
 │    AI model  │  profile + transcript +      │              │  worded by fixed
 └──────┬───────┘  findings, as text           └──────┬───────┘  sentences
        ▼                                             │
 ┌──────────────┐  grounding.py                       │
 │ 3. Check its │  every figure, time, segment        │  used when the model is not
 │    answer    │  and quotation is looked up         │  available, or nothing in its
 └──────┬───────┘                                     │  answer passes the checks
        ▼                                             ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 4. Coaching: corrections, what works, targets, caveats      │  coach.py
 └─────────────────────────────────────────────────────────────┘
```

The division of labour is strict:

| | Done by | Why |
| --- | --- | --- |
| Every number: WPM, pause lengths, pitch, timestamps | The measuring code (sections 1 to 12) | Arithmetic must be exact and repeatable |
| Saying what a number *is*: "fast", "very even", "a held silence" | The findings code, using fixed bands | So the same number always gets the same word |
| Deciding whether that suits the chosen profile | The findings code, from the profile's stated leanings | So a correction can never point the wrong way |
| Choosing which issues matter most, picking the line to work on, and wording the reason and the drill | **The AI model** | Reading a script and writing advice about it is what a language model is good at |
| The delivery summary, the targets for the next take, the list of what is uncertain | Code and templates | These must be exact, so the model is not asked |

**The model is never given audio**, and never calculates anything.

### Step 1: findings

A **finding** is one plain statement of fact about the recording, written by ordinary code.
It is the only place a figure in the coaching can come from. For the test recording used in
this document (a 22-second English clip):

```
f1: You spoke at 240 WPM while speaking (pauses left out). That is fast: over 200 WPM.
f2: Your phrases varied by 16 WPM around your typical 242 WPM, which is 7%. That is very
    even: under 10%. Slowest: segment 5 at 209 WPM. Fastest: segment 4 at 248 WPM.
f3: 5 pauses of 0.5 seconds or more, with a median of 1.1 seconds. That is long enough to
    register: 1 second or more. Pauses make up 32% of the recording.
f4: The longest pause is 2.6 seconds, at 0:08.6, between segments 3 and 4. That is a held
    silence: 2 seconds or more.
f5: Loudness varied by 5.2 dB across your speech. That is moderate: between 3 and 6 dB.
f6: Pitch varied by 2.3 semitones around your own median. That is moderate: between 2 and
    4 semitones.
```

Each finding also points back at its **evidence**: the metric, the segment or the pause it
rests on. That is what lets the screen put a Play button beside it.

The full list of findings the code can produce:

| Finding | Produced when | The bands it uses |
| --- | --- | --- |
| `pace` | Speech-active WPM was measured | Unhurried under 140 WPM, fast over 200 WPM, moderate between |
| `pace_variation` | There is a typical pace (at least 3 reliable segments) | Spread of segment WPM ÷ typical pace: very even under 10%, widely varied over 25% |
| `pause_length` | At least one pause | Median pause: short under 1 s, "long enough to register" from 1 s |
| `no_pauses` | No pause at all in 15 s or more of speech | — |
| `held_silence` | At least one pause | Longest pause: a "held silence" from 2 s |
| `loudness_variation` | Loudness variation was measured | Even under 3 dB, widely varied over 6 dB |
| `pitch_variation` | Pitch was measured | Narrow under 2 semitones, wide over 4 |
| `fast_segment`, `slow_segment` | A segment is 25% or more from typical pace (section 6). At most two of each, the furthest first | — |
| `hesitations` | At least one hesitation sound was recognised | — |
| `emphasis` | At least one emphasis candidate (section 10) | — |
| `no_emphasis` | No candidate, in a recording of 20 words or more | — |
| `recognition_confidence` | Words were recognised | — (always "context") |
| `voice_pitch` | Pitch was measured | The three ranges of section 9b: lower under 145 Hz, higher over 175 Hz |
| `voice_resonance` | Resonance was measured | Lower under 1,040 Hz, higher over 1,100 Hz |

If a measurement is unavailable, its finding is simply not produced. A missing number never
becomes a statement.

### The bands

A number on its own says nothing about delivery. "Pitch varied by 1.6 semitones" only becomes
useful once something says whether that is a little or a lot. The bands do that. They are in
`coaching/settings.py`, as `CoachingSettings`:

| Setting | Default | Meaning |
| --- | --- | --- |
| `slow_wpm` | 140 | Below this, speech-active pace is "unhurried" |
| `fast_wpm` | 200 | Above this, it is "fast" |
| `even_pace_ratio` | 0.10 | Pace variation under this share of typical pace is "very even" |
| `varied_pace_ratio` | 0.25 | Over this, "widely varied" |
| `registering_pause_seconds` | 1.0 | A median pause this long "registers" |
| `held_silence_seconds` | 2.0 | A single pause this long is a "held silence" |
| `even_loudness_db` | 3.0 | Loudness variation under this is "even" |
| `varied_loudness_db` | 6.0 | Over this, "widely varied" |
| `narrow_pitch_semitones` | 2.0 | Pitch variation under this is "narrow" |
| `wide_pitch_semitones` | 4.0 | Over this, "wide" |
| `no_pause_min_speech_seconds` | 15 | With no pause at all, shorter speech than this is not remarked on |
| `max_segment_findings` | 2 | Most "this phrase was faster" findings, and most "slower" |
| `version` | 1 | Goes up whenever a default changes |

**These bands are this project's own rough choices.** They were not taken from any actor's
voice, and they were not derived from a study. They are for orientation: a way of putting a
consistent word to a number. Every coaching result stores a copy of them, as every analysis
stores its thresholds, so a result can always be explained by the values that produced it,
and the calibration feature (Phase 6) can move them.

What they have been compared with is thin, and it is stated here so nobody assumes more.
The four synthesised test clips measured: speech-active pace 195 to 240 WPM; median pause
1.1 to 1.6 s; loudness variation 2.8 to 6.2 dB; pitch variation 2.3 to 3.1 semitones. So a
synthesised voice at its default speed lands in "fast", and in "moderate" for pitch. No
human recording has been through them yet.

### How a finding gets its role

Each profile now says, for each measurement it focuses on, which way it **leans**: it wants
that measurement low, or high. This is one word per measurement, in `profiles.py`. It is
still not a number.

| Profile | Leans |
| --- | --- |
| Walter White | Pace variation **low**; median pause **high**; loudness variation **low** |
| Joker | Pace variation **high**; pitch variation **high**; loudness variation **high** |
| Thomas Shelby | Pace **low**; longest pause **high**; loudness variation **low** |
| Custom / neutral | Nothing |

A banded finding then gets its role like this:

| The measurement is in… | …and the profile leans that way | …the opposite way | …the profile has no view |
| --- | --- | --- | --- |
| the low or high band | **strength** | **issue** (weight 1.0) | the general habit below, else **context** |
| the middle band | — | **issue** (weight 0.5): partway there | **context** |

When a profile has no view (always, for Custom / neutral), two general speaking habits
apply, because they hold for almost any delivery: a **fast overall pace** is an issue, and a
**narrow pitch range** is an issue (a wide one is a strength). Everything else is context.

The findings about single things follow the same logic:

| Finding | Role |
| --- | --- |
| A phrase faster than typical | An issue; a **strength** for a profile that leans towards varied pace (Joker), where a phrase that breaks the pattern is the point |
| A phrase slower than typical | An issue only for a profile that wants an even pace (Walter White); a strength for Joker; otherwise context |
| Hesitation sounds | An issue |
| No pause at all | An issue |
| Words that stood out | A strength; context for a restrained profile (Walter White, Thomas Shelby), where a louder word is neither a fault nor a goal |
| No word stood out | An issue only for an expressive profile (Joker) |

The weight puts issues in order, most important first. The coaching uses at most the top
three.

### The fallback: templates

For every kind of issue there is a fixed **template**: a title, a reason, a drill, and a
target, with gaps that code fills in (the profile's name, the opening words of the phrase,
the relevant band). For example, for a fast overall pace:

> **Slow your overall pace.** At this speed a listener has little time to take each phrase
> in. *Drill:* Say “You clearly do not know who you are…” at about half your normal speed,
> stretching the vowels. Then say it once more at a speed between that and normal. Do both 3
> times. *Target:* Bring your speaking pace down towards 200 WPM or below.

There are seventeen such templates (`rules.py`); four of them, added in Phase 9, are for
a voice goal and are described under "A voice goal" below. They are what the user gets, labelled
"Written from fixed rules", whenever the AI model cannot be used. They are also the reason
an analysis never has to fail because of the model.

A test fills in every template under every profile and checks that no gap is left open and
that the only figures in it are the bands.

### Step 2: asking the AI model

**Which model.** `llama3.1:8b`, run by **Ollama** on this computer. It is the model named in
the project brief and it was already installed here. The app never downloads it, or any
other model; if it is missing, the screen says so and gives the command for you to run.

**What it is sent** (`prompt.py`). Text only, in two parts.

The *instructions* tell it, among other things: you did not hear the recording; use only
the findings and the transcript; never state a number, time or measurement that is not
written in them; do not repeat a finding's figures, because the app prints the finding
beside your answer; do not mention breathing, emotion, pronunciation, accent or clarity of
consonants, because none of these were measured; never imply the recording was compared with
the character's real voice; choose the segment where the change matters most, judging by
what the words mean.

The *data* is, in order: the delivery profile in words; the recording's length and
language, with any warnings; the transcript, one line per segment with the pauses between
them; the bands; and the findings, grouped as issues, strengths and context:

```
seg-1 [0:00.0-0:04.1] 236 WPM: "You clearly do not know who you are talking to, so let me clue you in."
(pause-1: 1.3 seconds of silence)
seg-2 [0:05.4-0:06.6]: "I am not in danger."
…
Issues, most important first (corrections come only from these):
f1: You spoke at 240 WPM while speaking (pauses left out). That is fast: over 200 WPM.
    Aim: Slow your overall pace. Technique: half speed with stretched vowels, then a speed between that and normal.
```

Each issue carries the **aim** and a **technique** from its template. The model is not left
to work out which way to push, or to invent a drill method.

**What it is asked to write.** Only this:

- for each of up to three issues: which issue, which segment to practise on, a title, why
  it matters (one or two sentences), and a drill (one or two sentences);
- for one or two strengths: one sentence on what to keep doing.

It is **not** asked for the delivery summary, the targets for the next take or the caveats.
Those are written by code.

**How its answer is confined.** Ollama can force a model's output to fit a JSON schema, so
that text which does not fit cannot be produced at all. The schema built for each recording
lists the exact finding IDs that may be named as corrections (the issues), the exact ones
that may be named as working (the strengths), and the exact segment IDs that exist. The
model therefore cannot name a finding or a segment that does not exist, and cannot turn a
strength into a correction. The schema also fixes how many corrections to return; the code
checks all of this again when the answer arrives, and does not rely on the schema alone.

**Fitting the transcript in.** A model can only take in so much text at once. Text is
counted in **tokens**, pieces of roughly a word or part of one. Measured on this model:
English words took about 4 characters per token (1.05 tokens per word), Hindi in Devanagari
about 2 characters per token (2.14 tokens per word), and Hindi in Roman letters about 2.9.
Digits and punctuation cost far more: a line such as `seg-5 [0:15.7-0:17.8] 209 WPM:` is
mostly tokens of one or two characters.

The model is given room for 8,192 tokens. Before sending, the code estimates the size of
the prompt and makes it fit, in this order:

1. **The full layout**, as shown above: start and end time, WPM, every pause.
2. If that does not fit, **a leaner layout**: each phrase with its start time only, no WPM,
   and only the pauses of a second or more. Timings are trimmed before words, because they
   cost the most and the findings already carry the timings that matter.
3. If that still does not fit, **each phrase is cut** to its first 40 words, then 25, 15,
   10, 6, 3, until it does. Only now have words been lost, and the coaching says so in its
   caveats.
4. In the extreme case, only the phrases the findings point at are listed.

The estimate is deliberately high: letters at 3.5 characters per token, every digit and
punctuation mark as a whole token, other scripts at 1.6 characters per token. Compared with
what the model really counted:

| Prompt | Estimated | Real |
| --- | --- | --- |
| 22-second English recording, full layout | 1,781 | 1,330 |
| 8-second Hindi recording, full layout | 1,549 | 1,150 |
| 133-second English recording, full layout | 3,006 | 2,331 |
| A stand-in for a 10-minute recording (the 133-second one stitched end to end: 108 phrases, 1,665 words), leaner layout, no words cut | 6,603 | 5,134 |

An earlier version of the estimate counted every character alike and came out 27% too *low*
on a transcript listing. It was found by comparing against the model's own count, which is
why that comparison is now a test.

**Settings used:** temperature 0.3 (a little randomness, so a second try can differ; see
decision S32), an answer of at most 600 tokens, a time limit of 180 seconds per answer.

### Step 3: checking the answer

Confining the *shape* of the answer does not confine its *wording*: the model could still
write "you spoke at 150 WPM" inside a sentence. So the wording is checked, by ordinary code
(`grounding.py`), against the text the model was shown:

| In the model's wording | Rule | Example that fails |
| --- | --- | --- |
| A figure with a unit: WPM, seconds, milliseconds, dB, Hz, semitones, % (also written as words: "two seconds") | Must match a figure of the **same unit** in what it was shown, within 3% or half of its own last digit, whichever is larger | "Aim for 150 WPM" when no 150 WPM was measured |
| A time such as 0:55 | Must be within 0.6 s of a time that appears in the measurements | "At 1:15 you rushed" in a 22-second recording |
| "segment 9", "pause 7" | That segment or pause must exist | |
| Four or more words in quotation marks | Must appear, in that order, in the transcript | A line the speaker never said |
| A finding named | Must be one it was allowed to name, and not named twice | |
| Any part | Must not be empty or absurdly long | |

Not treated as measurements: counts in a drill ("repeat 3 times", "count to 5"), the phrase
"100%", and counting aloud in quotation marks ("one thousand one").

What happens next:

1. If everything passes, the answer is used.
2. If anything fails, the answer is sent back **once**, with the list of what was wrong
   ("“150 WPM” is not one of the measured figures"), and the model is asked to write it
   again.
3. Whatever still fails after that is **removed**, item by item, and the coaching carries a
   note saying how many suggestions were left out.
4. If no correction survives, or the answer was not valid JSON twice, the templates are
   used instead and the note says why.

### What the coaching contains

| Part | Written by | The spec's requirement it meets |
| --- | --- | --- |
| Delivery summary: Pace, Pauses, Voice, Clarity | Code, from the findings | A short summary grounded in computed values |
| Up to three corrections, most important first | The AI model (or templates), each tied to one finding | Top 3 corrections, ordered by impact |
| "Measured" and "Practise on" for each | Code: the finding's statement, and the segment's own words and times | Exact timestamps and segments, with a reason grounded in measured data |
| A drill for each | The AI model (or templates) | A concrete drill for each correction |
| What is already working | The AI model (or templates), each tied to a finding | What is working, supported by measurements |
| Targets for the next take | Templates, one per correction | Next-take targets based on this recording and profile |
| Uncertain or not measured | Code: the analysis warnings, what the profile asks for that cannot be measured, and that breaths, emotion and pronunciation are not measured | A clear note when estimates are uncertain or unavailable |

There can be **fewer than three corrections**. If only one thing measured works against the
profile, one correction is given. Nothing is invented to fill the list.

There can be **none**. A recording with no speech, or under three seconds, gets no coaching
at all, and the reason is shown. A recording in which nothing works against the profile gets
no corrections, and says so.

Since Phase 6 two things the user says reach the coaching. Their **labels on pauses**
(intentional or accidental) change how the pause findings are worded and judged, and are
shown to the AI model beside each pause. Their **ratings of corrections** (useful or not
useful) can move a kind of issue down the order in which issues are offered. Neither
changes a measurement, and the checks on the model's answer are exactly as described
above. Both are explained in section 15.

### A voice goal

Phase 9 added the two findings about where the voice sits, and one choice the speaker
makes when recording: **no goal**, **keep my voice lower**, or **keep my voice higher**.

**With no goal**, the two findings are context. They say where the voice sat, and are
never an issue, a strength or a correction:

```
Your pitch sat at a median of 118 Hz. That is in the lower range (under 145 Hz), 45% of the
way into it. A voice in that range is typically heard as masculine.
```

**With a goal**, code adds how the phrases stood against it, and the finding gets a role:

```
Your pitch sat at a median of 152 Hz. That is in the neutral range (145 to 175 Hz). A voice
in that range could be heard either way. Your goal is to keep your voice in the lower
range: 2 of 4 phrases stayed in it for pitch. Furthest from it: segment 3 at 190 Hz,
segment 2 at 150 Hz.
```

| Where the recording sat | Its phrases | Role | Weight |
| --- | --- | --- | --- |
| In the goal's range | All in it | **Strength** | — |
| In the goal's range | Some left it | Issue | 0.3 to 0.7, growing with the share that left |
| In the neutral range | — | Issue | 0.7 |
| In the opposite range | — | Issue | 1.0 |

The weight decides the order of the corrections, as for every issue. A whole recording
outside the range matters most; a few stray phrases least.

The correction is practised on **the phrase furthest from the range**, which code chooses,
and the screen puts a Play button beside it. There are four templates, by what is to move
and which way:

| Finding and goal | Title | The technique the drill is built on |
| --- | --- | --- |
| Pitch, lower | Keep your pitch in the lower range | A comfortable low hum that slides straight into the line, with the end of the phrase falling |
| Pitch, higher | Keep your pitch in the higher range | A comfortable higher hum that slides into the line, with the end of the phrase kept up |
| Resonance, lower | Deepen your resonance | The open throat of a beginning yawn, kept while the line is said slowly on a relaxed "aw" |
| Resonance, higher | Brighten your resonance | A slight smile and a forward tongue, as for "ee", with the sound placed at the front of the mouth |

These are ordinary exercises from voice training, chosen to be gentle. They are not
medical advice, every one of them ends "stop if your throat feels strained", and a
coaching with a goal adds this to its "uncertain or not measured" list:

> The voice ranges are this app's own rough ranges. They describe how a voice is typically
> heard, not who is speaking, and they are not a judgement of any voice. A voice changes
> through weeks of gentle practice: stop if your throat feels strained, and consider a voice
> coach or a speech therapist for guidance.

With a goal the delivery summary also gains a fifth line, "Voice range".

**What the AI model is and is not shown.** It is shown the measurements, the range and the
goal, and the technique. It is **not** shown the sentence "A voice in that range is
typically heard as masculine" (or "feminine"). In the first real run, with that sentence in
front of it, the model wrote that the actor should lower their pitch "to avoid being
perceived as feminine". Nothing measured says that, and it turns a description of a sound
into a remark about a person. Two things were done:

1. The sentence is taken out of what the model reads. The user still sees it, written by
   code, beside the measurement.
2. The model's wording is checked for words about the speaker (man, woman, male, female,
   masculine, feminine, boy, girl, gender, sex and the like) whenever a goal is set. A hit
   is sent back with the reason and, if it comes back again, that correction is removed,
   exactly like an unmeasured figure. Words inside quotation marks are not counted: the
   actor's own lines may well contain them.

The system prompt also gained a rule: talk only about the sound and the range, never say
or guess anything about the actor's sex or gender, and never call a voice wrong. As the
table below says of another rule, an instruction lowers how often something happens; it
is the two steps above that prevent it.

The same run showed the model writing "On seg-2, start with a low hum…", the internal name
of a phrase. Code now rewrites `seg-2` as "segment 2" in everything the model writes.

### When the model is not available

| Situation | What the user gets |
| --- | --- |
| Ollama is not running | Template coaching, with "Ollama is not running…" and the command to start it |
| The model is not installed in Ollama | Template coaching, and the `ollama pull` command to run yourself |
| The model takes longer than the time limit | Template coaching, and a note |
| Its answer fails the checks entirely | Template coaching, and a note |
| `OLLAMA_BASE_URL` points at another computer | Template coaching; nothing is sent |
| AI coaching is switched off (`AI_COACHING=off`) | Template coaching |

In every case the measurements are complete, and the model can be asked again later without
recording or uploading anything (the "Write the coaching again" button).

### Delivery profiles

Walter White, Joker and Thomas Shelby are **descriptions of a delivery style in words**, not
measurements of any actor's voice. The app has no reference recording of them and does not
claim to compare against one. A real, measured comparison only happens when the user
supplies a reference recording themselves, and it is a separate thing from the profile
(section 14).

| Profile | In a sentence | Measurements it depends on most | Not measured |
| --- | --- | --- | --- |
| Walter White | Controlled and deliberate | Pace variation (low), median pause (high), loudness variation (low) | Clarity of consonants |
| Joker | Expressive and unpredictable | Pace variation (high), pitch variation (high), loudness variation (high) | Whether a contrast was purposeful |
| Thomas Shelby | Composed and economical | Speech-active WPM (low), longest pause (high), loudness variation (low) | Crispness of phrasing |
| Custom / neutral | No style target | None singled out | — |

There are deliberately **no target numbers** in a profile, such as "Walter White speaks at
130 WPM". Any such number would be invented. A profile says only which way it leans; the
figures in a coaching target ("towards 140 WPM or below") are the app's own bands, the same
for every profile, and the screen says so beside them.

### What was seen with the real model

About fifteen coaching runs were made with the real `llama3.1:8b` while building this, on
four synthesised recordings (three English, one Hindi) across all four profiles. This is a
small sample of one kind of input, and the advice was read by the developer, not judged by
a speaking coach. With that said:

| Observation | What was done about it |
| --- | --- |
| Every answer was valid JSON of the right shape, and named only real findings and segments | Expected: the schema makes anything else impossible |
| None of the runs had an answer fail the checks on wording | The retry and removal steps are therefore proven only by the automated tests, which script a misbehaving model |
| Asked for a drill with no guidance, it suggested "whisper it, then full voice" for a correction about keeping the volume *level* | Each issue now carries its aim and technique (decision S35) |
| Asked for a title, it described the problem ("Faster pace") instead of the remedy | Same fix; titles now read "Slow Down Your Pace" |
| Asked for its own next-take targets, it once advised against "holding pauses too long", which no finding said | Targets are now always written by template (decision S30) |
| It tends to choose the first phrase to practise on, whatever the correction | Left as it is; the phrase shown is always real |
| Its reasons are often generic ("this undermines the character's authority") | Left as it is; the measured line beside each reason carries the specifics |
| Hindi lines were quoted back in Devanagari, exactly as transcribed | — |
| Told not to mention emotion, it still once ended a drill with "focusing on the different pitches and emotions" | Left as it is, and not checked by code: it is an instruction to the actor, not a claim that emotion was measured. It shows that an instruction to the model lowers how often something happens; it does not prevent it |
| With a voice goal (Phase 9): shown "typically heard as feminine", it advised lowering the pitch "to avoid being perceived as feminine" | That sentence is no longer shown to the model, and its wording is checked for words about the speaker ("A voice goal", above). The two coaching runs of the final end-to-end check had none |
| With a voice goal, its "why" still reaches for character ("a lower pitch can undermine a confident tone") | Left as it is: the same generic reasoning as elsewhere, and it is about the delivery. Not checked by code |
| It named a phrase by its internal label, "On seg-2…" | Code rewrites the label as "segment 2" |
| Time for the model, per coaching | 20.9 to 51.8 seconds on an Apple M2 with 16 GB, for recordings up to 133 seconds. The first answer after Ollama has been idle includes about 7.5 seconds to load the model. For the 10-minute stand-in, 66 seconds, most of it spent reading the prompt |
| Speed | About 15 tokens of answer per second; about 116 tokens of prompt read per second |
| Memory while loaded | 5.8 GB, as reported by Ollama. It stays loaded for about five minutes after its last use, which is Ollama's default |

## 14. Comparing with a reference recording

All code for this section is in `backend/app/comparison/`, plus
`backend/app/pipeline/waveform.py` for the picture.

### What a reference is

A **reference** is a recording you supply yourself, for example the original performance of
the monologue you are practising. It goes through exactly the same pipeline as one of your
own takes (sections 1 to 12): the same speech detection, the same recogniser, the same
measurements, the same thresholds. The only differences are that it is listed separately,
has a name, and gets no coaching.

This is the first place in the app where one recording is set against another. It is what
makes it possible to say something the delivery profiles never could:

| Kind of statement | Example | Where it comes from |
| --- | --- | --- |
| A measurement of your take | "You paused for 2.6 seconds here" | Sections 1 to 12 |
| A judgement against a profile described in words | "For Walter White, pauses this short work against the profile" | Section 13 |
| A **measured comparison with a real recording** | "The reference pauses for 6.1 seconds here. You did not pause" | This section |

The three are kept apart on screen and in the code. In particular the comparison does not
go through the AI model at all, and the profile coaching never mentions the reference.

**Which two recordings are compared (Phase 8).** A reference is the original recording of
a **monologue**, and a take recorded while practising that monologue belongs to it. A take
is compared with the original of its own monologue and with no other, and a take made in
General Practice, which belongs to no monologue, is compared with nothing. Before Phase 8
any take could be set against any reference the user picked from a menu, including one of
different words. The arithmetic below is unchanged; what changed is that the pair is now
always one that was meant.

When the original's words are corrected, or it is measured again, the monologue gets a new
revision of its reference, and its takes are from then on compared with that one. A
comparison is worked out when it is asked for and stored nowhere, so nothing has to be
recalculated: the next time a take is opened, it is set against the newest revision.

### The idea in one picture

```
 your take (measured)            the reference (measured)
        │                                │
        └───────────────┬────────────────┘
                        ▼
 ┌────────────────────────────────┐  align.py
 │ 1. Line up the words           │  which word of one is which word of the other
 └───────────────┬────────────────┘
                 ▼
 ┌────────────────────────────────┐  compare.py
 │ 2. Pause by pause              │  for each pause: does the other recording pause at
 │                                │  the same place in the words, and for how long
 ├────────────────────────────────┤
 │ 3. Phrase by phrase            │  the pace of the same words in each recording
 ├────────────────────────────────┤
 │ 4. The recordings as wholes    │  their headline figures, side by side
 └───────────────┬────────────────┘
                 ▼
 ┌────────────────────────────────┐
 │ 5. The biggest differences     │  the few that a listener would notice most
 └────────────────────────────────┘
```

Everything here is arithmetic on the two stored results. No audio is read, nothing is
stored, and neither result is changed. A comparison took between 3 and 31 thousandths of a
second in the runs measured here, so it is worked out each time it is asked for.

### Step 1: lining up the words

Two recordings of the same passage never have the same transcript. A word is misheard in
one, dropped in the other, or spelt differently. So the first job is to work out which word
in the reference is which word in the take.

**Match keys.** Each word is first reduced to a *key*: lower case, punctuation removed, and
combining marks removed. In English that makes "Danger," and "danger." the same. In Hindi,
combining marks are the vowel signs, the nasal dot and the half-letter mark, which is
exactly where the recogniser's spelling varies:

| The recogniser wrote | Key |
| --- | --- |
| खतरे, खत्रे | खतर |
| हूँ, हु | ह |
| आदमी, आद्मी | आदम |
| दरवाज़ा, दर्वाजा | दरवज |

Some genuinely different words get the same key this way (में and मैं both become म). That
is accepted, because of what comes next.

**The longest common run.** The two lists of keys are then matched by finding the longest
list of words that appears in both *in the same order*. In computing this is called the
longest common subsequence. Because order must be preserved, a stray equal key cannot pull
the line-up out of place: it would have to match without disturbing its neighbours.

**Coverage.** The share of the reference's words that found a partner in the take decides
how far the comparison goes:

| Coverage | Status | What is compared |
| --- | --- | --- |
| 60% or more | `matched`: the same passage | Everything |
| 30% to 60% | `partial` | The parts that line up; the note says so |
| Under 30% | `unmatched`: different words | Only the recordings as wholes |
| One has no recognised words | `no_words` | Only the recordings as wholes |

Measured on the test recordings: an English take against an English reference of the same
lines matched 30 of 31 words (97%); a Hindi take against a Hindi reference matched 17 of 19
(89%), the two misses being the two forms of one word, which the recogniser spelt with an
extra letter in the reference (ख्यत्री where the take had खत्रे); an English take against a Hindi reference matched 0%.

### Step 2: pause by pause

For each pause in the reference, the question is: does the take pause at the same place in
the words?

A pause sits between the last word of one phrase and the first word of the next. The
matched words nearest to it on either side (at most 3 words away) have partners in the take.
Those two partner words mark the same place in the take, and then:

| In the take, those two words are… | The row says |
| --- | --- |
| in **different phrases** (there is a pause between them) | `both`: both pause here. The difference in length is given |
| in the **same phrase** | `reference_only`: the reference pauses, you did not |
| not found (no matched word within 3 words on one side) | `unplaced`: could not be located in your take. It is **not** called missing |

The same is then done from the take's side, to find pauses the take makes where the
reference runs on: `take_only`.

Two details matter:

- **Pauses are located by phrase, not by word time.** It would seem natural to say "the
  take's pause must lie between the end of one word and the start of the next". That was
  the first version, and it was wrong. The recogniser's word times are loose around a
  pause: the first word after a pause is often given a start time *inside* the pause. Comparing
  a two-minute recording with an exact copy of itself, that version reported 6 of the 23
  pauses as missing on one side and extra on the other. Which phrase a word belongs to is
  decided once, by the pipeline, and a pause is by definition the gap between two phrases,
  so the question "is there a pause between these two words?" is now answered by asking
  whether they are in the same phrase. The same self-comparison now gives 23 of 23 pauses
  matched with a difference of zero.
- **If the take makes two pauses where the reference makes one**, the longer of the two is
  taken as "the" pause.

### Step 3: phrase by phrase

For each phrase of the reference, the pace of the same words in the take:

```
reference pace = matched words of the phrase ÷ time from the first to the last of them
take pace      = the take's words over the same stretch ÷ that stretch's time,
                 minus any pauses the take makes inside it
```

Both are taken over the same stretch of words, and pauses are left out of both, as
everywhere else in the app. A phrase is compared only when at least 60% of its words were
matched, it has at least 3 words, and the stretch lasts at least 1.5 seconds in both
recordings. Otherwise it is listed, can still be played in both, and carries no pace.

This figure rests on the recogniser's word times, which are good to about a tenth of a
second. Over a three-second phrase that is a few per cent. It is labelled as an estimate.

### Step 4: the recordings as wholes

Fourteen headline figures side by side: length, time speaking, words, speech-active WPM,
whole-clip WPM, pace variation, number of pauses, median, longest and total pause, pause
share, loudness variation, pitch variation and pitch range.

**Three things are deliberately left out:**

| Not compared | Why |
| --- | --- |
| How loud each recording is | It depends on the microphone, the distance and any processing, not on the performance |
| How high each voice is (median pitch) | Two voices differ in pitch. Only how much each one *moves* is compared, in semitones |
| The sound waves themselves | The waveform is a picture (see below) and is never measured |

Loudness *variation* is included, with a note: a film clip has usually been compressed,
which evens out its loudness, so this one is not only about the performance.

If the take covers more or less of the text than the reference, the totals differ for that
reason alone. The table says so.

### Step 5: the biggest differences

The few differences a listener would notice most, largest first, each as one plain
sentence with both versions to listen to:

| Difference | Listed when | Example |
| --- | --- | --- |
| A pause only the reference makes | It lasts 1 second or more | "The reference pauses for 6.1 seconds after “No”. You did not pause there." |
| A pause only the take makes | It lasts 1 second or more | "You paused for 1 second after “I am not in danger”. The reference does not pause there." |
| A pause both make, of different length | The lengths differ by at least 0.5 s and by at least 40% of the reference's | "The reference holds 1.6 seconds after “…I am the danger”; you held 2.6 seconds." |
| A phrase at a different pace | It differs by 25% or more | "You said “…” at 240 WPM. The reference says it at 120 WPM, so you were 100% faster." |
| A different overall pace | It differs by 15% or more | "Overall you spoke at 230 WPM while speaking; the reference speaks at 180 WPM." |

To put pauses and paces in one order, each is given a weight in rough seconds of silence: a
missing pause weighs its own length (at most 3), a pause of different length 0.8 of the
difference, an extra pause 0.7 of its length, and a phrase 3 times the share by which its
pace differs. At most five are listed.

The wording is always "difference", never "mistake". The reference is the target you chose,
but whether to follow it at each point is a decision about a performance, and the app does
not make it.

### The settings

In `comparison/settings.py`, as `ComparisonSettings`. They are sent with every comparison.

| Setting | Default | Meaning |
| --- | --- | --- |
| `matched_coverage` | 0.6 | From this share of matched words, the two are the same passage |
| `partial_coverage` | 0.3 | From here, partly |
| `max_anchor_gap_words` | 3 | How far from a pause a matched word may be and still locate it |
| `phrase_min_coverage` | 0.6 | Share of a phrase's words that must be matched to compare its pace |
| `phrase_min_words` | 3 | Fewest words in a phrase whose pace is compared |
| `phrase_min_seconds` | 1.5 | Shortest stretch over which a pace is compared |
| `notable_pause_seconds` | 1.0 | A pause only one recording has is listed from here |
| `notable_pause_change_seconds` | 0.5 | A pause both have is listed when the lengths differ by this… |
| `notable_pause_change_ratio` | 0.4 | …and by this share of the reference's |
| `notable_phrase_pace_ratio` | 0.25 | A phrase is listed when its pace differs by this share |
| `notable_overall_pace_ratio` | 0.15 | The overall pace is listed when it differs by this share |
| `max_differences` | 5 | How many of the biggest differences are listed |
| `pause_context_seconds` | 1.5 | Audio played either side of a pause |
| `version` | 1 | Goes up whenever a default changes |

Like the analysis thresholds and the coaching bands, these are this project's own choices.

### The waveform: a picture, not a measurement

The screen can draw the sound waves of the two recordings on one timeline. This is the one
part of the app that is **only** for looking at.

**How it is made.** A recording has far too many samples to draw: ten minutes is 9.6
million. So when a recording is analysed, the samples are grouped into at most 2,000
buckets (and never finer than 5 milliseconds each), and only the lowest and the highest
sample of each bucket is kept. Drawn as a filled band between those two lines, that looks
the same as drawing every sample, and it is small: about 21 KB for a 17-second recording
and 23 KB for a 133-second one.

**How it is kept apart.**

- It is stored in its own column, not inside the measured result, and is sent only when the
  screen asks for it. A screen that never switches the waveform on never receives it.
- Nothing reads it. Speaking rate, pauses, loudness and pitch all come from the samples
  themselves, by the methods in sections 3 to 9. A test analyses the same recording with
  and without the waveform step and checks that the measured results are identical.
- The comparison in this section does not use it either.

**What it shows honestly.**

- Each recording keeps its real length. A 17-second reference next to a 22-second take is
  drawn 17 and 22 seconds long; neither is stretched to match the other.
- The two are not lined up automatically. You can shift your take by a number of seconds;
  the number is yours, it is shown, and it changes only the picture.
- Height is **relative waveform amplitude**: 1.0 is the loudest a recording can be. It is
  not loudness in the room. By default both are drawn on that same scale, so a quietly
  recorded clip looks thin. An option stretches each to its own loudest point so that its
  shape can be seen; it is off by default and says, when on, that it hides any real
  difference in level.

### The original as a script

Steps 2 and 3 of Daily Practice show the original recording as a script: one line per
phrase, the pause after it, and the words that stood out.

```
 1. I am not in danger, Skyler.
 ‖ pause 1.6 s
 2. I am the danger.
 ‖ pause 1.1 s
 3. A guy opens his door and gets shot, and you think that of me?
                                            ‾‾‾ ‾‾‾‾‾
```

Nothing in it is new. It is the reference's stored result, laid out differently:

| On the script | Is | From section |
| --- | --- | --- |
| A line | One segment: speech with no pause inside it | 4 |
| `‖ pause 1.6 s` | The pause between that segment and the next, at its measured length | 4, 7 |
| `‖‖ long silence` | A pause of 5 seconds or more | 4 |
| An underlined word | An emphasis candidate: at least 3 dB louder or 2 semitones higher than the speaker's typical word | 10 |
| ▲ faster, ▼ slower | A phrase at least 25% from the speaker's own typical pace | 6 |

So everything section 10 says about emphasis candidates holds here. An underlined word
*measured* louder or higher. That does not prove it was stressed on purpose, and a word
stressed by slowing down or by a pause before it is not underlined at all. The legend
under the script says so. The words themselves are the recogniser's, and are corrected
where the original is studied, in step 1.

## 15. Feedback and calibration

The analysis makes mistakes, and only the speaker knows which. A pause the app found may
have been a slip. A silence the app ignored may have been a real pause. The words may be
wrong. This section is about what the app does when the user says so.

Two rules hold throughout:

1. **Feedback never changes a stored measurement.** A pause that was measured stays in
   every pause figure, at its measured length, whatever is said about it.
2. **Numbers are changed by fixed rules, never by the AI model.** The model decides
   nothing in this section. It appears once, near the end, where it is allowed to choose
   which of the user's own notes to show first, and nothing reads its choice.

### The idea in one picture

```
                         one piece of feedback
                                  │
            ┌─────────────────────┼──────────────────────┐
            ▼                     ▼                      ▼
         A LABEL               A REPORT               A RECORD
   "this pause was       "a pause was missed     "the WPM looks too high"
    accidental"           here"                  "the words are wrong"
            │                     │                      │
            ▼                     ▼                      ▼
   changes how the       counts towards moving    changes nothing by itself.
   coaching reads        ONE setting, chosen      WPM: shows a review of what
   that pause            from what was            went into the figure.
                         measured at that spot    Words: corrected only if you
            │                     │               supply them (a new revision).
            │                     ▼
            │            enough reports that agree?
            │              no → nothing moves
            │              yes → the setting moves one small step,
            │                    inside its allowed range
            ▼                     ▼
    the next coaching     recordings analysed from now on
    written for this      (results already made keep the
    result                 settings they were made with)
```

Which of the three a piece of feedback is depends only on its category and on what was
measured. Code: `feedback.py` (`classify`).

### The ten kinds of feedback

| What the user says | About | Kind | Counts towards |
| --- | --- | --- | --- |
| "Intentional: I meant this pause" | A pause | Label | Nothing |
| "Accidental: I lost my place" | A pause | Label | Nothing |
| "Not a pause: I was still speaking" | A pause | Report, if the pause is shorter than 800 ms | Raising the minimum pause |
| "Too short to split the phrase here" | A pause | Report, if the pause is shorter than 800 ms | Raising the minimum pause |
| "A pause was missed here: it should be two phrases" | A phrase and a time | Report, if a silence of 250 ms or more was heard there | Lowering the minimum pause |
| "The WPM looks too high" / "too low" | A phrase, or the whole recording | Record | Nothing; opens a review |
| "The words are wrong" | A phrase | Record; or a correction, if the words are supplied | Nothing |
| "Useful" / "Not useful" | A correction in the coaching | Report | Raising or lowering the priority of that kind of correction |

The brief lists "this segment was incorrectly split" and "these two segments should be
separate" as feedback of their own. In this app a pause is exactly what ends a segment
(section 4), so a wrong split *is* a pause that should not have counted, and two segments
that should be separate *are* a missed pause. They are offered under those wordings on the
pause and on the phrase, and counted the same way.

### What is looked up when a report arrives

A report is only as good as the measurement behind it, so each one is checked against what
the detector heard.

**A report about a detected pause** carries that pause's measured length.

**A report of a missed pause** carries a phrase and a time. The app looks among that
phrase's short silences (section 4) for one within half a second of the time. If there are
several, it takes the one whose middle is nearest.

```
 phrase:   ████████████░░░████████████████░██████
                       ↑                  ↑
              a short silence      a short silence
              of 356 ms            of 132 ms

 the user marks a time near the first one
   → "a silence of 356 ms was heard there, and it was under the 500 ms minimum"
```

The length found, the minimum pause the recording was analysed with, and the calibration
version are stored with the feedback, as its **features**.

### Pointing at the moment: a silence, a word, or the player

The rule above needs a time. The screen offers four ways of giving one, and all four end
in the same rule:

| The user picks | The time sent |
| --- | --- |
| One of the short silences listed for the phrase | The middle of that silence |
| A word: "the pause came after this one" | Halfway between the end of that word and the start of the next, kept inside the phrase |
| Where the player is | The player's position |
| "I cannot say exactly where" | None: the report is saved and cannot count |

**Why a word needs care.** Word times come from the speech recogniser, not from the
detector that finds silences, and the two do not agree exactly: a word's end is often
drawn a little into the silence after it. So "after this word" gives a moment *near* the
silence, not inside it. That is what the half second of tolerance is for, and it is the
same half second whether the moment came from a word or from the player.

```
 words:      … who    I    am │        │ so   say   my …
 silence:                       ░░░░░░░░
                               ↑
              halfway between "am" and "so": 4.41 s
              the silence runs from 4.29 s to 4.65 s  →  found
```

Measured on the two test recordings, for every short silence the detector heard: the word
before the silence was looked up, the moment after that word was reported, and the answer
was compared with the silence.

| Recording | Word picked | Moment sent | The silence | Found? |
| --- | --- | --- | --- | --- |
| Take | "to" | 2.71 s | 324 ms from 2.62 s | Yes |
| Take | "Skyler" | 8.09 s | 356 ms from 7.97 s | Yes |
| Take | "shot" | 14.55 s | 356 ms from 14.46 s | Yes |
| Take | "No" | 17.69 s | 132 ms from 17.73 s | Yes |
| Reference | "am" | 4.41 s | 356 ms from 4.29 s | Yes |
| Reference | "knocks" | 9.34 s | 356 ms from 9.31 s | Yes |

Six of six, each within 0.12 s of where the silence starts. A word with no silence within
half a second was also tried: the report was saved, counted towards nothing, and said "the
detector heard speech straight through at that point".

Two limits. All six are from clean synthesised speech; a real voice, with words that run
together, may be timed less well. And half a second is wide enough that a word next to
the right one can find the same silence, which is the forgiving direction: the screen
shows which silence was found before the report is saved.

### From a report to a setting

| Report | What was measured | Counts towards | Why |
| --- | --- | --- | --- |
| Not a pause / wrong split | The pause lasted under 800 ms | Raising the minimum pause | A higher minimum would no longer report it |
| Not a pause | The pause lasted 800 ms or more | Nothing | No minimum pause explains a silence that long. If the user was speaking, the detector did not hear them, and no adjustable setting would have made it (see below) |
| Wrong split | The pause lasted 800 ms or more | Nothing | A silence that long ends a phrase at any setting |
| Missed pause | A silence of 250 ms or more near the time | Lowering the minimum pause | A lower minimum would have caught it |
| Missed pause | A silence shorter than 250 ms | Nothing | Nothing shorter than 250 ms is ever counted as a pause |
| Missed pause | No silence near the time | Nothing | The detector heard speech straight through; no pause setting could have caught it |
| Missed pause | No time given, or a result from before short silences were kept | Nothing | It cannot be checked against anything |
| Useful / Not useful | The kind of finding the correction was about | The priority of that kind | |

Every row leads to **at most one** setting. When a report counts towards nothing it is
still saved, and the screen says why in a sentence.

### When a setting moves

One report never moves anything. The reports about a setting that have not yet been used
are looked at together, most recent ten only, and the setting moves when all of these hold:

| Rule | Value | Why |
| --- | --- | --- |
| Enough reports point the same way | 3 | One or two can be a slip or an odd moment |
| They come from more than one recording | 2 recordings | One unusual recording must not retune the app for every later one. Revisions of one recording count as one |
| At least one of them is about one of the user's own takes | 1 report | A reference recording is often a film clip: another voice, another room, sometimes music. See "Feedback on a reference recording" below |
| They are most of what was said | 75% of the reports looked at | Three for and two against is a disagreement, not a signal |
| The move is not straight back the way the setting just came | 5 reports instead of 3 | So a setting cannot flip back and forth |
| The setting is not already at the end of its range | | |
| Automatic adjustment is switched on | | The user can switch it off |

Until then the screen says "still calibrating" and shows the count: "2 of the 3 reports
needed for lowering it, from 1 of the 2 recordings needed". When the only thing missing is
a report on a take, it says that: "4 of the 3 reports needed for lowering it. All of them
are about reference recordings, and a setting moves only once a take of your own shows the
same thing."

Two more rules keep it honest:

- **A report is used once.** When a setting moves, every report that was waiting on it is
  spent, whichever way it pointed. The next move needs new reports.
- **A report that has been answered stops counting.** A missed silence of 420 ms needs no
  further lowering once the minimum pause is 400 ms. So a report made on an old result,
  about a value that has since changed, counts only if it would still be a complaint today.

Code: `calibration/engine.py` (`tally`, `still_applies`, `propose`).

### How far it moves

The minimum pause sits on a grid of 50 ms and moves 50 or 100 ms at a time. Where it lands
is steered by the silences that were reported: it goes to the grid value that would have
got the *typical* (median) reported silence right, but never more than 100 ms in one move.

| Now | Reported | Typical | Would be right at | Moves to |
| --- | --- | --- | --- | --- |
| 500 ms | Missed silences of 380, 420, 450 ms | 420 ms | 400 ms (420 counts as a pause from 400) | **400 ms** |
| 500 ms | Missed silences of 470, 480, 490 ms | 480 ms | 450 ms | **450 ms** |
| 500 ms | Missed silences of 260, 300, 320 ms | 300 ms | 300 ms | **400 ms** (the 100 ms limit) |
| 500 ms | False pauses of 520, 560, 610 ms | 560 ms | 600 ms (560 is no longer a pause at 600) | **600 ms** |

In the third row the reported silences are still missed after the move. That is on
purpose. The user reports them again on recordings made with the new value, and the
minimum pause moves again: a setting is walked to where it should be in small confirmed
steps, never thrown there by three clicks.

A priority moves by 0.2 at a time.

Code: `calibration/engine.py` (`next_value`).

### What can be adjusted, and what cannot

| Setting | Default | Allowed range | One move | Moved by |
| --- | --- | --- | --- | --- |
| **Minimum pause** | 500 ms | 250 to 800 ms | 50 or 100 ms | Missed pauses (down); false pauses and wrong splits (up) |
| **Priority of a kind of correction** (fourteen of them: overall pace, pause length, pitch, a rushed phrase, and since Phase 9 the range the pitch sits in and the resonance, …) | 1.0 | 0.4 to 1.0 | 0.2 | "Not useful" (down); "Useful" (back up) |

- **250 ms** is the floor because a shorter silence is usually part of pronouncing a word
  (the closure before a "p" or a "t"), not a pause between words.
- **800 ms** is the ceiling because a silence that long is a pause for any speaker.
- **A priority never reaches zero.** A kind of correction can be moved down the list; it
  cannot be switched off, and the measurement behind it is always still shown.

Everything else is fixed, and is listed on the calibration screen so that nothing is
hidden: the 1-second and 5-second pause labels, the 2 seconds and 3 words a phrase needs
for a trusted WPM, the 180 WPM review flag, the coaching bands.

**The speech detection threshold is deliberately fixed.** The brief suggests that feedback
could adjust the detector's sensitivity, so this was measured on the real detector before
deciding. `vad_threshold` is how sure the detector must be that a sound is speech (0.5 by
default).

| Test, on the real detector | 0.35 | 0.50 | 0.65 |
| --- | --- | --- | --- |
| Three clean recordings (17 s, 22 s and 133 s): phrases and pauses found | 4, 6 and 24 phrases | The same | The same |
| The same: the measured length of a pause | Up to 64 ms shorter | — | Up to 64 ms longer |
| A recording with steady noise as loud as the voice | 4 phrases | The same 4 | The same 4 |
| A phrase made 30 dB quieter than the rest | Found whole | Found whole | Starts 0.5 s late |
| A phrase made 40 dB quieter: how late its start is found | 0.9 s late | 1.5 s late | 1.7 s late |
| A phrase made 45 dB quieter | Lost | Lost | Not run |

And outside that range: at 0.1 the clean recordings lost most of their pauses (23 became
12 in the two-minute one). At 0.2 a real 0.8-second pause disappeared from the recordings
with a quiet phrase and from those with background noise.

So inside the range where the detector is safe, the threshold never added or removed a
pause in any test. What it does change is the measured length of a silence, by up to about
0.06 s either way, and the minimum pause already adjusts for exactly that, in milliseconds
the user can read. Where it would matter most, a phrase spoken far more quietly than the
rest, it helps a little and not enough.

A setting that changes almost nothing a user could see must not be "learned" from their
reports: the app would announce that it had adapted, and the results would stay the same.
Reports the minimum pause cannot explain are therefore saved, with an honest sentence, and
count towards nothing.

Code: `calibration/registry.py`.

### Undo, reset and off

| Control | What it does |
| --- | --- |
| **Undo last adjustment** | Puts back the value the most recent adjustment replaced. Repeating it walks back one adjustment at a time. The reports behind an undone adjustment stay used, so they cannot bring it back |
| **Reset to defaults** | Every setting back to its default; reports that were waiting are set aside. The feedback itself and every result are kept |
| **Adjust automatically: off** | Feedback is still saved and labels still shape the coaching, but no setting moves. Switching it on again acts on reports that built up meanwhile |

None of them changes a result that already exists. Each one adds a version to the
calibration's history (backend document, section 4a).

### Confidence

Each adjustment says how many reports were looked at, how many agreed, and from how many
recordings. From the number that agreed it also gets one word:

| Agreeing reports behind the current value | Confidence |
| --- | --- |
| 3 or 4 | Low |
| 5 to 7 | Medium |
| 8 or more | High |

It is a count turned into a word, nothing more. An adjustment is made as soon as the rules
allow, which is usually at three reports, so a first adjustment is always "low", and the
screen says so. The app never says it has "learned" anything.

### Labels: what they change in the coaching

Marking a pause intentional or accidental is the one kind of feedback that reaches the
coaching directly. It changes how findings (section 13) are *worded and judged*; it never
changes a figure.

Take four phrases with pauses of 0.6 s, 3.0 s and 0.7 s, under a profile that wants a held
silence.

| | No labels | The 3-second pause marked **accidental** | The 3-second pause marked **intentional** |
| --- | --- | --- | --- |
| Pause figures (count, median, longest) | 3 pauses, longest 3.0 s | **Identical** | **Identical** |
| "Held silence" finding | "The longest pause is 3 seconds… That is a held silence." A strength | "Leaving out the 1 pause you marked as accidental, the longest pause is 0.7 seconds… No pause was held for 2 seconds." An issue | "The longest pause is 3 seconds… You marked it as intentional." A strength |
| New finding | — | "You marked 1 pause as accidental: 3 seconds at 0:08.6. It still counts in the pause figures…" An issue, with a drill for getting through that spot | "You marked 1 pause as intentional: 3 seconds at 0:08.6." A strength |

- An **accidental** pause is left out of the *judgement* of pause length and of held
  silence: a slip is not a silence the speaker chose to hold. The measured figures are
  stated first, unchanged; the sentence then says what remains without the slips.
- An **intentional** pause is never turned into an issue, and the AI model is told never to
  advise shortening or removing it.
- The AI model sees the labels beside the pauses in the transcript ("marked accidental by
  the actor"), and its answer is checked exactly as before.

A label takes effect the next time the coaching is written for that result. The screen
says when the labels have changed since the coaching was written and offers to write it
again. Labels do not train any setting: there is nothing measured in a pause that tells an
intended one from a slip, so nothing to adjust.

Code: `coaching/findings.py` (`_pauses`, `_longest_pause`, `_labelled_pauses`).

### Priorities: useful and not useful

Each issue has a weight that decides its place in the list (section 13). A priority is a
number that weight is multiplied by. At 1.0 nothing changes. After three "not useful"
ratings of, say, corrections about pitch, from at least two recordings, the priority of
pitch corrections drops to 0.8, and other issues are more likely to make the top three.

The finding itself is untouched: "Pitch varied by 1.6 semitones…" still appears in the
summary and in the list of findings. Only the order in which issues are offered changes.
"Useful" ratings count the other way, and cancel "not useful" ones.

### "The WPM looks wrong": a review, not a correction

WPM is words divided by speaking time. If it is wrong, the words are wrong or the time is
wrong. A report that it "looks too high" changes no figure. Instead the app lays out what
went into it:

```
 16 words ÷ 4.51 s of speaking × 60 = 212.9 WPM.

 THE WORDS          16 words were counted in this phrase. The speech recogniser was
                    reasonably sure of each of them. A word you did not say, or one word
                    heard as two, makes the WPM too high. …correct them.
 THE SPEAKING TIME  The phrase lasts 4.51 s. There is a pause of 1.64 s after it. Time
                    inside a pause is not speaking time. If you were still speaking during
                    one of them, the WPM comes out too high: mark that pause as "Not a pause".
 FLAGGED FOR REVIEW The figure is above 180 WPM, the level at which the app flags a phrase
                    for review. The figure itself was not changed.
 WORD TIMING        Every word's timing falls inside this phrase.
```

The words, the speaking time and the word timing are always part of it; the other entries
appear when they apply. Each points at the feedback that would correct it: fixing the
words, reporting a missed pause (speaking time too long, WPM too low), or reporting a false
pause (speaking time too short, WPM too high). No figure is multiplied by a correction.

Code: `wpm_review.py`.

### Correcting the transcript

When the user supplies the words of a phrase as they really said them, the app works the
word-based figures out again and stores the outcome as a new **revision**. The result that
was corrected is not touched.

```
 segment WPM  =  corrected word count  ÷  the phrase's own measured length  × 60
```

The length is the one the speech detector measured. It does not change, because the sound
did not change. Example from a real run: the recogniser heard 16 words in a phrase of
4.51 s (212.9 WPM); corrected to 14 words, it is 14 ÷ 4.51 × 60 = **186.3 WPM**.

| Worked out again | Copied exactly as it was |
| --- | --- |
| The phrase's word count, WPM and reliability flags | Where every phrase and pause is, and how long |
| Total words, speech-active WPM, whole-clip WPM | All pause statistics |
| Typical pace, pace variation, slowest and fastest phrase | Loudness and pitch, overall and per phrase |
| Each phrase's "faster / slower than typical" | The settings the result was made with |
| Hesitation sounds (counted from the corrected words) | Figures of phrases that were not corrected |

**Word times.** A corrected word that is also in the recognised version, in the same
order, keeps the time the recogniser gave it. Words are matched the way two recordings are
lined up in section 14. New words in between were never timed by anything, so they are
spread evenly across the gap they sit in and carry no confidence figure. **Emphasis
candidates** rest on loudness and pitch per word, measured from sound that is no longer
there; one is kept only if its word is still present at the same time.

The settings used are the ones the result was made with, not today's: the phrases were cut
by those, and what counts as "too few words to trust" should not shift under a result.

The revision is marked "transcript corrected" and carries a note saying so. Its coaching
is written from the fixed rules at once; the AI model is asked when the user chooses.

Code: `transcript_correction.py`.

### Old results, and analysing again

A result records the calibration version and the minimum pause it was made with, and is
never recalculated. After the minimum pause moves, an older result and a newer one have
their pauses cut differently, so the app says so wherever the two meet:

| Where | What is shown |
| --- | --- |
| On an older result | "This result was made when a silence counted as a pause from 500 ms. Your feedback has since moved that to 400 ms…" |
| Comparing with an earlier attempt | A warning that the two were analysed with different settings |
| Comparing with a reference | The same, with both values |

If the recording was kept, it can be **analysed again** with the settings as they are now.
That makes a further revision; the earlier result stays. The check that this does what the
rules say is simple and was run on real audio: at a lower minimum pause, the pauses found
are exactly the earlier pauses plus the earlier short silences that are at least as long
as the new minimum.

### Feedback on a reference recording

A reference is measured exactly like a take (section 14), so it can be wrong in exactly
the same ways: a misheard word, a pause that was missed, a silence that was not a pause.
In one way it matters more. Takes are compared with it word by word, so one wrong word in
the reference is a wrong word in every comparison.

What can be said about a reference, and what comes of it:

| Said about a reference | What happens | Why |
| --- | --- | --- |
| "The words are wrong", with the right words | A new revision of the reference. Its word counts and WPM are worked out again as for a take (see "Correcting the transcript"); nothing measured from the sound changes; takes are then lined up with the corrected words | The comparison rests on the words |
| "Not a pause", "too short to split", "a pause was missed" | Saved as a report, with the measured silence, like a report on a take | The detector is the same detector |
| "The WPM looks too high / too low" | The same review as for a take, worded for someone else speaking | |
| "Intentional" / "Accidental" | Refused | A label changes how the coaching reads a pause, and a reference has no coaching |
| "Useful" / "Not useful" | Not possible | There is no correction to rate |

**The rule that a reference cannot move a setting by itself.** A report on a reference
counts towards the minimum pause like any other: it carries a measured silence, and
"that 356 ms gap is a pause" is as true of a film clip as of a take. But the settings are
meant to fit the user's own recordings, and a film clip can mislead the detector in ways
the user's microphone never will: speech under music is heard as silence, a cut between
shots as a pause. So one more condition is added to the list above: among the reports
that agree, at least one must be about a take.

```
 reports waiting on the minimum pause           does it move?
 ─────────────────────────────────────────      ─────────────────────────────────────────────
 reference, reference, reference, reference     no: none is about a take
 reference, reference, take                     yes: 3 agree, 2 recordings, 1 is a take
 take, take (one recording)                     no: 2 reports, 1 recording
```

Everything else is unchanged: three reports, two recordings, three in four agreeing. The
evidence used to choose the new value is all the agreeing reports' silences, the
references' included.

On the real pipeline: four missed-pause reports on two references moved nothing. A fifth,
on a take, moved the minimum pause from 500 to 400 ms, "after 5 reports of a pause that
was missed, from 3 recordings. The silences reported were around 356 ms long." Correcting
two words of a reference gave a revision that a take lined up with on 45 of 47 words,
where it had lined up on 47 of 47 with the uncorrected one: exactly the two words changed.

Code: `feedback.save` (what is refused), `calibration/engine.py` (`Report.own_take`,
`Tally.enough`), `revisions.create_corrected`.

### What the feedback adds up to

After a few sessions there may be dozens of pieces of feedback spread over many results.
The calibration panel gathers them in one place. There are two parts, and they are made in
opposite ways on purpose.

**The facts: counted and worded by code.** Every time the panel is opened, the stored
feedback is read and turned into about ten sentences:

```
 f1: 12 pieces of feedback in all, on 3 recordings: 6 on your own takes and 6 on reference
     recordings.
 f2: What it is about, largest group first: missed pauses (5), WPM figures (3), pauses you
     labelled (2), coaching corrections (1), wrong words (1).
 f3: Pauses you labelled intentional: 1. It lasted 1.6 s. A label changes how the coaching
     reads a pause, not its length.
 f5: Missed pauses you reported: 5. At 5 of them the detector had heard a silence lasting
     between 324 and 356 ms, which was shorter than the minimum pause at the time and so
     was not counted as a pause.
 f9: Minimum pause is now 400 ms; the default is 500 ms. Your reports moved it, and it
     applies to recordings analysed from now on.
```

Three rules shape these sentences, each learned from watching a reader get them wrong
(the reader was the AI model, in the experiments below, but the rules serve a person too):

- **One fact, one thing.** "Pauses you labelled intentional" and "accidental" are two
  facts, each with its own lengths. When they shared a sentence, the two lengths were read
  as two measurements of one pause.
- **No two facts count the same feedback.** Which kinds of correction were rated "not
  useful" is said inside the fact that counts the ratings. As a fact of its own it was
  read as a second lot of ratings.
- **A fact that could be misread carries what it means.** "…which was shorter than the
  minimum pause at the time and so was not counted as a pause." "Saying so changes no
  figure." Nobody should have to work that out.

**The notes: the user's own words, with a few picked out by the AI model.** A note is up
to 280 characters the user typed beside a piece of feedback ("he stops for a beat here in
the film"). Code cannot sum those up, so this is the one place the model is used. It is
used as narrowly as possible:

```
 the notes, numbered                      the model's whole answer
 ───────────────────────────────          ─────────────────────────
 n1 (on a pause you said the app          { "notes": ["n4", "n1", "n6"] }
    missed): "music is loud under
    this part"
 n2 …                                     what is shown
 …                                        ─────────────────────────
                                          notes 4, 1 and 6, word for word
```

- The model is given the notes and what each was written about. No counts, no settings,
  no transcript, no audio.
- It answers with three numbers. The answer's shape is fixed by a JSON schema that lists
  the allowed names, so it cannot name a note that does not exist.
- Nothing it writes is shown. What is shown is the user's own notes, copied.
- A note of fewer than three words ("ok", "wrong") is never offered to it.
- Code counts which subject most notes are on and says so in the request ("Most of the
  notes are on a pause you said the app missed. Choose at least one of those."), so the
  model does not have to count.
- It is asked only when there are at least five notes worth offering. With fewer, they are
  all on the screen already.

So the worst the model can do here is choose badly. It cannot state anything false,
because it states nothing.

**Why so narrow: three designs, measured on the real model.** The brief allows the model
to "summarise feedback". The obvious way to do that was built first and measured, then a
second, then the third. All runs below are `llama3.1:8b` on the same stored feedback.

*Design 1: the model restates the facts in its own words.* Its answer was checked the way
coaching is (section 13): every number had to be a number from the facts.

| What was asked | Runs | Numbers that passed the check | What it wrote |
| --- | --- | --- | --- |
| An overview, plus three "patterns", each resting on a named fact | 3 | All of them, in all 3 | A false or meaningless sentence in each run. "You intentionally paused for 1.6 seconds, but the app measured the same pause as 2.7 seconds" (two different pauses). "You labelled 2 pauses as intentional" (one of each). One rating reported as two |
| An overview only, from the one-thing-per-fact wording above | 5 | All of them, in all 5 | "You provided feedback on 12 recordings" in 5 of 5. It was 12 pieces of feedback on 3 recordings |
| The same, told to write no numbers at all | 5 | Not applicable | Numbers in 5 of 5 |

Every figure was real and every check passed. What was wrong was *which thing each number
counted*, and no check on numbers can see that. Rewording the facts cured the two mix-ups
it was aimed at and left the model free to make the next one.

*Design 2: the model says, in its own words, what the notes are about.* Its answer was
checked for numbers and quotations that are not in a note.

| What was asked | Notes | Runs | What it wrote |
| --- | --- | --- | --- |
| "What these notes are mostly about and what they have in common" | 11, English | 8 | True and empty in 8 of 8: that the notes are feedback on the app's measurements of pauses and speed |
| "What reasons you give for disagreeing with the app" | 11, English | 6 | Causes nobody gave. "The app… mislabels some [pauses] as accidental": the app labels nothing |
| "The particular things they mention, in the notes' own words" | 11, English | 8 | Faithful in 8 of 8, mostly by quoting the notes |
| The same | 3, English | 8 | The three notes quoted correctly, with something no note says added in 7 of 8 ("their impact on the listening experience") |
| The same | 5, Hinglish | 8 | Something false about the speaker in 3 of 8: "you paused too long" twice, "your speaking speed was too high" once. The note said the opposite: "sunne mein itna tez nahi lagta" |
| The same, after rewording what each note was about so that it says who said what | 11, English | 8 | A new mistake in 4 of 8: that the app "mislabelled pauses as intentional or accidental" |

The best wording was faithful on one set of notes and wrong three times in eight on notes
in the language this app's user actually writes in. Each fix moved the mistake somewhere
else. And the one thing that was reliably right in every run was the part where the model
*quoted* a note.

*Design 3: the model only picks.* That observation is the design: keep the quoting, drop
the sentences around it.

| Version | Notes | Runs | Usable answers | Time | What it picked |
| --- | --- | --- | --- | --- | --- |
| Pick three | 11, English | 10 | 10 | 1.7 to 4.6 s | A note from the largest group (5 of the 11) in only 3 of 10 |
| Pick three | 7, Hinglish, two of them "ok" and "galat" | 10 | 10 | 1.6 to 3.3 s | An empty note in 9 of 10 |
| Short notes never offered; the largest group named in the request | 11, English | 10 | 10 | 1.6 to 2.3 s | A note from the largest group in 10 of 10; three different subjects in 8 of 10 |
| The same | 7, Hinglish | 10 | 10 | 1.6 to 2.2 s | The same two specific notes in 10 of 10 |
| The same, through the API and the worker | 9, mixed | 5 | 5 | 2 to 6 s for the whole job | Every picked note one of the notes, word for word; "ok" never; the largest group in 5 of 5 |

The two faults of the first version were both failures of judgement, and both were fixed
by code doing the part code is good at (counting words, counting groups), not by asking
the model more firmly.

**What is not claimed.** That the three picked are the three a person would pick. Nobody
has compared. The pick also varies from one request to the next: the 11 English notes gave
five different sets of three in ten runs. It is a way of seeing a few notes first, and the
whole list is one click below it.

Code: `feedback_summary.py` (`build_digest` for the facts; `build_prompt`, `read_answer`
and `pick` for the notes).

### What was seen with the real pipeline

Two recordings were synthesised with silences of known length inside their phrases, and
the whole path was run through the real API, worker, speech model and AI model.

| Step | Result |
| --- | --- |
| Silences inserted as 380, 420 and 400 ms in one recording, 390 and 430 ms in the other | Measured as 324, 356 and 356 ms, and 356 and 356 ms: 35 to 75 ms shorter. Each speech region is widened by 30 ms on each side, and the detector works in steps of 32 ms |
| Two missed pauses reported in one recording | Nothing moved |
| A third reported in the second recording | 500 → 400 ms: "…after 3 reports of a pause that was missed, from 2 recordings. The silences reported were around 356 ms long." |
| The recording analysed again at 400 ms | Same 3 pauses: the silences are under 400 ms. As the rules predict |
| Three fresh reports on the new results | 400 → 350 ms |
| Analysed again at 350 ms | 5 pauses: the two 356 ms silences now count and the 324 ms one does not. Speaking time fell by exactly 2 × 0.356 s. Word count unchanged |
| Both adjustments undone, analysed again | Cut exactly as the first time |
| A pause marked accidental, coaching written again by the AI model | The pause no longer praised; a correction about carrying on through it; every measurement identical |

The first adjustment did not fix the reported silences, and the second did. That is the
"small confirmed steps" behaviour working as designed, and it is also a real cost: reaching
350 ms took six reports and two rounds of analysing again.

## 16. Accuracy and limits

What is known, stated plainly.

| Area | Limit |
| --- | --- |
| Pause lengths | The detector works in 32 ms steps and regions are widened by 30 ms, so a pause length is good to roughly a tenth of a second, not a millisecond. In testing, silences requested as 1.5 s and 6.0 s were measured as 1.60 s and 6.15 s; the synthesiser adds a little natural silence of its own. |
| Background noise | Loud or changing background makes speech detection, and so pauses, less accurate. The `noisy` warning signals this but cannot fix it. |
| Two people talking | Not handled. Overlapping voices are treated as one stream of speech. |
| Word counts | Only as good as the recogniser. Mumbled, very fast or accented speech can lose or gain words, which moves WPM. |
| Hindi | The `small` model makes spelling mistakes in Hindi (in testing: "खत्रे" for "खतरे", "आद्मी" for "आदमी") and sometimes dropped one short word. Word counts were close (19 or 20 of 20), but less reliable than English, and Hindi was where the recogniser got stuck on a low-quality file (decision S9). The larger `medium` model is better and several times slower. |
| Audio quality | Heavily compressed audio makes recognition worse. A clean recording matters more than its format. |
| Hinglish | Best effort only, as explained in section 5. |
| Word times | From the recogniser's internal attention, not from a dedicated alignment tool. Fine for deciding which segment a word is in; not precise enough to measure the length of a single word. |
| Pitch | Occasional octave errors; unreliable on creaky or breathy voice and in noise. Since Phase 9 a step counts as voiced at a lower certainty (0.3, was 0.5), which gives deeper voices enough to measure and lets in slightly more doubtful steps; the median moved by 3 Hz or less for thirteen of fourteen test voices and by 6 Hz for one. |
| Voice range: what it is | A description of two measurements against stated ranges. It is not a statement about the speaker, and not a measure of how any listener hears them: perception also depends on intonation, the way words are shaped, loudness, and the listener. No one's ears were part of this. |
| Voice range: the ranges | This app's own. The pitch ranges follow round figures usually given for adult speaking voices; the resonance ranges were set from fourteen synthesised voices and nothing else. A real voice may sit differently in them, and the neutral range for resonance (1,040 to 1,100 Hz) in particular is only the gap those voices left. |
| Voice range: the percentage | A position between two stated numbers, drawn as a straight line. It is not a probability, and "40%" is not "40% masculine". Past the far end of a range it stays at 100%. |
| Resonance: tested on | Synthesised voices only (fourteen macOS voices, English and Hindi). **Not on a person**, not on a laptop microphone in a room, not on a singer or a trained voice. |
| Resonance: a short phrase | Depends on which vowels the phrase happens to hold. Of stretches 1 to 1.5 seconds long, 2 to 4 in a hundred landed in the opposite range and 10 to 16 in the neutral one. A phrase with little usable sound is labelled an estimate; the figure for the whole recording is much steadier. |
| Resonance: background noise | Hiss makes a voice read brighter. The figure is labelled an estimate when the voice is less than 30 dB above the background and not given under 20 dB. In between it can still be off by tens of Hz: in the test at 24 dB, a voice that measures 1,017 Hz clean read 1,050 Hz, which is in the neutral range instead of the lower one. |
| Resonance: music, other voices, a phone line | Not tried. Music or a second voice will be measured as if it were the speaker. A telephone or a heavily filtered recording that removes sound above 3,400 Hz takes away part of what is measured. |
| Resonance: the words spoken | The figure leans on the third formant to depend less on the vowels, and it still depends on them a little. Compare takes of the same lines, as the monologue screens do, in preference to different texts. |
| Voice goal: the drills | Ordinary, gentle voice exercises, written as templates. They are not medical advice and not a programme. Changing where a voice sits takes weeks of practice and is best guided by a voice coach or a speech therapist; the app says so whenever a goal is set. |
| Voice goal: one recording | Each analysis stands alone. The app does not yet show how pitch or resonance moved across days of practice. |
| Loudness | Relative to the recording only (section 8). |
| Emphasis | Detects louder and higher. Misses emphasis by slowing down or pausing. |
| Hesitation sounds | A lower bound. |
| Breaths | Not detected. |
| Intention and emotion | Not measured, and not inferred from the measurements. |
| The bands behind "fast", "even", "narrow" | This project's own rough choices (section 13). Compared so far only with four synthesised clips. A real voice, a different language or a different style may sit differently in them. |
| AI coaching: the figures | Checked. A figure with a unit, a time, a segment number or a quotation that does not match the measurements is sent back, then removed. The check allows 3%, so a figure near a measured one passes: in one run the model proposed drill speeds of "220, 240 and 200 WPM", which passed because phrases had been measured at 225 and 237 WPM and 200 WPM is a band. |
| AI coaching: the advice | Not checked, and cannot be by code. Whether "this line sets the tone" is true, or a drill is a good one, is the model's judgement. An 8-billion-parameter model is fluent and often generic. Treat it as a suggestion. |
| AI coaching: language | Written in English, whatever language was spoken. Hindi lines are quoted in their own script. |
| AI coaching: repeatability | Asking twice gives different wording, and can choose different lines. The measurements, findings, summary, targets and caveats are identical every time. |
| Comparison: needs the same words | Lining up works through the recognised words. Two recordings of different text, or in different languages, are compared only as wholes. |
| Comparison: depends on both transcripts | A word misheard in either recording is a word not lined up. A pause next to several misheard words is reported as "could not be located", not guessed at. |
| Comparison: a reference with music or other voices | Typical of a clip from a film. Music can be taken for speech, or hide a pause, and it changes the loudness and pitch figures. The comparison cannot tell; a clean recording of the original gives a far better reference. |
| Comparison: phrase pace | Rests on word times good to about a tenth of a second, so it is an estimate, weakest on short phrases. |
| Comparison: what it cannot say | Whether a difference matters. It lists where the two recordings differ in pauses and pace. It does not hear emphasis, tone or intention, and it never calls a difference a mistake. |
| Comparison: which original | Since Phase 8 a take is compared only with the original of the monologue it was recorded for. A take recorded for the wrong monologue (the user chose one and performed another) is still compared, and the line-up will say how few words were found. |
| The script of the original | A rearrangement of the reference's stored result, so it inherits every limit above: misheard words appear as heard, a pause hidden by music is missing, and only louder or higher words are marked. It is not a transcript checked by a person. |
| Waveform | A picture. Its height depends on how each recording was made. Nothing is measured from it. |
| Short silences | Measured 35 to 75 ms shorter than the silence really is, for the same reason pauses are (the 30 ms widening and the 32 ms steps). A real gap of 400 ms shows as about 350 ms. This is what the minimum pause is compared with, so "500 ms" means about 550 ms of true silence. |
| Calibration: what it can adjust | One measuring setting, the minimum pause, between 250 and 800 ms, and the order of corrections. It cannot make the detector hear speech it missed, fix a misheard word, or change how pitch and loudness are measured. |
| Calibration: how much it has to go on | An adjustment is made on as few as three reports. That is a small sample, and the screen says "low confidence". It is one person's judgement of their own recordings, which is the point of it, and also its limit. |
| Calibration: speed | Deliberately slow. Each step is 50 or 100 ms and needs three fresh reports from two recordings. In the test run, going from 500 to 350 ms took six reports and analysing the recordings again in between. |
| Calibration: older results | Not recalculated. A result made before an adjustment has its pauses cut by the old value, and is marked wherever it is set beside a newer one. Analysing again needs the recording to have been kept. |
| A quiet or whispered phrase | The detector can miss the start of a phrase spoken far more quietly than the rest (measured: 1.5 s lost at 40 dB quieter). Feedback cannot correct this; recording closer to the microphone can. The app says so when a long "pause" is reported as speech. |
| Corrected transcripts: word times | A word the user adds or changes has no measured time. It is placed evenly between its neighbours, so emphasis candidates are kept only for unchanged words, and anything that depends on exact word times is an estimate there. |
| Corrected transcripts: what is trusted | The user's words are taken as given. The app does not check them against the audio. |
| Pause labels | Taken as given. Nothing in the sound tells an intended pause from a slip, so the app never guesses one, and a label is never applied to other pauses or other recordings. |
| Picking a word for a missed pause | The word's time comes from the speech recogniser and can be a tenth of a second or more from the silence. The nearest silence within half a second is taken, and shown before the report is saved. Measured on six silences in clean synthesised speech only. |
| Feedback on a reference | Its reports count towards a setting only together with one from a take of the user's own. A user who only ever reports on references will see the count grow and nothing move, and the screen says why. |
| What the feedback adds up to: the facts | Counts and measured figures, worded by code. Exact, and only as good as the feedback itself. |
| What the feedback adds up to: the AI model's pick | Three of the user's notes, chosen by the model and shown word for word. It cannot say anything false, because it says nothing. Whether they are the three a person would choose has not been checked, and the choice changes from one request to the next. A note of one or two words is never picked. |
| The AI model and summaries | It was tried at writing a summary, in two ways, and was wrong too often to show: right numbers attached to the wrong things, and things no note said. Those versions are not in the app. See section 15. |
| AI coaching: what the speaker says | The transcript is part of what the model reads. Words in a recording that sound like instructions could in principle steer its wording. They cannot make it name a finding or segment that does not exist, or get an unmeasured figure past the checks. |

**How it has been tested so far.** The arithmetic is covered by tests whose answers can be
worked out by hand. The complete pipeline has been run on synthesised speech (the macOS
`say` voices, English and Hindi) with silences of known length, as WAV, AIFF, M4A, MP3 and
as WebM recorded by a browser. It has **not** yet been checked against real human
recordings with pauses and words marked by a person, so the accuracy figures above are
indications, not guarantees.

**The same speech in different formats** gave nearly the same numbers: the test clip as WAV
measured 223.1 speech-active WPM with pauses of 1.60 and 6.15 s; re-recorded through a
browser as WebM it measured 224.0 WPM with pauses of 1.64 and 6.15 s. A low-quality MP3 was
the exception that exposed the recogniser failure described in decision S9.

**Repeat runs.** Pauses, loudness and pitch are the same every time for the same file. Word
counts are too, unless a window had to be retried (decision S9), in which case they can
differ slightly between runs.

**Speed**, measured on this Apple M2: a 17-second recording in about 9 seconds including
loading the model; recognising the words of a 133-second recording in about 20 seconds. The
AI coaching then adds 20 to 50 seconds, which depends on the length of the answer far more
than on the length of the recording.

**How the comparison has been tested.** Its arithmetic is covered by tests on recordings
built to order, with pauses and phrases at known times. The complete path was then run with
the real pipeline on five synthesised recordings:

| Check | Result |
| --- | --- |
| An English take against an English reference of the same lines (the take adds a line before and after, splits one line in two and runs two together) | 30 of 31 words lined up. All four pause rows correct: one extra pause, two shared (+1.02 s and +0.29 s), one missing 6.1-second pause |
| A Hindi take against a Hindi reference, pausing in different places | 17 of 19 words lined up. The reference's 2-second pause reported as missing in the take; the take's two pauses reported as extra |
| A two-minute recording against an exact copy of itself | 370 of 370 words, 23 of 23 pauses matched with zero difference, 24 phrases at identical pace, no differences listed |
| An English take against a Hindi reference | 0% lined up; compared only as wholes, and the note says so |
| Time to compare | 3 to 5 thousandths of a second for the short pairs; 14 to 31 for the two-minute pair |

The third check is the one that found a real fault, described in section 14 and decision
S39. It has **not** been run on real human recordings, on a reference taken from a film, or
on two recordings in which the same text is spoken by different voices.

**How feedback and calibration have been tested.** The rules are covered by automated
tests whose answers can be worked out by hand, including that no setting ever leaves its
range, that one piece of feedback never counts towards two settings, and that a corrected
WPM is the corrected word count over the phrase's own length. The complete path was then
run through the real pipeline and the real AI model on two synthesised recordings with
silences of known length inside their phrases; what was seen is in section 15. The speech
detector's threshold was measured on five synthesised recordings, and on nine altered
copies of one of them (a phrase made quieter, or noise added), before deciding to leave it
fixed. It has **not** been tried on a real human
voice, with feedback given by someone who actually spoke the words, or over the weeks of
use that calibration is meant for. Whether the 250 and 800 ms limits, "three reports from
two recordings" and the 50 to 100 ms step suit real use is not known yet; they are
cautious first choices.

**How Phase 7 has been tested.** The rule about reference recordings, the facts and the
handling of the model's pick are covered by automated tests; the facts for a known set of
feedback are compared word for word. The complete path was run through the real pipeline
and the real AI model: 41 checks, all passed (section 15 and the backend document).
Separately, the three designs for using the AI model were each run 3 to 10 times on the
real model, about 125 runs in all, and every answer was read; the tables in section 15
are what was found. It has **not** been tried with notes a person wrote over days of use;
the notes were written for the test, eleven in English and five to seven in Hinglish.
Whether five notes is the right minimum, three the right number to pick, and three words
the right length for a note worth offering is not known; like the limits above, they are
first choices. Picking a word for a missed pause was measured on six silences in clean
synthesised speech and no others.

**How Phase 8 has been tested.** No measuring code was changed, so the tests of the
measurements, the comparison and the calibration are as they were and all still pass.
What is new was checked for the two things it could have got wrong. That a take is tied
to the right original: automated tests of the backend (a take is listed under its
monologue and nowhere else; a corrected original is still the same monologue) and of the
screen's store (a take is never compared with another monologue's original, which caught
a real fault: frontend decision F75). And that the pairing changes no figure: on the real
pipeline, the same file was submitted as a monologue's original and as a take of it, and
the comparison lined up 31 of 31 words, found all 3 pauses in both with a difference of
zero, and listed no differences. A second, different take then gave four differences. The
script is covered by tests of its own (one line per phrase, the pause after each, a
repeated word marked only where it stood out) and was read in the browser for an English
and a Hindi recording. It has **not** been tried on a real performance; both originals
were synthesised speech.

**How Phase 9 has been tested.** The arithmetic (which range a value falls in, the
percentage, the one-word marker) is covered by tests worked out by hand, including the
edges of every range. The resonance measurement is tested on vowels built with exactly
known formants, so the right answer is known: a spacing of 1,000 and of 1,200 Hz, each
found within 20 Hz, the same answer on a low note and a high one and on a much quieter
copy, and nothing reported for silence or for a sound too short. The choice of method, the ranges
and the noise limits rest on the measurements in section 9a: fourteen synthesised voices,
two sentences each, clean, with white, pink and low-weighted noise at three levels, as
compressed audio, and at lower volume.

The complete path was then run through the real API, worker, speech model and AI model
on five recordings: 22 checks, all passed.

| Check | Result |
| --- | --- |
| A deeper voice | Pitch 125 Hz, lower range, 34% into it. Resonance 1,017 Hz, lower range, 23%. Together: lower |
| A higher voice | Pitch 181 Hz, higher range, 7%. Resonance 1,198 Hz, higher range, 49%. Together: higher |
| The same recording with and without a goal | Every measurement identical; only the coaching differs |
| The deeper voice with the goal "higher" | Both findings are issues; corrections "Keep your pitch in the higher range" and "Brighten your resonance", targets pointing up, the word of caution added |
| The deeper voice with the goal "lower" | Both findings are strengths; no correction about the voice |
| One recording with the deeper voice, a pause, then the higher voice | Phrase 1: 125 Hz and 1,019 Hz, lower. Phrase 2: 182 Hz and 1,197 Hz, higher. Pitch within 1 Hz and resonance within 2 Hz of each voice measured alone |
| That recording with the goal "lower" | "1 of 2 phrases stayed in it for pitch. Furthest from it: segment 2 at 182 Hz." Both drills are set on phrase 2 |
| The AI model's wording, with a goal | No word about the speaker's sex or gender in either run, after the two changes described in section 13 |
| Hiss about 25 dB below the deeper voice | The app reads 24 dB. Resonance 1,050 Hz, neutral, labelled an estimate, with a warning. Pitch unchanged in range (126 Hz) |
| Hiss about 15 dB below it | The app reads 14 dB. Resonance not given, with the reason; pitch alone decides the marker |
| A reference recording | Measured the same way; never has a goal |

Three of those checks first failed and changed the app: the pitch of the deeper voice came
back as unavailable (section 9, the 0.3), the model's wording spoke about the speaker
(section 13), and at 14 dB the resonance came back in the wrong range labelled as an
estimate (section 9a, the 30 and 20 dB limits). It has **not** been tried on a human
voice, on someone actually working on their voice over weeks, or against the judgement of
a voice coach or of listeners. Until it has, the ranges and the figures above are
indications of how the app behaves, not evidence of how a voice is heard.

**How the coaching has been tested.** Its logic is covered by automated tests that replace
the AI model with a scripted stand-in, including one that invents figures, misquotes, names
things that do not exist, answers in broken JSON or is not running. The real model was then
run about fifteen times on four synthesised recordings; what was seen is in section 13. A
prompt the size of a 10-minute recording was also sent to it, built by stitching the
measurements of a 133-second recording end to end, to confirm that it fits and is answered.
It has **not** been tried on real human recordings, on a real recording near the 10-minute
limit, or compared with what a human speaking coach would say.

## 17. Science decisions

Each entry says what was chosen, what was considered, and what was decided against and why.

### S1. Speech detection with Silero VAD

- **Chosen:** the Silero VAD neural network, which ships inside the speech library.
- **Why:** it separates speech from other sound, which is exactly the question. It runs
  locally in a fraction of a second and needed no extra install.
- **Decided against:**
  - *A loudness threshold:* simplest, but treats any loud sound as speech and any quiet word
    as silence, so it breaks with background noise or a soft voice.
  - *WebRTC VAD:* an older, lighter detector; another dependency, and generally reported
    to be less accurate than Silero in noise. It was not tried here.

### S2. Speech regions are widened by 30 ms, not the default 400 ms

- **Chosen:** minimal widening.
- **Why:** the default exists to avoid cutting off word endings before transcription. Here
  the regions are used to measure pauses, and the default would shorten each one by up to
  0.8 s.
- **Trade-off accepted:** a very soft word ending can fall just outside a segment. That
  affects the pause by a few hundredths of a second, which is within the stated accuracy.

### S3. Every pause ends a segment; five seconds starts a new section

- **Chosen:** segments are phrase-sized (split at every pause of 0.5 s or more), and
  segments are grouped into sections at long silences (5 s or more).
- **Why:** the project brief names two thresholds, 0.5 s for a pause and 5 s for a "new
  segment boundary". Splitting only at 5 s would make a typical monologue one giant segment,
  so "segment WPM" would just repeat the overall rate and coaching could not point at a
  particular phrase. Splitting at every pause gives phrases that can be practised
  individually, and the 5-second rule still marks the larger structure.
- **Decided against:** segments split only at 5 s; one flat list with no notion of sections.
- **Note:** this is an interpretation of the brief. If segments should be longer, the two
  thresholds are settings and can be changed.

### S4. Speaking time is the length of the segments

- **Chosen:** gaps under 0.5 s count as speaking; pauses and end silences do not.
- **Why:** this is the standard idea of "articulation rate": the tiny gaps inside a phrase
  are part of how speech is produced and are not pauses.
- **Decided against:**
  - *Summing only the raw detected regions:* would also subtract the sub-pause gaps, making
    everyone seem faster and making the result depend on the detector's fine detail.
  - *Summing word lengths from the recogniser:* word times are the least precise thing
    available.

### S5. Silence before the first word and after the last is not a pause

- **Chosen:** reported separately, excluded from pause statistics.
- **Why:** how long someone waits before starting, or how late they press stop, says nothing
  about their delivery, yet would otherwise dominate "longest pause".

### S6. Whisper `small` through faster-whisper

- **Chosen:** the `small` model with 8-bit numbers (`int8`), on the CPU.
- **Why:** it handles English and Hindi, gives word times, and runs several times faster
  than real time on this laptop.
- **Decided against:**
  - *`medium` or `large-v3`:* clearly better, especially for Hindi, but several times slower
    and heavier on memory. Left as a setting (`WHISPER_MODEL`).
  - *`tiny` or `base`:* faster, but noticeably worse on Hindi.
  - *The original OpenAI Whisper package:* same models, slower, and needs a much larger
    install.
  - *Any cloud speech service:* ruled out by the local-only requirement.

### S7. Word times from Whisper, not from a separate alignment tool

- **Chosen:** Whisper's own word timestamps.
- **Why:** they only need to be good enough to put a word in the right phrase, and the
  check in section 5 reports when they are not.
- **Decided against:** forced-alignment tools such as WhisperX or the Montreal Forced
  Aligner. They are more precise but add large dependencies and separate models per
  language, including Hindi.
- **When to revisit:** if word-level features, such as how long a single word was held,
  become important.

### S8. The detector decides boundaries, the recogniser decides counts

- **Chosen:** segment and pause times come only from speech detection; words are then
  placed into those segments by their midpoint.
- **Decided against:** deriving pauses from gaps between Whisper's words. Whisper stretches
  words across silence, so pauses would come out too short or disappear.

### S9. A window is redone only when it has clearly gone wrong

This decision was changed once. Both steps are recorded, because the first one was a mistake
worth understanding.

- **Background:** when a 30-second window's text looks repetitive, Whisper retries it with a
  little randomness ("temperature"), up to five more times. "Repetitive" is judged by how
  well the text compresses; Whisper's default line is a ratio of 2.4.
- **First choice (Phase 2): no retries at all.** Practised speech is often repetitive. On a
  133-second test clip that repeated one passage, the default took 134 seconds, with
  stretches of 50 seconds in which a cancel request could not be acted on. A single pass took
  23 seconds and recognised the same number of words (370 of about 376). So retries were
  switched off.
- **What went wrong (Phase 3):** a Hindi clip, saved as a low-quality MP3, came out as one
  character repeated for five seconds: 8 words instead of 20, and 82 WPM instead of about
  200. This is exactly the failure the retry exists to rescue, and it had been removed. The
  same clip as an uncompressed file had been fine, which is why it was not seen earlier.
- **Chosen now:** keep all of Whisper's retries, but raise the line for "repetitive" from
  2.4 to 3.0. The stuck output measured 5.0; the genuinely repeated passage measured 2.7.
  With the line between them:

| Clip | No retries | Retries, line at 3.0 |
| --- | --- | --- |
| Hindi MP3 (20 words spoken) | 8 words, garbled | 19–20 words in 4 runs out of 4 |
| Repeated English passage, 133 s | 23 s, 370 words | 20 s, 370 words, no retries triggered |
| Short English clip | 31 words | 31 words, no retries triggered |

- **Decided against:**
  - *Whisper's default line of 2.4:* six times slower on the repeated passage, for no gain.
  - *One retry only:* it rescued the Hindi clip in testing but then failed once in a real
    run, because the retry is random and a single one can also come out badly.
  - *Forbidding repeated words in the output:* it would also rewrite speech where words are
    repeated on purpose ("never, never, never").
- **Trade-offs accepted:**
  - A window that is retried takes several times longer, and a cancel request waits for it.
  - Retries use randomness, so a recording that needed one can give a slightly different
    transcript if it is analysed again (19 words one time, 20 the next).
- **Honest limit:** the line at 3.0 rests on two clips. A passage with one short line said
  many times over could cross it and be retried needlessly, which costs time but still
  gives a transcript. The garbled-transcript check (section 5) is the backstop if a stuck
  result gets through anyway.

### S10. Silence is never sent to the recogniser

- **Chosen:** Whisper's own silence filter is on, and Whisper is skipped entirely when no
  speech was detected.
- **Why:** given silence, Whisper tends to produce plausible phrases that were never said.

### S11. Hinglish is handled as Hindi and labelled as a best effort

- **Chosen:** transcribe as Hindi, mark every word-based number an estimate, and warn.
- **Decided against:** presenting Hinglish as supported; trying to detect the language word
  by word, which this model cannot do reliably.

### S12. Loudness is relative dBFS from RMS energy

- **Chosen:** RMS in dBFS, compared only within one recording.
- **Decided against:**
  - *Real-world loudness (dB SPL):* impossible without a calibrated microphone at a known
    distance.
  - *LUFS, the broadcast loudness standard:* designed for programme loudness and adds
    perceptual weighting that is not needed to compare phrases in one voice recording.
  - *Scaling every recording to the same level first:* would make recordings look
    comparable when they are not.

### S13. Background level from the median, away from speech

- **Chosen:** background is measured at least 0.1 s from any speech and summarised by its
  median.
- **Why:** the first version averaged everything outside the segments. A test with known
  levels showed it reporting 25 dB where the truth was 40 dB, because the trailing edges of
  words were being counted as background.

### S14. Pitch with pYIN from librosa

- **Chosen:** pYIN, run on speech segments only.
- **Why:** it reports how sure it is that a step is voiced, which is needed to avoid
  inventing pitch for consonants and noise. Running it only on speech saves time.
- **Decided against:**
  - *Praat through Parselmouth:* the standard tool in phonetics, and a reasonable
    alternative; it would be one more dependency for a similar result.
  - *Plain YIN:* much faster, but gives a pitch for every step, voiced or not.
  - *CREPE and other neural pitch trackers:* accurate, but need a large deep-learning
    framework installed on top of everything else.

### S15. Pitch range by percentiles, movement in semitones

- **Chosen:** 5th to 95th percentile; variation in semitones around the speaker's median.
- **Decided against:** lowest-to-highest (one tracking error sets the range); Hz alone
  (makes deep voices look less expressive than high ones for the same movement).

### S16. Emphasis by simple, visible rules

- **Chosen:** fixed thresholds on loudness and pitch, results called candidates.
- **Why:** the rule can be read, checked and explained to the user.
- **Decided against:** a trained model of stress or prominence, which would be a black box
  and would need labelled Hindi and English data.

### S17. Only unambiguous hesitation sounds are counted

- **Chosen:** `um`, `uh`, `अं` and similar. Not "like" or "मतलब".
- **Why:** counting real words as fillers would produce false accusations that the user
  cannot check.

### S18. Breaths are reported as unavailable

- **Chosen:** no number at all.
- **Decided against:** counting pauses, or pauses with some noise in them, as breaths.

### S19. Doubtful numbers are shown and labelled, not hidden or adjusted

- **Chosen:** unreliable values stay visible with a reason; outliers are flagged and left
  unchanged; anything unknown is empty rather than zero.
- **Why:** the user should always be able to see what was actually measured and decide for
  themselves.
- **Decided against:** capping fast WPM values; dropping short segments; filling gaps with 0.

### S20. Output is rounded

- **Chosen:** times to the millisecond, WPM and dB to one decimal place.
- **Why:** `193.54838709677` WPM suggests a precision the method does not have.

### S21. Numbers come from code; the AI model only explains

- **Chosen:** see section 13. Built in Phase 4, and taken further than first planned: the
  model does not even receive the raw metrics to interpret. It receives finished statements
  (decision S24).
- **Decided against:** asking the model to listen to audio or to compute rates, which it
  would do unreliably and unrepeatably.

### S22. "Faster" and "slower" are judged against the speaker's own median

- **Chosen:** typical pace is the median WPM of the reliable segments; a segment is labelled
  when it is 25% or more away from it.
- **Why:** it needs no outside standard, so it is true for any voice, language or style. The
  median is not moved by one extreme phrase.
- **Decided against:** fixed bands such as "over 160 WPM is fast" (wrong for many speakers
  and for Hindi versus English); comparing with the mean (one rushed line shifts it);
  comparing with a per-profile target speed (there is no honest source for such a number).
- **Honest limit:** the 25% figure is a judgement, not a research finding. It is a setting.

### S23. A garbled transcript is detected by its shape

- **Chosen:** a "word" over 40 characters, or with one character repeated eight or more
  times, marks the transcript as garbled.
- **Why:** it is cheap, cannot be fooled by language, and catches the failure actually seen.
  Real words that are long ("disestablishmentarianism") or stretched ("soooo") pass.
- **Decided against:** trusting the recogniser's own confidence alone, which was not
  reliably low for the stuck output.
- **Honest limit:** it catches a stuck *character*. A stuck *word* or phrase ("thank you
  thank you thank you…") is left to the retry in S9.

### S24. Code states the facts; the model chooses among them and words the advice

- **Chosen:** a layer of **findings** between the measurements and the model. Each finding
  is a finished sentence with its figures in it, and a role (issue, strength, context)
  already decided. The model picks from the issues and writes about them.
- **Why:** it removes the two things a small model does worst. It never has to read a table
  of 25 metrics and decide what "pitch variation 1.6" means, and it never has to decide
  which way a correction should point. It also gives the template fallback for free,
  because templates and model work from the same findings.
- **Decided against:**
  - *Handing the model the whole result as JSON and asking for coaching.* This is the
    obvious design. An 8-billion-parameter model given numbers without anchors guesses at
    what is high or low, and nothing could then check its judgement.
  - *Templates only, no model.* Fully safe, and what the fallback is. But it cannot choose
    the line where a pause would serve the meaning, and the brief asks for the local model.
  - *Letting the model also label each finding as good or bad.* A model that mislabels a
    strength would then coach the user out of something that works.

### S25. The bands are rough, ours, and stored with every coaching

- **Chosen:** fixed thresholds (section 13) that turn a figure into a word, kept in one
  place with a version number and saved inside each coaching.
- **Why:** any coaching, by rules or by a model, needs to know whether a number is a little
  or a lot. Writing the thresholds down makes that judgement visible and changeable instead
  of leaving it hidden in a model's guess.
- **Decided against:**
  - *No bands; let the model judge the raw numbers.* See S24.
  - *Bands drawn from a body of recordings* ("the middle half of speakers fall between…").
    The right way, and there is no such body of recordings here to draw them from.
  - *Bands per language.* Hindi and English words differ in length, so one WPM band for both
    is crude. Separate bands would need evidence this project does not have.
- **Honest limit:** these are judgement calls, checked against four synthesised clips. They
  are settings, and Phase 6 exists to adjust them.

### S26. A profile says which way it leans, never a number

- **Chosen:** each profile focus gets one word, `low` or `high`. "Walter White leans
  towards low pace variation."
- **Why:** it is enough to turn a banded finding into an issue or a strength, and it claims
  nothing about any actor's actual voice.
- **Decided against:** a target per profile ("Thomas Shelby: 120 WPM"). There is no honest
  source for such a figure; it would be invented, and it would look like a measurement.
- **Consequence:** the figures in a target ("towards 140 WPM or below") are the app's bands,
  identical for every profile. The screen says this beside them.

### S27. With no profile, only two things count as issues by default

- **Chosen:** a fast overall pace, and a narrow pitch range. Plus the findings that are
  issues for anyone: a rushed phrase, hesitation sounds, no pause at all.
- **Why:** with no style chosen, most measurements are neither good nor bad. Loud and quiet,
  even and varied, long pauses and short ones can all be right. Speaking too fast and
  speaking in a flat pitch are two of the most widely given pieces of general speaking
  advice, and are safe to raise as optional suggestions.
- **Decided against:** treating every measurement outside its middle band as an issue (it
  would nag about choices that may be deliberate), and giving no coaching at all without a
  profile.

### S28. The shape of the model's answer is enforced, not requested

- **Chosen:** Ollama's structured output, with a JSON schema built for each recording whose
  lists of allowed finding IDs and segment IDs are exactly the ones that exist.
- **Why:** it makes whole classes of mistake impossible instead of merely unlikely. The
  model cannot name `seg-12` in a recording of six segments, because that text cannot be
  generated.
- **Decided against:**
  - *Asking for JSON in the prompt and parsing whatever comes back.* A model can add
    commentary, drop a bracket or rename a field, and repair code would be needed for each.
  - *Plain "JSON mode" without a schema.* Valid JSON, but of any shape.

### S29. The wording is checked figure by figure, with one retry

- **Chosen:** the checks in section 13, then one chance to correct, then removal of what
  still fails, then templates if nothing is left.
- **Why:** the schema cannot see inside a sentence. Telling a model "do not invent numbers"
  lowers the rate at which it does; it does not make it zero, and the brief asks for the
  output to be validated, not trusted.
- **Decided against:**
  - *Trusting the instruction alone.*
  - *Forbidding digits altogether.* Simple to check, but "repeat 3 times" and "hold for 2
    seconds" are exactly what a drill needs.
  - *Throwing the whole answer away over one bad sentence.* Wasteful when two of three
    corrections are sound.
  - *Retrying until it passes.* Each try costs most of a minute, and a model that failed
    twice the same way is not improving.
  - *An exact match for figures.* People, and models, round: "about 220 WPM" for 223 is not
    an invention. Hence the 3% allowance, with the cost described under "Accuracy and
    limits".
- **Honest limit:** this catches wrong *figures*, *times*, *references* and *quotations*.
  It cannot catch a wrong *opinion*.

### S30. The summary, the targets and the caveats are never written by the model

- **Chosen:** the delivery summary is assembled from the findings; each target for the next
  take is a template tied to a correction; the list of what is uncertain comes from the
  analysis warnings and fixed sentences.
- **Why:** these three have to be right every time, and none of them needs a turn of phrase.
  A target should also be something the next recording can be checked against, which
  "establish a steady pace from the start" is not and "keep phrase speeds within 10% of
  your typical pace" is.
- **What prompted it:** in an early version the model wrote the targets, and one of them
  warned against holding pauses "too long", which no finding had said. There was no figure
  in it for the checks to catch.
- **Decided against:** asking the model for everything and checking harder.

### S31. The AI model is reached on this computer only

- **Chosen:** the Ollama address must be `localhost`, `127.0.0.1` or `::1`. Any other
  address is refused before a request is made. Proxy settings in the environment are
  ignored, so a local request cannot be routed through another machine. The client has no
  code for downloading a model.
- **Why:** the prompt contains everything the user said. "Runs locally" should be something
  the code enforces, not something a setting can quietly undo.
- **Decided against:** letting `OLLAMA_BASE_URL` point anywhere (convenient for someone with
  a stronger machine on their network, and exactly how a transcript ends up leaving the
  device), and pulling a missing model automatically (a multi-gigabyte download the user did
  not ask for).

### S32. `llama3.1:8b`, at a low temperature, with room for 8,192 tokens

- **Chosen:** the model named in the brief and already installed here; temperature 0.3; a
  context of 8,192 tokens; answers capped at 600 tokens.
- **Why this model:** it runs on a 16 GB laptop, taking 5.8 GB while loaded, and its
  published description lists Hindi among the languages it supports, which matters for
  Hindi and Hinglish transcripts.
- **Why 8,192 tokens:** left to itself, Ollama picks a size that depends on its version and
  the machine, and a prompt that does not fit is cut by Ollama in a way this app does not
  control. Asking for 8,192 explicitly holds a long transcript plus the instructions, and
  anything longer is cut by this app in a known way (section 13) before it is sent.
- **Decided against:**
  - *A larger model.* Better writing, but slower and beyond this machine's memory alongside
    the speech model.
  - *A model with its refusals removed* (an "abliterated" build of the same model was also
    installed). Speaking coaching never triggers a refusal, so it offers nothing here, and
    altering a model's weights can cost quality. It can be tried by changing one setting.
  - *Temperature 0.* Fully repeatable, but then "Write the coaching again" would return the
    same answer.
- **Honest limit:** 0.3 was the first value tried and was kept. Other values, and other
  models, were not compared.

### S33. Coaching is written in English

- **Chosen:** the instructions, and so the answers, are in English. Lines from the
  transcript are quoted in the script they were spoken in.
- **Why:** the screen is in English, and the templates, bands and findings would all need
  translating for the result to be consistently in another language.
- **Decided against:** asking the model to answer in the language spoken. Its Hindi has not
  been evaluated here, and the checks (units, "segment 4") are written for English wording.
- **Honest limit:** a Hindi speaker gets English advice about Hindi lines.

### S34. Fewer than three corrections when there are fewer than three issues

- **Chosen:** as many corrections as there are issues, up to three.
- **Why:** the brief asks for the top three. But a model told to produce exactly three from
  one issue will invent two, and invented problems are worse than a short list.
- **Decided against:** padding with "context" findings to reach three.

### S35. The model is told the aim and the technique for each issue

- **Chosen:** each issue in the prompt carries a line from its template: "Aim: Keep your
  volume level. Technique: one steady volume, as if to someone across a table."
- **Why:** observed, not assumed. Given a free hand, the model titled a too-fast pace "Speak
  at a steady pace", and for a correction about keeping the volume level it proposed
  whispering and then speaking at full voice, a drill for the opposite problem.
- **Decided against:** leaving the method to the model (above), and giving it the whole
  template drill to copy (it copied it nearly word for word, adding nothing).
- **What is left to the model:** which line to work on, why it matters for that line, and
  the wording of the drill around that line.

### S36. Recordings are lined up by their words, not by their sound

- **Chosen:** the two transcripts are matched word by word, and everything else follows
  from that: a pause is "the same pause" when it falls at the same place in the words.
- **Why:** it is what a person means by "the original pauses after *I am the danger* and
  you did not". It needs no assumption that the two recordings run at similar speeds, and
  every statement it produces can be checked by reading two transcripts.
- **Decided against:**
  - *Matching the sound itself* (stretching one recording's timeline until its loudness
    or pitch curve fits the other's, known as dynamic time warping). It needs no
    transcript, but it lines up *anything* with anything: two unrelated recordings still
    produce a confident-looking match, and its answers cannot be explained in words.
  - *Comparing by clock time* ("at 0:05 the reference is silent and you are not"). It
    breaks the moment one speaker is a little faster than the other.
- **Cost accepted:** it only works when both say the same words, and only as well as the
  recogniser heard them.

### S37. The line-up is the longest common run of words, worked out for the whole passage

- **Chosen:** the longest common subsequence of the two word lists, computed in full.
- **Why:** observed, not assumed. Python's built-in sequence matcher was tried first. It
  works block by block, taking the longest identical stretch first. On a made-up test, a
  passage that repeats its lines set against a copy with about one word in eight dropped or
  changed, it lined up 17% of the words; the full method lined up 86%. A monologue that
  repeats a phrase is exactly the case that must work.
- **Speed:** two passages of 2,600 words each (more than ten minutes of speech) take about
  three hundredths of a second, because each row of the working table is one array
  operation.
- **Decided against:** an approximate or block-based matcher (above), and matching
  phrase to phrase (the two speakers break phrases in different places, which is the very
  thing being measured).

### S38. Words are matched on a key that ignores Devanagari marks

- **Chosen:** see "Match keys" in section 14.
- **Why:** observed. The `small` recogniser spells the same Hindi word differently from one
  recording to the next, and the differences are in the vowel signs and half-letters.
  Matching on exact spelling would line up far fewer Hindi words than English ones.
- **Decided against:**
  - *Exact spelling*: unfair to Hindi.
  - *"Close enough" matching by counting changed letters*: it needs a threshold for what is
    close enough, and makes the line-up many times slower.
  - *Turning Hindi into Roman letters first*: another tool to add, with errors of its own.
- **Honest limit:** some different words share a key. Order protects against most wrong
  matches; it is not a guarantee.

### S39. A pause is located by the phrases around it, never by word times

- **Chosen:** two words have a pause between them exactly when the pipeline put them in
  different phrases.
- **Why:** found by testing, not foreseen. The first version asked whether a pause lay
  between the end time of one word and the start time of the next. Comparing a recording
  with a copy of itself, it called 6 of 23 pauses missing on one side and extra on the
  other, because the recogniser had given the first word after each of those pauses a start
  time some tenths of a second inside the pause. Phrase membership has no such looseness: it
  is the definition of a pause (section 4).
- **Decided against:** widening the time allowance until the test passed. Any fixed
  allowance is wrong for some recording, and a large one starts matching the wrong pause.
- **A check worth keeping:** "a recording compared with itself shows no difference" is now
  an automated test, with word times deliberately pushed into the pauses.

### S40. A pause that cannot be located is called that, not called missing

- **Chosen:** if no matched word lies within three words of a reference pause on both
  sides, the row says "not found in your take" and it is left out of the differences.
- **Why:** a take that covers only the first half of the passage has not "missed" the
  pauses of the second half. Nor has a take in which the recogniser lost a sentence.
- **Decided against:** treating everything unmatched as a difference, which would bury the
  real ones.

### S41. Phrase pace is taken over the same words in both recordings

- **Chosen:** from the first matched word of the phrase to the last, in each recording,
  with pauses inside that stretch left out.
- **Why:** the two speakers break phrases differently, so "the reference's phrase 2 against
  the take's phrase 2" would compare different words. Leaving pauses out keeps to the rule
  of section 6: a pace is how fast you speak while speaking.
- **Decided against:** comparing each recording's own phrase WPM (different words), and
  comparing only the overall pace (it hides the one rushed line).

### S42. Loudness and the height of the voice are not compared

- **Chosen:** neither the level of each recording nor each voice's median pitch appears in
  the comparison. Pitch *variation* and *range*, in semitones, do. So does loudness
  *variation*, with a note that it also reflects how each recording was made.
- **Why:** a studio clip and a laptop microphone differ in level for reasons that have
  nothing to do with performance, and two people's voices differ in pitch by nature. Showing
  those differences would invite the user to "fix" them.
- **Decided against:** normalising both recordings to the same level and then comparing.
  It would look rigorous and still compare the microphones.

### S43. Differences are ranked by rough seconds, and worded as differences

- **Chosen:** the weights in section 14; at most five; always "the reference does X, you
  did Y", never "you should".
- **Why:** a list of thirty rows is a table, not guidance; the checklist's last step asks
  for the two biggest things to change. Ranking needs one scale, and seconds of silence is
  the one a listener feels. The neutral wording is because the reference is a target the
  user chose, not a rule: an actor may hold a pause longer than the original on purpose.
- **Honest limit:** the weights are judgement calls. A different weighting would put a
  rushed phrase above a missing pause, or below it.

### S44. The comparison does not go through the AI model

- **Chosen:** the comparison is produced entirely by code, and the profile coaching of
  section 13 is not told about the reference.
- **Why:** the brief asks for measured self metrics, qualitative profile targets and
  measured reference comparison to be kept separate. Every sentence in the comparison is a
  measured fact about two recordings, which code can state exactly; a model would add
  fluency and the chance of error to something that needs neither.
- **Decided against:** giving the model the comparison as extra findings. It is a
  reasonable later step, once the comparison itself has been tried on real recordings.

### S45. The waveform is a stored outline that nothing measures

- **Chosen:** the lowest and highest sample of each of up to 2,000 buckets, made by the
  worker when a recording is analysed, stored apart from the measurements, never
  normalised, and fetched only when the screen asks.
- **Why made by the worker and not in the browser:** the worker already has the decoded
  audio in hand, so the outline costs almost nothing. The browser would have to decode the
  file itself. By calculation, ten minutes of stereo audio at 48 kHz is about 230 MB once
  decoded; it also fails for formats that browser cannot play, and is impossible when the
  recording was not kept.
  Stored this way, the picture is available for every recording, kept or not.
- **Why lowest and highest, not an average:** an average over a bucket hides the peaks. A
  single loud consonant would vanish from a ten-minute picture.
- **Why not normalised:** stretching each recording to full height would make a whisper and
  a shout look the same, and would suggest the two were recorded equally loud.
- **Decided against:** drawing from the loudness timeline the result already contains (it
  is in decibels, four points a second: a different thing, and too coarse); a charting
  library (two filled shapes do not need one).

### S46. Feedback is one of three kinds, and a label is never a report

- **Chosen:** every piece of feedback is a **label** (what a pause meant), a **report**
  (the analysis got something wrong) or a **record** (noted; changes nothing by itself).
  Which one is fixed by its category and by what was measured.
- **Why:** the brief asks for two things that pull apart: the app should learn from
  corrections, and "intentional" or "accidental" must never change a measured pause. Kept
  apart, neither can leak into the other. "This pause was accidental" says nothing about
  whether it *was* a pause, so it must not nudge the pause threshold.
- **Decided against:** one "this pause is wrong" control, with the app working out what
  was meant. An accidental 3-second pause is still a 3-second pause.

### S47. A report counts towards one setting, chosen from what was measured

- **Chosen:** the setting is picked by code from the measurement at the spot: the length
  of the pause reported, or of the silence the detector heard where a pause was "missed".
  A report the measurement does not support counts towards nothing, and says why.
- **Why:** the brief says to adjust "the relevant setting only". Relevance is a fact about
  the audio, not about the button pressed. "You missed a pause" where the detector heard a
  380 ms silence is a case for a lower minimum pause. The same words where it heard no
  silence at all are not: no pause threshold could have found one there.
- **Decided against:** *category alone decides* ("missed pause" always lowers the
  threshold): three reports of pauses that were never silences would lower it for nothing.
  *Letting the AI model interpret feedback*: the brief requires fixed rules for anything
  that changes a number.

### S48. Two things are adjustable: the minimum pause, and the order of corrections

- **Chosen:** `min_pause_ms`, and a priority for each kind of correction: twelve when
  this was decided, fourteen since Phase 9 added the two about where the voice sits.
- **Why these:** each has a kind of feedback that is direct evidence about it, and a
  change the user can see and check. The minimum pause decides what counts as a pause, and
  a missed or false pause is evidence about exactly that. A priority decides what the
  coaching leads with, and "not useful" is evidence about exactly that.
- **Decided against:**
  - *The 5-second long-silence boundary*: the brief asks that feedback refine how a long
    silence is *read*, which labels do, not where the boundary is.
  - *The 2 seconds / 3 words needed for a trusted WPM, and the 180 WPM review flag*: no
    kind of feedback is evidence about them. "The WPM looks too high" is about one
    figure's inputs, not about when figures in general deserve trust.
  - *The coaching bands* (what counts as "fast"): they come from the profile's meaning,
    and "not useful" does not say which way a band is wrong.
  - *The speech detector's threshold*: see S49.

### S49. The speech detection threshold is not adjustable, because it was measured first

- **Chosen:** `vad_threshold` stays at 0.5. Reports that only the detector could answer
  ("a long silence was really speech", "a pause was missed where no silence was heard") are
  saved and count towards nothing.
- **What was built first:** exactly what the brief suggests: those reports moved the
  threshold in steps of 0.05 between 0.35 and 0.65. It worked in the tests, where the
  detector is scripted.
- **What the real detector showed** (section 15): from 0.35 to 0.65 it found the same
  phrases and pauses in every recording tried, clean or noisy; it changed the length of a
  silence by about 0.06 s; and it recovered only part of a phrase spoken 40 dB quieter.
  Below 0.3 it began to swallow real pauses.
- **Why that settles it:** the app would have told the user "speech detection adjusted
  after your reports" and then produced the same results. That is the claim to have
  learned that the brief warns against. The one real effect, a few hundredths of a second
  on a silence's length, is what the minimum pause already adjusts, in units the user can
  read.
- **Decided against:** *a wider range*, where it does change results: it changes them by
  losing pauses. *Keeping it adjustable but rarely triggered*: an adjustment that does
  nothing is worse than none.

### S50. The minimum pause may move between 250 and 800 ms

- **Chosen:** explicit bounds, enforced where a value is calculated and again where it is
  stored.
- **Why 250 ms:** below about a quarter of a second, a silence is usually part of saying a
  word (the closure before "p", "t", "k"). A quarter of a second is also a cut-off often
  used for a "silent pause" in research on speech.
- **Why 800 ms:** a silence that long is a pause for any speaker. A threshold above it
  would start hiding pauses nobody would dispute. It also stays below the 1-second line
  where a pause becomes "medium".
- **Decided against:** *no bounds, trusting the rules to behave*. The brief requires
  explicit bounds, and a bound is what turns "the rules should not run away" into "they
  cannot".

### S51. Three reports that agree, from two recordings, making up three-quarters

- **Chosen:** the rules in section 15: at least 3 reports one way, from at least 2
  recordings, at least 75% of the last 10 reports about that setting.
- **Why three:** it is the smallest number that is not a single slip or a coincidence of
  two. **Why two recordings:** one recording can be unusual (a noisy room, a cold) and
  should not retune the app for all the others. Revisions of one recording count as one.
  **Why 75%:** three for and two against is the user disagreeing with themselves.
  **Why the last ten:** what suited the user's recordings months ago should fade.
- **Decided against:**
  - *Adjusting a little on every piece of feedback*: one click would move a threshold, and
    the brief says not to claim learning from one or two noisy events.
  - *A statistical test*: with three to ten reports it would add an air of precision and
    nothing else.
  - *Weighting reports by how sure the detector was*: no such confidence is measured.
- **Not known:** whether three is the right number in real use. It is a cautious guess.

### S52. One adjustment is a small step, steered by the silences reported

- **Chosen:** 50 or 100 ms at a time, to the grid value that would have got the typical
  reported silence right.
- **Why steered:** the reports carry a measurement. If the missed silences were around
  420 ms, moving to 400 fixes them and moving to 450 would not; a fixed 50 ms step would
  need a second round of reports to get there.
- **Why capped at 100 ms:** three reports are a small sample. A cap means three reports
  about one extreme case cannot take the threshold from 500 to 250 in one go.
- **Why the median:** one odd report (a 260 ms silence among 420s) does not drag it.
- **Decided against:** *jumping straight to the evidence*; *a fixed step* (see above);
  *averaging old and new value*, which lands on values like 437 ms that mean nothing to a
  reader.

### S53. A report is used once, and stops counting once it is answered

- **Chosen:** an adjustment spends every report waiting on its setting. Separately, a
  report counts only while it would still be a complaint under today's value.
- **Why spend them:** so each step is earned by new evidence gathered under the new value.
  Otherwise ten reports of 300 ms silences would walk the threshold from 500 to 300 in the
  same instant, three steps at once.
- **Why "still a complaint":** feedback can be given on an old result at any time. A
  missed silence of 420 ms on a result made at 500 ms is no reason to go below 400.
- **Decided against:** *counting every report ever made*: a setting could never settle.

### S54. Moving back the way a setting just came needs five reports

- **Chosen:** if the last adjustment still in effect lowered a setting, raising it needs 5
  agreeing reports instead of 3; and the other way round.
- **Why:** the brief asks that thresholds do not oscillate. A user who reports both missed
  and false pauses near the threshold would otherwise push it down, then up, then down,
  making neighbouring recordings hard to compare.
- **Not affected:** undo. That is the user's own decision and takes effect at once.

### S55. One calibration for every profile and every language

- **Chosen:** a single set of adjusted values, whatever delivery profile or language a
  recording was analysed with.
- **Why:** the brief says to keep separate settings only where real evidence supports it.
  What counts as a pause depends on the speaker and the microphone, and nothing measured
  so far says it depends on which profile was chosen. Splitting three reports four ways
  would also mean none of the four ever had enough to go on.
- **Decided against:** *per-profile calibration* (overfitting each profile to a handful of
  recordings, which the brief warns against); *per-language* (plausible, since Hindi and
  English differ in rhythm, but untested here, and it can be added later because every
  report already records which analysis it was about).

### S56. Confidence is a count, said in a word

- **Chosen:** every adjustment shows how many reports were looked at, how many agreed and
  from how many recordings, plus low (3 or 4 agreeing), medium (5 to 7) or high (8 or more).
- **Why:** the brief asks for "confidence/sample count". With samples this small the count
  *is* the confidence; a percentage would pretend to more. The word is there so the first
  adjustment is plainly called "low".
- **Decided against:** *a probability or a score out of 100*.

### S57. "The WPM looks wrong" changes nothing and opens a review

- **Chosen:** the report is saved, no figure moves, and the user is shown the words, the
  speaking time and the word timing behind the figure, each with the feedback that would
  correct it.
- **Why:** required by the brief ("do not blindly multiply WPM by an arbitrary correction
  factor"), and right in itself: a WPM is a division. If it is wrong, one of its two
  inputs is wrong, and the user is the only one who can say which.
- **Decided against:** *a correction factor learned from "too high" reports*: every later
  recording would be multiplied by a number that described an earlier one's mistake.

### S58. A corrected transcript changes the word-based figures, by the pipeline's own code

- **Chosen:** segment WPM = corrected word count ÷ the phrase's measured length. The
  functions that work it out are the ones the audio pipeline uses, given the corrected
  words. Everything measured from sound is copied unchanged.
- **Why:** the brief requires WPM to be "recalculated from the corrected transcript" and
  not patched. Reusing the pipeline's functions means a corrected figure and a measured
  one can never be calculated in two different ways.
- **Why the phrase's length is kept:** it comes from the speech detector, not from the
  words. Changing the words does not change when the speaker was speaking.
- **Why untouched phrases keep their stored figures exactly:** recalculating them from
  stored, rounded times could move a figure in its last digit, and a figure that changes
  when nothing about it was corrected is a small lie.
- **Decided against:** *running the recogniser again with the corrected text as a hint*
  (needs the audio, and may still disagree with the user); *forced alignment* to get real
  word times (a second model for a modest gain: see S7).

### S59. A label changes how a pause is read, never the pause

- **Chosen:** accidental pauses are left out of the *judgement* of pause length and of
  held silence, and named in a finding of their own. Intentional pauses are noted and
  never made an issue. The measured figures are stated first, unchanged, in the same
  sentence.
- **Why:** required by the brief, and it is the honest reading: a 3-second stop while
  finding the next line is in the recording, so it is in the figures, but it is not "a
  held silence that fits the profile".
- **Decided against:** *removing labelled pauses from the statistics* (forbidden, and it
  would make the figures describe a recording that does not exist); *a second set of
  "adjusted" figures on the results screen*: two numbers for one thing invite reading the
  wrong one. The one place the leave-out appears is inside the finding's sentence, next
  to the measured figure.

### S60. A label does not train anything

- **Chosen:** labels apply to the one pause they are put on, in the one result.
- **Why:** to generalise, something measurable would have to separate an intended pause
  from a slip, and nothing does. Length does not: a dramatic pause and a lost line can
  both last three seconds.
- **Decided against:** *guessing labels for unlabelled pauses* from the user's history.
  The app would be inventing intention, which section 4 rules out.

### S61. A priority moves a kind of correction down the list and never removes it

- **Chosen:** a multiplier between 0.4 and 1.0 on the weight that orders issues.
- **Why a multiplier on the order, and not a filter:** the top three corrections are a
  choice among issues. "Not useful" is a reason to choose differently, not a reason to
  stop measuring. The finding stays in the summary and the list.
- **Why per kind of finding:** it is the level at which a rating means something for
  another recording. "Slow your overall pace" on one take and on the next are the same
  advice.
- **Why 0.4 and not 0:** at 0 a kind of issue could never be a correction again, however
  large it became.
- **Not built:** telling "the advice was wrong for me" from "this wording was poor". Both
  are "not useful", and both lower the priority.

### S62. Short silences are measured and stored with every result

- **Chosen:** every gap between speech regions that is shorter than the minimum pause is
  kept in the result, with the phrase it lies in.
- **Why:** without it a report of a missed pause is only a time and an opinion. With it,
  the app can say "the detector heard 356 ms of silence there", decide what the report
  counts towards, and show the candidates so the user picks a real one.
- **Cost:** about forty entries for a two-minute recording.
- **Consequence:** results stored before Phase 6 do not have them. A missed-pause report
  on one is saved and cannot count; analysing the recording again adds them.

### S63. Old results are never recalculated; a new analysis is a new revision

- **Chosen:** an adjustment affects only recordings analysed afterwards. A kept recording
  can be analysed again, which adds a revision beside the earlier result. Where an older
  and a newer result meet, a notice says they were cut differently.
- **Why:** required by the brief, and the only way a result stays traceable to its
  settings. A history in which last week's pause counts quietly changed would make every
  comparison across time meaningless.
- **Decided against:** *recalculating everything in the background after each adjustment*;
  *re-cutting old results from their stored short silences without the audio*, which
  could move the pauses but not the loudness and pitch per phrase, giving results that
  are half old and half new.

### S64. The AI model has no part in calibration

- **Chosen:** classifying feedback, counting reports, moving settings, undo and reset are
  all ordinary code. The model only ever sees labels, as text beside a pause, when it
  words coaching.
- **Why:** required by the brief ("deterministic code must apply and validate numeric
  setting changes"), and consistent with S21: numbers come from code.
- **Phase 7:** the brief allows the model to *summarise* feedback. In Phase 6 that was
  left out, on the grounds that a summary would add nothing to the list. Phase 7 built
  it, in the narrow form described in S69 to S71. This decision still holds as written:
  what the model does there changes no setting and is read by nothing.

### S65. A word points at a moment; the moment is checked like any other

- **Chosen:** "the pause came after this word" is turned into a time, halfway between that
  word and the next, and sent as an ordinary missed-pause report. The existing rule finds
  the silence: the nearest within half a second.
- **Why:** a speaker remembers where in the sentence they paused, not at what second. And
  when the recording was not kept, there is no player to point with.
- **Why no new rule:** word times and silences come from two different models and differ
  by up to a tenth of a second or so. A rule that demanded the silence lie exactly between
  the two words would fail on that disagreement. The half second already in use for the
  player's position covers it: six of six on the test recordings.
- **Decided against:** *sending the word's number and resolving it on the backend* (a
  second way of pointing at a moment, with a second rule to keep in step); *a tighter
  tolerance for words* (no measurement says it would be more right, and it would be less
  forgiving of word timing on a real voice).

### S66. Reports on a reference count, but a setting needs one from a take

- **Chosen:** as described under "Feedback on a reference recording": the same reports,
  the same evidence, and one more condition before a setting moves.
- **Why they count at all:** the alternative, refusing them (the Phase 6 choice), left the
  user unable to say that the original performance pauses where the app saw none, which is
  the very thing the Monologue screen (since Phase 8: step 1 of Daily Practice) is for.
- **Why not alone:** music, sound effects and edits make a film clip mislead the detector
  in ways a practice recording does not. A setting tuned on those would be tuned to the
  film.
- **Why one, not a majority:** with one monologue there is one reference and it may be the
  only place the short pauses are. Requiring most reports to be about takes would make the
  reference's evidence nearly worthless. One take showing the same thing is the smallest
  proof that it is not only the film.
- **Decided against:** a separate minimum pause for references (two recordings cut by
  different rules cannot be compared pause by pause, and the brief rules out settings per
  profile).

### S67. A reference's pauses are not labelled

- **Chosen:** "intentional" and "accidental" are refused on a reference.
- **Why:** a label has exactly one effect, on how the coaching reads a pause (S55), and a
  reference is never coached (S34). A control that does nothing should not be offered.
  Besides, whether the original actor meant a pause is not something the user knows.

### S68. The facts are written one thing at a time, each with what it means

- **Chosen:** the three rules under "What the feedback adds up to": one fact about one
  thing, no feedback counted in two facts, and the meaning said where it could be mistaken.
- **Why:** measured. With two labels in one sentence, a reader (the model) took the two
  lengths for one pause measured twice. With ratings and their subjects in two sentences,
  it counted the ratings twice. The facts are read by a person on the screen, and a person
  skimming makes the same mistakes.
- **Decided against:** a table of counts (compact, and silent about what any count means).

### S69. The AI model does not restate the counts

- **Chosen:** every count and figure in "What your feedback adds up to" is worded by code.
- **Why:** measured, in three versions (Design 1 above). The model kept every number
  correct and attached it to the wrong thing: "feedback on 12 recordings" for 12 pieces of
  feedback on 3 recordings, in 5 runs of 5. The check that guards coaching looks at
  numbers and found nothing wrong, because nothing was wrong with the numbers.
- **What this says about section 13:** coaching is safe from the same mistake for a
  reason built in from the start (S21): the app prints each finding beside the model's
  words, and the model is told not to repeat its figures. Here the model was asked to
  repeat them, which is the one thing it should not be asked.
- **Decided against:** *a stricter check* (it would have to understand the sentence);
  *telling the model to write no numbers* (it wrote them anyway, 5 runs of 5).

### S70. The AI model does not describe the notes in its own words

- **Chosen:** no sentence written by the model about the notes is shown.
- **Why:** measured (Design 2 above). Three wordings of the task were tried. The best was
  faithful on English notes and said something false about the speaker in 3 of 8 runs on
  Hinglish notes, turning a note that says the pace does not feel that fast into "your
  speaking speed was too high". This app's user writes in Hinglish.
- **Decided against:** shipping the best wording with a warning beside it. A sentence that
  is wrong three times in eight is not made right by a caption.

### S71. The AI model picks; code does everything a pick needs

- **Chosen:** the model chooses three notes by number; code decides which notes it may
  choose from, names the largest group for it, and shows the chosen notes word for word.
- **Why:** it is the part of Design 2 that was right every time, with the rest removed. It
  works the same in any language, since nothing is translated. And it cannot say anything
  false.
- **Why three, five and three words:** three notes fit in a glance; with fewer than five
  there is nothing to choose from that is not already on screen; a note of one or two
  words was picked in 9 runs of 10 when offered and says nothing. None of the three
  numbers has been tested against anything but that.
- **Decided against:** *letting code pick* (the longest note in each group, say: it would
  be repeatable, and blind to what the notes say); *no AI part at all* (a fair choice,
  and what Phase 6 did; it was built because it could be made unable to mislead).

### S72. A pick is a reading aid: it is asked for by hand, replaced, and marked when stale

- **Chosen:** the model is asked only when the user presses the button. One pick is kept.
  When the notes change it is marked out of date and still shown.
- **Why:** it costs the model's time and, on a busy worker, a wait behind an analysis, so
  it should be the user's choice. It is not a record of anything, so there is no reason
  to keep the old ones. And the facts beside it never go out of date, which is where the
  eye should go first.

### S73. A take is compared only with the original it was recorded for

- **Chosen:** a take belongs to one monologue and is compared with that monologue's
  reference. A take of no monologue is compared with nothing.
- **Why:** the comparison lines two recordings up by their words (S36), so it only means
  something for two recordings of the same text. Asking the user to pick a reference
  each time left "the same text" to chance; recording the take *for* a monologue settles
  it when the take is made. It also completes G6 in the main document: the comparison
  with a real recording now has one place, and the profile coaching another.
- **Decided against:** *guessing the monologue from the words* (line a new take up with
  every reference and keep the best match). It would usually be right, and when wrong it
  would file a take under a monologue the user never chose. The user knows which
  monologue they are practising; the app asks.
- **What did not change:** the endpoint still compares any analysis with any reference.
  The restriction is in which pairs the screens ask for.
- **Honest limit:** nothing checks that the take really is of that monologue. A take of
  other words is compared anyway, and the result says "only 12% of the reference's words
  were found", as it always has.

### S74. The script shows only what was measured

- **Chosen:** the script of the original is its segments, its pauses and its emphasis
  candidates, rearranged. No pause is added, moved or named, and no word is marked that
  is not already a candidate.
- **Why:** step 2 of the routine is "mark the delivery": the actor decides what the
  pauses and stresses are *for*. The app can say where the original paused and for how
  long. It cannot say why, and section 4 already rules out guessing.
- **Decided against:** *marking "dramatic" pauses or "key" words*, which would be the
  app's opinion printed in the same ink as a measurement; *having the AI model annotate
  the script*, for the same reason and because nothing could check it.

### S75. Resonance is the average spacing of the first three formants, found by LPC

- **Chosen:** one figure in Hz, the step of the evenly spaced ladder that best fits the
  median F1, F2 and F3 (section 9a), with the formants found by linear prediction on
  25 ms slices of the louder, voiced part of the speech.
- **Why:** it is one number with a physical meaning (it follows the length of the vocal
  tract), it needs no new dependency (`librosa.lpc` is already installed for pitch), and
  it runs at about 85 times real time.
- **Considered:** *F1, F2 and F3 shown separately*: three numbers a reader has to
  combine, and F1 and F2 move with every vowel. *The plain average of the formants*, or
  *F3 alone*: either works roughly; the fitted spacing uses all three and weighs the
  steadiest most. *Spectral centroid or tilt* ("brightness" of the whole sound): cheap,
  and it changes with the microphone, the room and how loudly one speaks. *Praat through
  the `parselmouth` package*: the standard tool for formants, and a good one; it would
  add a large dependency for one figure, and its usual settings differ by the sex of the
  speaker, which is the thing this app must not assume.
- **Honest limit:** validated on synthesised voices only.

### S76. Three formants under 4,000 Hz, the same for every voice

- **Chosen:** look below 4,000 Hz, for three formants, with a filter of order 8, whoever
  is speaking.
- **Why:** measured (section 9a). Four formants under 5,500 Hz separated clean voices
  better (a gap of 119 Hz against 86) and moved by up to 277 Hz with hiss 30 dB below
  the voice. Three under 4,000 Hz moved by 25 Hz. A figure that depends on the
  microphone's hiss more than on the voice is of no use for practice at home.
- **Decided against:** *a higher limit for higher voices*, as formant tools usually do. It
  measures each kind of voice better and needs to be told which kind it is. Here that
  would settle the answer before the measurement.
- **Also tried:** limits of 3,800 and 4,200 Hz, formant widths of 350 and 700 Hz, and a
  filter of order 10; each was worse in separation or in noise (the table in section 9a).

### S77. Three stated ranges on each scale, and a percentage that is a position

- **Chosen:** lower, neutral and higher ranges for pitch and for resonance, and a
  percentage saying how far into its range a value lies: from the neutral edge to the far
  end in the outer ranges, and from the edges to the middle in the neutral one.
- **Why:** the user asked for ranges with a percentage, and a position is the one
  percentage this app can stand behind. It is arithmetic on a measured value and two
  stated numbers, so it can be checked by hand and explained in a sentence.
- **Decided against:** *"72% feminine"*, a single likelihood. It reads as a probability
  that a listener hears the voice that way, and nothing here measures listeners. It
  would need a model trained on labelled voices, which could not be explained or
  checked, and would be a classifier of people, which this app is not. *A curve instead
  of a straight line* (so that the middle of a range counts for more): no measurement
  says what curve. *No neutral range*: a voice at 150 Hz would flip between two words on
  a difference no one can hear.

### S78. The ranges describe how a voice is typically heard, and are stored with the result

- **Chosen:** the words on screen are "lower range", "neutral range" and "higher range",
  each with one explanatory line ("typically heard as a masculine voice", "could be heard
  either way", "typically heard as a feminine voice"). The eight numbers are in
  `VoiceRangeSettings`, with a version, and a copy travels with every result.
- **Why:** the feature exists because listeners do hear pitch and resonance that way, so
  hiding the words would hide its purpose. Naming the *range* and saying how it is
  *heard* keeps the statement about a sound. The speaker is never called anything.
- **Where the numbers come from:** pitch, from the figures usually given for adult
  speaking voices; resonance, from this app's own fourteen voices (section 9b). Both are
  stated as rough.
- **Decided against:** *labelling the speaker* ("male voice", "female voice"): it is a
  guess about a person from two numbers, wrong for many people, and unkind when wrong.
  *Letting feedback adjust the ranges*: there is nothing for a report to be right about;
  how a voice is heard is not something one user's recordings can calibrate.

### S79. One marker from two scales, with "mixed" when they disagree

- **Chosen:** lower, neutral, higher or mixed (the table in section 9b). A neutral scale
  lets the other decide; opposite scales give "mixed"; a missing one is left out.
- **Why:** a speaker working on their voice needs to know when pitch and resonance point
  different ways. That is common, and it is exactly what a pitch-only tool cannot show.
- **Decided against:** *averaging the two percentages into one score*: Hz of pitch and Hz
  of formant spacing are different things, and any weighting between them would be
  invented. *Letting pitch decide alone*: simpler, and it would hide the case above.

### S80. A goal is the speaker's choice, and without one nothing is judged

- **Chosen:** no goal by default. A speaker may choose "keep my voice lower" or "keep my
  voice higher". Only then do the two voice findings become issues or strengths, and only
  then is anything about them coached.
- **Why:** "No target pitch" (section 9) still holds as the app's own position: a
  register is a property of the person. A goal is the person saying what they are
  working towards, in either direction, for any reason. The goal changes how the result
  is read and never what is measured, which the end-to-end run confirmed.
- **Decided against:** *a goal named for a kind of person* ("sound more masculine"): the
  request was to keep it general, and a direction on a scale is all the app can act on.
  *A numeric target* ("reach 120 Hz"): it invites pushing the voice to a number;
  "stay in this range, phrase by phrase" is the gentler instruction and the one a drill
  can serve. *Storing the goal with the monologue*: it belongs to the speaker, so the
  browser remembers it and each recording records the one it was made with.

### S81. With a goal, the model is not shown how a range is heard, and its words are checked

- **Chosen:** the sentence "typically heard as…" is written by code for the user and
  removed from what the AI model reads. With a goal set, the model's wording is checked
  for words about the speaker's sex or gender; a hit is sent back once, then removed.
- **Why:** observed, not supposed. Shown the sentence, the model wrote "to avoid being
  perceived as feminine". An instruction in the prompt was added too, and S29's lesson
  applies: an instruction makes a thing rarer, a check makes it not appear.
- **Decided against:** *checking only when the sentence slips through*: the model can
  bring the idea from its own training without being shown it. *Checking every
  coaching, goal or not*: with no goal the voice findings are not offered to the model
  as anything to write about, and a monologue may well be about a man or a woman.
- **Honest limit:** the check is a list of words. It does not catch the same thought said
  without them.

### S82. Resonance is an estimate under 30 dB of signal-to-noise, and not given under 20

- **Chosen:** those two limits, plus "estimate" for a phrase with under about a second
  and a half of usable sound, and no figure under a fifth of a second.
- **Why:** hiss moves the figure one way only, towards brighter, and the lower range is
  100 Hz wide. At 15 dB one deeper voice moved by 175 Hz into the higher range.
- **What was tried first:** 20 and 10 dB, from the table of typical shifts. The
  end-to-end run then returned exactly that wrong reading, labelled "estimate". A label
  does not make a wrong range right, and for someone practising towards a lower voice it
  is a discouraging error. The limits moved so that a figure given as measured shifted by
  about half a range at worst in testing, and one that can cross a whole range is not
  given.
- **Cost:** in a noisy room there is no resonance figure at all, and the app says why.
  Pitch, which is far less affected, is still given and decides the marker alone.

### S83. A step counts as voiced at 0.3, not 0.5

- **Chosen:** `pitch_voiced_probability` 0.3, as a recorded setting, with the settings
  version raised to 2.
- **Why:** measured (section 9). At 0.5 a deeper voice kept 6 to 20% of its steps and a
  short recording fell under the 30 a pitch needs; at 0.3 it kept two to three times as
  many and the median moved by 3 Hz or less for thirteen voices of fourteen.
- **Decided against:** *no probability test, only the tracker's voiced flag*: most steps
  of all, and the spread of pitch grew by up to 0.7 semitones for two voices, which
  would feed straight into "pitch variation". *Lowering the 30-step minimum instead*: it
  treats the symptom, and a median of 15 steps is a poor median.
- **What it changes for older results:** nothing. They keep settings version 1 and their
  own figures. Pitch variation and emphasis candidates in new results rest on more
  steps, so a recording analysed again can show slightly different figures for both.

## 18. Glossary

| Term | Meaning |
| --- | --- |
| **Sample** | One measurement of the sound wave. 16,000 of them per second here. |
| **Sample rate** | Samples per second, in hertz. |
| **Mono** | One audio channel. |
| **Clipping** | Distortion from a sound too loud for the recorder; samples stick at the maximum. |
| **VAD** | Voice activity detection: deciding where speech is. |
| **Silero VAD** | The neural network used for VAD. |
| **Speech region** | One stretch the VAD marked as speech. |
| **Segment** | Regions joined across gaps under 0.5 s: roughly one phrase. |
| **Pause** | Silence of 0.5 s or more between two segments. |
| **Section** | Segments grouped between long silences (5 s or more). |
| **Whisper** | The speech-recognition model. |
| **faster-whisper** | The library that runs Whisper efficiently on a CPU. |
| **Word timestamp** | The start and end time the recogniser gives a word. |
| **Confidence** | The recogniser's own 0-to-1 estimate that a word is right. |
| **WPM** | Words per minute. See section 6 for the three kinds. |
| **Articulation rate** | Speaking rate with pauses left out; here, speech-active WPM. |
| **RMS** | Root mean square: a measure of signal strength over a short window. |
| **Decibel (dB)** | A logarithmic unit for ratios. +20 dB is ten times the amplitude. |
| **dBFS** | Decibels relative to the loudest possible digital value. Always 0 or negative. |
| **Signal-to-noise ratio** | How far the voice is above the background, in dB. |
| **F0 / fundamental frequency** | The rate of vocal-fold vibration, heard as pitch. In Hz. |
| **Voiced** | Sounds made with the vocal folds vibrating, such as vowels. Only these have pitch. |
| **pYIN** | The pitch-tracking algorithm used. |
| **Semitone** | One piano key step. Twelve semitones double the frequency. |
| **Resonance** | How deep or bright a voice sounds, apart from the note it speaks on. Set by the shape of the throat and mouth. |
| **Formant** | A band of frequency that the throat and mouth strengthen. Numbered from the lowest: F1, F2, F3. |
| **Formant spacing** | The average distance between neighbouring formants, in Hz. The app's figure for resonance: lower is deeper. |
| **Vocal tract** | The tube from the vocal folds to the lips. A longer one puts the formants closer together. |
| **LPC (linear prediction)** | A way of fitting a small filter to a slice of sound. The peaks of the filter are the formants. |
| **Pre-emphasis** | Boosting the higher frequencies slightly before analysis, so the weaker upper formants can be found. |
| **Voice range** | Where a voice sits: its pitch and its resonance, each placed in the lower, neutral or higher range. |
| **Marker** | One word for pitch and resonance together: lower, neutral, higher, or mixed when they disagree. |
| **Voice goal** | The speaker's own choice to keep their voice lower or higher. Optional. Changes the coaching, never a measurement. |
| **White / pink noise** | Hiss with equal energy at every frequency, or with more at the low end. Used to test how noise moves a measurement. |
| **Percentile** | The value below which a given share of measurements fall. |
| **Median** | The middle value when sorted. Less affected by extremes than the average. |
| **Standard deviation** | A measure of how spread out values are around their average. |
| **Temperature** | In a language or speech model, how much randomness is used when choosing output. 0 means none. |
| **Ollama** | A program that runs AI language models on your own computer. |
| **LLM** | Large language model: an AI model that reads and writes text. |
| **Grounding** | Making sure everything an AI model states is backed by supplied facts. |
| **Finding** | One plain statement of fact about a recording, written by code, with its figures in it. |
| **Band** | A range of values given a word: under 2 semitones is "narrow". |
| **Role** | What a finding means for the chosen profile: an issue, a strength, or just context. |
| **Template** | A fixed sentence with gaps that code fills in. |
| **Prompt** | The text sent to a language model: instructions, then data. |
| **Token** | The pieces of text a language model reads and writes: roughly a word, or part of one. |
| **Context** | How many tokens a model can take in and produce in one go. |
| **JSON schema / structured output** | A description of the exact shape an answer must have; Ollama can refuse to generate anything that does not fit it. |
| **Reference** | A recording you supply to compare your takes with, such as the original performance. Measured like any take. |
| **Take** | One of your own recordings. |
| **Monologue** | One piece being practised: its reference recording (the original) and the takes recorded for it. A take is compared with the original of its own monologue. |
| **Script (of the original)** | The reference's phrases, pauses and emphasis candidates laid out as lines to read. Nothing in it is measured anew. |
| **Line-up (alignment)** | Working out which word of one recording is which word of the other. |
| **Match key** | A word with case, punctuation and combining marks removed, so two spellings of one spoken word compare as equal. |
| **Longest common subsequence** | The longest list of items that appears in two lists in the same order, not necessarily next to each other. |
| **Coverage** | The share of the reference's words that were lined up with a word in the take. |
| **Waveform** | A picture of the sound wave itself: how far the air pressure swings, moment by moment. |
| **Outline (envelope)** | The lowest and highest value of the waveform in each small stretch of time. What is actually drawn. |
| **Parameters (as in "8b")** | The numbers inside a model that were learned in training; 8 billion here. More usually means more capable and slower. |
| **Feedback** | Something the user says about one analysis: a label, a report or a record. |
| **Label** | The user's word for what a pause meant: intentional or accidental. Changes the coaching's reading of it, never the measurement. |
| **Report** | Feedback saying the analysis got something wrong. Counts towards moving one setting. |
| **Calibration** | The current values of the settings feedback may adjust, and the history of how they got there. |
| **Adjustable setting** | A setting with a default, an allowed range and a step, that enough agreeing reports can move. Here: the minimum pause, and the priority of each kind of correction. |
| **Bounds** | The lowest and highest value a setting is allowed to take. |
| **Minimum pause** | The shortest silence that counts as a pause. 500 ms by default. |
| **Short silence** | A silence the detector heard that was shorter than the minimum pause. |
| **Priority** | A number from 0.4 to 1.0 that the weight of a kind of issue is multiplied by, deciding how readily it becomes one of the corrections. |
| **Revision** | A later result made from a recording that already has one: after a transcript correction, or a fresh analysis. |
| **Decibel difference (as in "40 dB quieter")** | A ratio. 20 dB quieter is a tenth of the amplitude; 40 dB quieter is a hundredth. |
| **Fact (about the feedback)** | One sentence counted and written by code from the stored feedback. Never worded by the AI model. |
| **Note** | Up to 280 characters the user typed beside a piece of feedback. |
| **Pick** | The few notes the AI model chose as the most telling. Shown word for word; the model's own words are never shown. |
| **Extractive** | Summing something up by choosing pieces of it, not by writing new sentences about it. What the pick is. |
| **Enum (in a schema)** | A list of the only values an answer may contain. Here: the names of the notes the model may pick. |
