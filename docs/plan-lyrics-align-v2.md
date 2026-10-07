# Plan: robust automatic lyric alignment (v2)

## Goal
Align every LRC line to the 4:43 recording automatically. Lyrics should appear
when the vocal starts, with no manual per-line fixes.

## Why v1 falls short
- whisper.cpp word timestamps without DTW are coarse (often 0.5-2 s off).
- Matching each line greedily on its own is fragile. Repeated words (the song
  title, the "away" refrains) pull lines to the wrong place, and the fallbacks
  then guess from the live version's line spacing.

## Scope
In: `align_lyrics.py` only (render code unchanged).
Out: changing the lyric text; manual timing tables.

## Steps
1. Vocal-focused input for whisper: mid channel (L+R), band-limited
   150 Hz-7 kHz to suppress bass/drums.
2. Run whisper-cli with `--dtw large.v3.turbo` for token-level timestamps.
   Cache the result per settings.
3. Global alignment: one Needleman-Wunsch DP between the whole LRC word
   sequence and the whisper word sequence. Fuzzy word similarity, gap penalties,
   and a time-window constraint around the rough offset, so a word can only match
   inside its section.
4. Line start = time of the first matched word, minus a small lead for the
   unmatched leading words. Lines with no matches are interpolated between
   neighbours by source time.
5. Report per-line coverage (matched words / words), write the re-timed LRC,
   re-render.

## Risks / open questions
- whisper may still miss words under loud guitar/sax. Coverage per line is
  reported so weak lines are visible.
- The spoken outro lines in the LRC are crammed into ~1 s, so they can only be
  placed where whisper actually hears them.

## Complexity
Medium

## Outcome
- whisper.cpp proved unstable on the full mix: each run (with/without DTW,
  whole song vs chunks) heard different parts, and a band-limited "vocal" input
  made it hallucinate. All runs are now pooled (`out/whisper/*.json`, cached).
- Added vocal isolation with demucs (`--two-stems vocals`, installed into
  `.venv`, ~40 s on MPS). The stem is used twice: two extra whisper runs, and
  vocal phrase segments (RMS gate, >= 150 ms gaps) as acoustic ground truth.
- Alignment: one global Needleman-Wunsch over all lyric words vs pooled heard
  words (content words weighted over short function words, DTW timestamps
  preferred, +/-15 s window). Per line, only the largest cluster of matches
  (<= 3 s apart) is kept, which removes stray hits on repeated words.
- Line start = onset of the vocal phrase holding its first trusted (> 3 letters)
  word. If the first word was not heard (the held first word before a pause), the
  unclaimed phrase right before it is used, bounded by half the source spacing
  (max 3 s) after the previous line. Lines without heard words snap to the
  nearest unclaimed onset (+/-1.5 s). A final pass keeps the order.
- Result: line-to-line spacing now matches the LRC's own spacing within about
  0.3-0.7 s in all verses. Verse 3 sits about 1-2 s later than in v1, which had
  it early. The crammed spoken lines at the end are spread out instead of
  dropped (30 lines shown).
- Deviation: the "vocal-focused" band-limited input (plan step 1) was dropped in
  favour of demucs separation.
