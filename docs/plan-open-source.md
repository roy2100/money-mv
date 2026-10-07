# Plan: open-source release

## Goal
Publish the generator as a public GitHub repo `roy2100/money-mv` (MIT), with a
Chinese README, and rename the local folder to `money-mv`.

## Scope
In:
- Delete junk (`.DS_Store`, `__pycache__/`).
- `.gitignore` for the venv, caches, renders and every copyrighted input/output:
  audio files, `.lrc` lyrics, `out/` (renders with the original recording and
  lyrics, demucs stems, whisper transcripts).
- `requirements.txt`, `LICENSE` (MIT), `README.md` (Chinese, as requested),
  preview stills taken from the original-soundtrack render only.
- `git init`, initial commit, `gh repo create --public --push`, rename the folder.

Out:
- The user's mp3 and LRC stay on disk (ignored), as chosen.
- No code changes beyond what the release needs.

## Steps
1. Remove junk files; write `.gitignore`.
2. Add `requirements.txt` and `LICENSE`.
3. Extract preview stills from `out/money_mv.mp4` (synth soundtrack) into
   `docs/images/`.
4. Write `README.md` in Chinese.
5. `git init`, check that `git status` contains no audio, lyrics or `out/` files,
   then commit.
6. Create the public repo with `gh` and push.
7. Rename `~/Project/mv` to `~/Project/money-mv`.

## Risks / open questions
- A copyrighted file slipping into the commit: verify the staged file list
  before committing.
- Renaming the folder breaks absolute shebangs in `.venv/bin/*` scripts.
  `.venv/bin/python -m ...` keeps working; the README recreates the venv anyway.

## Complexity
Low

## Outcome
- Removed `.DS_Store` and `__pycache__/`. Added `.gitignore` (venv, caches,
  `out/`, all audio formats, `*.lrc`), `requirements.txt` (demucs listed as
  optional), MIT `LICENSE`, and a Chinese `README.md` with six stills from the
  original-soundtrack render (`docs/images/`).
- Checked the staged file list before committing: no audio, lyrics, renders,
  stems or whisper transcripts, and no lyric text in any tracked file.
- Published as public repo `roy2100/money-mv` and renamed the local folder to
  `~/Project/money-mv`. The user's own mp3/LRC stay in the folder, ignored by git.
