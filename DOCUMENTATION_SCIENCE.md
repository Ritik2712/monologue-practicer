# Monologue Coach — Audio Science and AI Documentation

How a recording is turned into numbers — speaking rate, pauses, loudness, pitch — and how an
AI model will later turn those numbers into coaching.

- Start with [DOCUMENTATION.md](DOCUMENTATION.md) for the big picture and the general glossary.
- How jobs are queued, run, cancelled and stored is in
  [DOCUMENTATION_BACKEND.md](DOCUMENTATION_BACKEND.md). This file is about **what is
  measured and why it is measured that way**.

Anything not built yet is marked **Planned**.

**Last updated:** end of Phase 3. All measurements below are built, and the delivery
profiles exist as descriptions. The AI coaching (section 13) is not built.

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
10. [Emphasis candidates, hesitation sounds, breaths](#10-emphasis-candidates-hesitation-sounds-breaths)
11. [How much to trust a number](#11-how-much-to-trust-a-number)
12. [The settings](#12-the-settings)
13. [The AI model (planned)](#13-the-ai-model-planned)
14. [Accuracy and limits](#14-accuracy-and-limits)
15. [Science decisions](#15-science-decisions)
16. [Glossary](#16-glossary)

All code for this document is in `backend/app/pipeline/`.

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
 │              │  fillers.py       hesitation sounds
 └──────┬───────┘
        ▼
 ┌──────────────┐  runner.py        everything assembled into one result, with quality
 │ 6. Result    │                   labels and warnings
 └──────────────┘
```

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

Code: `segmentation.py` (`build_segments`, `classify_pause`).

## 5. Words

### Recognising them

Speech is turned into text by **Whisper**, an open speech-recognition model, running locally
through the **faster-whisper** library. The model size is `small` (about 480 MB).

Whisper works on windows of up to 30 seconds. For each word it also reports a start time,
an end time and a **confidence** between 0 and 1.

Three choices in how it is run (reasons in section 15):

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
This happened in testing (section 15, decision S9).

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
with probability below 0.5 are thrown away. The search range is 65–500 Hz.

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

### No target pitch

The app never says a pitch is too high or too low, and no delivery profile has a target
pitch. A voice's register is a property of the person. Only movement relative to the
speaker's own median is reported.

### When pitch is unavailable

With fewer than 30 voiced steps (about half a second) there is too little to describe a
voice. Pitch is then "unavailable" with the warning `pitch_unavailable`, rather than a
number computed from almost nothing.

Code: `acoustics.py` (`measure_pitch`, `summarize_pitch`, `semitones`).

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
| `version` | 1 | Goes up whenever a default changes |

**Every result stores a full copy of the settings that produced it.** Months later it is
still possible to say "this was measured with a 0.5 s pause threshold". When the calibration
feature (Phase 6) starts adjusting these values, old results will stay explainable and will
not be silently recalculated.

Settings that contradict each other are refused when created; for example, a minimum pause
longer than the long-silence boundary.

## 13. The AI model (planned)

**Not built. This section records what has been decided for Phase 4.**

### What it will be

A language model running on this computer through **Ollama**, using `llama3.1:8b`, which is
already installed here. No cloud model, and no fallback to one.

### The division of labour

| | Done by | Why |
| --- | --- | --- |
| Every number: WPM, pause lengths, pitch, timestamps | The code in this document | Arithmetic must be exact and repeatable |
| Explaining what the numbers mean for a performance, and suggesting drills | The AI model | Language is what it is good at |

**The model will never be given audio**, and will never calculate. It will receive the
finished result — transcript, segments with times, the metrics, the warnings — plus a
description of the chosen delivery profile, and will be asked to write:

1. the top three corrections, most important first;
2. the exact segments and timestamps to practise, each with a reason taken from the numbers;
3. a concrete drill for each;
4. what is already working, backed by a measurement;
5. targets for the next take;
6. a note wherever a measurement was an estimate or unavailable.

### Keeping it honest

Language models can state numbers that sound right and are not. Two safeguards are planned:

- **Checking its answer.** Every timestamp, segment and figure the model mentions will be
  compared with the measured result. Anything that does not match will be removed or the
  answer rejected.
- **A fallback that is not the model.** If Ollama is not running or its answer fails the
  check, the measured result is still shown, with plain correction notes generated by fixed
  rules.

### Delivery profiles

**This part is built**: the profiles exist, in `backend/app/profiles.py`, and the General
Practice screen shows them. Using them to judge a performance is the part still to come.

Walter White, Joker and Thomas Shelby are **descriptions of a delivery style in words**, not
measurements of any actor's voice. The app has no reference recording of them and does not
claim to compare against one. A real, measured comparison will only happen when the user
supplies a reference recording themselves (Phase 5).

Each profile names the measurements that matter most for the style, and says what the app
cannot hear at all:

| Profile | In a sentence | Measurements it depends on most | Not measured |
| --- | --- | --- | --- |
| Walter White | Controlled and deliberate | Pace variation (low), median pause, loudness variation (low) | Clarity of consonants |
| Joker | Expressive and unpredictable | Pace variation (high), pitch variation, loudness variation (high) | Whether a contrast was purposeful |
| Thomas Shelby | Composed and economical | Speech-active WPM (unhurried), longest pause, loudness variation (low) | Crispness of phrasing |
| Custom / neutral | No style target | None singled out | — |

Today the screen marks those measurements with a "Profile focus" tag and stops there. It
does not yet say "too fast for Thomas Shelby". Turning the description and the numbers into
that kind of statement, carefully, is the AI coaching step.

There are deliberately **no target numbers** in a profile, such as "Walter White speaks at
130 WPM". Any such number would be invented.

## 14. Accuracy and limits

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
| Pitch | Occasional octave errors; unreliable on creaky or breathy voice and in noise. |
| Loudness | Relative to the recording only (section 8). |
| Emphasis | Detects louder and higher. Misses emphasis by slowing down or pausing. |
| Hesitation sounds | A lower bound. |
| Breaths | Not detected. |
| Intention and emotion | Not measured, and not inferred from the measurements. |

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
loading the model; recognising the words of a 133-second recording in about 20 seconds.

## 15. Science decisions

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

### S21. Numbers come from code; the AI model only explains *(planned)*

- **Chosen:** see section 13.
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

## 16. Glossary

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
| **Percentile** | The value below which a given share of measurements fall. |
| **Median** | The middle value when sorted. Less affected by extremes than the average. |
| **Standard deviation** | A measure of how spread out values are around their average. |
| **Temperature** | In a language or speech model, how much randomness is used when choosing output. 0 means none. |
| **Ollama** | A program that runs AI language models on your own computer. |
| **LLM** | Large language model: an AI model that reads and writes text. |
| **Grounding** | Making sure everything an AI model states is backed by supplied facts. |
