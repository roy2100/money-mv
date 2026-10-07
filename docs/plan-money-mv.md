# Plan: "Money" tribute MV (MP4)

## Goal
Render an MP4 music video inspired by Pink Floyd's "Money": a 7/4 groove,
cash-register / coin imagery, a 4/4 "solo" section, and audio-reactive visuals.

## Scope
In:
- `render_mv.py`: one Python script (numpy + Pillow, frames piped to ffmpeg).
- Original synthesized soundtrack (own bassline in 7/4, drums, cash-register
  and coin SFX) used when no audio file is given.
- `--audio <file>` option so the user can render visuals against their own
  legally obtained copy of the song (visuals driven by audio analysis).
- Output: `out/money_mv.mp4`, 1280x720, 30 fps, H.264 + AAC.

Out:
- The original recording, lyrics, the original bass riff, album artwork or
  band branding (copyright/trademark). Visuals and music are original.

## Steps
1. Create `.venv` with numpy + Pillow.
2. Write the audio synth (7/4 at ~120 BPM, intro SFX, groove, 4/4 solo, outro).
3. Write audio analysis (per-frame bass/mid/high energy + onsets) usable for
   both synth and user audio.
4. Write scene renderer: intro (register drawers + coins), groove (coin rain,
   7-step beat meter, ticker), solo (spinning coin, banknote tunnel), outro.
5. Pipe frames to ffmpeg, mux with audio.
6. Render a short preview, check timing/perf, then full render.

## Risks / open questions
- Pure-Python/numpy frame rendering speed (~2000+ frames); keep drawing cheap.
- For user audio, beat timing is estimated from energy, not a true beat grid.

## Complexity
Medium

## Outcome
- Implemented as planned in `render_mv.py` (numpy + Pillow in `.venv`, frames piped
  to ffmpeg). Full 90 s render takes ~30 s.
- Soundtrack: original E-minor 7/4 bassline (Em-Em-Am-Bm) at 120 BPM, drums,
  a synthesized seven-sound cash-register loop, an organ "rise" section, and an
  8-bar 4/4 section with a seeded pentatonic lead plus ping-pong echo.
- Structure: intro 0-7 s, groove 7-35 s, rise 35-49 s, solo (4/4) 49-65 s,
  crash 65-79 s, outro 79-86 s, end card 86-90 s.
- Visuals: guilloche waves and a 7-fold (4-fold in the solo) rosette driven by
  bass/mid energy, coin rain on kicks, stock ticker, money counter, beat meter,
  banknote stacks + rising chart, spinning "7/4" coin with banknote tunnel,
  red crash chart with screen shake, end card with attribution.
- `--audio/--bpm/--sections` path for a user-supplied recording: kick/coin events
  come from onset detection; default section split is by duration fractions.
  Not tested with a real file (none provided).
- Outputs: `out/money_mv.mp4` (1280x720, 30 fps, H.264 + AAC, ~110 MB) and
  `out/money_mv_soundtrack.wav`.

### Follow-up: render against a user-supplied recording
- Added `track_beats()` (Ellis-style DP beat tracker with a locally estimated
  tempo) so the beat grid follows tempo drift in a real recording (~118-136 BPM
  observed), and `Timeline` now uses tracked beats when `--audio` is given.
- `--sections` accepts a meter override (`outro/4`); added `--crf`.
- Section times for the supplied 4:43 file were derived from analysis (bass entry,
  beat-synchronous self-similarity at 7- vs 4/8-beat lags, tempo jump at 2:53):
  `0:00=intro,0:09.3=groove,1:42=rise,2:52.8=solo,3:31=crash,4:04=outro/4`.
- End card credits switch to "music: Pink Floyd" when external audio is used.
- Output: `out/money_mv_original_audio.mp4` (crf 24, ~168 MB). No lyrics on screen.
