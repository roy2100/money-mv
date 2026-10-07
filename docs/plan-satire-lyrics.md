# Plan: lyrics layer + satirical art direction

## Goal
Make the MV more artistic and satirical, and support on-screen lyrics.

## Scope
In:
- `--lyrics <file.lrc>`: render user-supplied, time-stamped lyrics as
  "ransom-note" kinetic typography (each word cut out in a different font/paper,
  popping in word by word). The repo ships no lyric text; the user provides the
  LRC file.
- Satirical layer (all original writing/art):
  - rubber-stamp slogans with fine print, slammed onto the screen per section;
  - an original mascot ("Mr. Margin", a top-hatted coin) that rides the chart up
    in "rise" and floats away on a golden parachute in "crash";
  - "THEM vs YOU" counters (executive pay vs your balance) replacing the single
    money counter;
  - an unskippable "SKIP AD" button during the solo;
  - outro becomes an itemized receipt scrolling up;
  - satirical stock ticker items.
- Print look: film grain, colour misregistration on hits, paper-tone end card.

Out:
- Writing, transcribing or bundling the song's lyrics (copyright).
- Changing the soundtrack synthesis or the section analysis.

## Steps
1. LRC parser + word-level timing (words spread across the line's duration).
2. Ransom-note word sprites (cached per word) with pop-in animation, lower third.
3. Stamp slogans table keyed by section progress; stamp sprite + slam animation.
4. Mascot drawing + placement per section (chart head, parachute).
5. THEM/YOU counters, SKIP AD button, receipt outro, new ticker text.
6. Grain + misregistration post-processing.
7. Render synth version and original-audio version (with a test LRC of
   placeholder lines only, to verify layout), check frames.

## Risks / open questions
- Visual clutter: lyrics (lower third), stamps (upper third), counters (top-left)
  must not collide; stamps are short-lived.
- LRC timing quality depends on the user's file.

## Complexity
Medium

## Outcome
- `--lyrics <file.lrc>` (+ `--lyrics-offset`) renders user-supplied lyrics as
  ransom-note kinetic typography (8 fonts x 7 paper colours, per-word pop-in,
  drop-out on line end, cut-paper shadow). Verified layout with a placeholder
  LRC only; no lyric text is shipped or written by us.
- Satire layer implemented as planned: 12 rubber stamps with typed-out fine
  print, Mr. Margin mascot (bottom-right in groove, riding the chart head in
  rise, golden parachute in crash, next to the receipt in outro), THEM/YOU
  counters (+BONUS while YOU goes negative in crash), unskippable ad during the
  solo with a scripted cursor click, itemized receipt outro, satirical ticker,
  "MONEY™" title and "this video has been monetized." on the end card.
- Print look: film grain (light + dark) on every frame, RGB misregistration
  that widens on kicks and stamp hits, stamp-hit screen shake.
- Deviations: outro no longer shows the register icons (receipt instead); outro
  stamp sits at the bottom so it does not cover receipt items; default `--crf`
  raised to 23 because grain inflates file size. Render time ~45 s (synth) /
  ~150 s (4:43 recording).

### Follow-up: aligning the user's LRC
- The supplied LRC is timed for the 8:37 live version, not the 4:43 recording.
  Added piecewise `--lyrics-offset "src=offset,..."` and a 0.5 s minimum line
  length (the file crams its last lines into ~1 s).
- Offsets found from per-bar spectral novelty (vocal bars alternate every two
  7/4 bars and match the LRC's line spacing): verses 1-2 at -14.87 s, verse 3
  and outro at -247.52 s (verse 3 enters at 3:32.5, right after the 4/4 solo).
- Lyric rows narrowed to W-320 and the groove mascot moved bottom-left to avoid
  overlapping long lines.

### Follow-up: drop the 7/4 motif, whisper re-alignment
- Removed visible 7/4 elements: bottom beat meter (cells, "7/4"/"4/4" label,
  bar counter), "7/4" on the solo coin (now "$" / "IN DEBT WE TRUST", 12 stars),
  intro caption (now "A SHAREHOLDER PRESENTATION"), "tribute in 7/4" on the end
  card, "STORE #7/4" on the receipt. The 7-fold rosette stays as texture.
- Added `align_lyrics.py`: runs local whisper.cpp (`whisper-cli`,
  ggml-large-v3-turbo) for word timestamps, anchors only on distinctive lines
  (>= 3 distinct words, score >= 0.75) searched near the previous anchor, and
  places short/repetitive lines by their source spacing. `--only-after 3:00`
  kept verses 1-2 (already judged correct) untouched.
- Result for post-solo lines: verse 3 is ~2.8-3.0 s later than the rough
  offset, the last lines ~4.4-4.8 s later. Re-timed copy written to
  `out/money_aligned.lrc` (derived from the user's file) and used for the render.
