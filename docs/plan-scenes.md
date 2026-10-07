# Plan: replace abstract background with narrative scenes

## Goal
Swap the guilloche waves/rosette background for concrete, original scenes that
tell a story across the sections.

## Scope
In:
- groove: a factory. Smokestacks puff on kicks, a wall sign and a fast clock,
  worker figures load coins onto a conveyor belt on the beat, and the belt feeds
  a bank building ("BANK OF MARGIN"). Mr. Margin stands on the bank's roof.
- rise: a skyline of coin-stack towers that grows with section progress and
  breathes with the spectrum. A coin "sun" rises, there is a crane, and the
  antennas blink on beats. These replace the banknote spectrum bars. The chart
  stays on top.
- solo: a giant vault door swings open to show glowing gold piles. The spinning
  coin and flying banknotes come out of it.
- crash: the same skyline collapses tower by tower, with staggered timing,
  dust, and coins flying off.
- Remove the wave band and rosette (assets + drawing code).

Out:
- Intro (register icons) and outro (receipt) layouts are not changed. Neither
  are the HUD, lyrics or stamps.

## Steps
1. Remove waves/rosette assets and `draw_background` usage.
2. Factory scene with belt/worker/smoke state.
3. Skyline towers (shared layout for rise and crash) + collapse particles.
4. Vault door scene behind the solo coin.
5. Re-position mascot in groove (bank roof).
6. Render both versions, check frames for readability of lyrics/stamps/HUD.

## Risks / open questions
- Busy lower third: the belt/workers sit behind the lyrics. Keep scene colours
  muted so the paper-cut lyrics stay readable.

## Complexity
Medium

## Outcome
- Implemented as planned. Waves/rosette assets, `draw_stacks` and the unused
  `SECTION_INK` table were removed; `draw_background` now dispatches to
  `draw_factory` / `draw_skyline` / `draw_vault`.
- groove: three smokestacks (puff per kick), wall slogan "MARGIN & CO. · WE MAKE
  MONEY. YOU MAKE IT FOR US.", windows that flash on kicks, an "OVERTIME" clock
  spinning one turn per four beats, six shirt-and-tie workers lifting coins in
  alternating beats, a belt whose speed follows bass, coins dropping into the
  "BANK OF MARGIN" with Mr. Margin on its roof. Groove coin rain reduced to 2 per
  kick.
- rise/crash: 16 coin-stack towers (height = section progress x spectrum band),
  blinking antennas, a crane with a hanging coin, and a coin "sun" that rises in
  rise and sets in crash. In crash each tower falls at its own time, throwing
  coins and dust.
- solo: a vault door swings open over 2.5 s to show glowing gold piles behind
  the spinning coin, under a "MARGIN & CO. · PRIVATE RESERVES" sign.
- Side effect: no more full-screen line patterns, so files shrank (synth 33 MB,
  original-audio 106 MB at crf 23).

### Follow-up: verse-3 first line
- User report: lyrics at 3:35, singing at 3:37. Line 19 had been placed by
  spacing (its wide-window match was rejected). Added pass 3 to
  `align_lyrics.py`: spacing-placed lines get a narrow (+/-3 s) whisper search with
  a lower score bar, bounded by their neighbours. Line 19 moved to 3:36.68,
  where whisper hears the line's first word.
