#!/usr/bin/env python3
"""Re-time a user-supplied .lrc file against a recording using local whisper.cpp.

whisper on a full band mix is unstable: separate runs hear different parts of
the vocal. So the recording is transcribed several ways (whole song with and
without DTW token timestamps, plus DTW runs over the given vocal chunks), the
word hypotheses are pooled, and the whole lyric word sequence is aligned to the
pooled sequence in one global dynamic-programming pass. Each word may only match
within a time window around its rough position. A line starts at its first
matched word. Lines with too few matches are interpolated between their
neighbours.

Usage:
  .venv/bin/python align_lyrics.py song.mp3 lyrics.lrc out.lrc \
      --offset "0:00=-14.87,7:00=-247.52" --chunks "0:20-2:00,3:25-4:43" \
      --vocals out/stems/htdemucs/<song>/vocals.wav   # demucs --two-stems vocals
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile

from render_mv import parse_shift, parse_time

MODEL = os.path.expanduser("~/whisper-models/ggml-large-v3-turbo.bin")
STAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
WORD_LEAD = 0.3      # seconds per unmatched leading word when back-dating a line start


def norm(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def run_whisper(wav, model, out_json, dtw, offset_ms=0, dur_ms=0):
    if os.path.exists(out_json):
        return
    cmd = ["whisper-cli", "-m", model, "-f", wav, "-l", "en", "-ml", "1", "-sow", "-ojf",
           "-of", os.path.splitext(out_json)[0], "-np"]
    if dtw:
        cmd += ["-nfa", "--dtw", "large.v3.turbo"]
    if dur_ms:
        cmd += ["-ot", str(offset_ms), "-d", str(dur_ms)]
    subprocess.run(cmd, check=True, capture_output=True)


def read_words(path, dtw):
    """[(token, time)] from a whisper-cli full JSON; DTW token times when available."""
    with open(path) as fh:
        segs = json.load(fh)["transcription"]
    words = []
    for s in segs:
        w = norm(s["text"])
        if not w:
            continue
        t = s["offsets"]["from"] / 1000
        if dtw:
            dt = [tok["t_dtw"] for tok in s["tokens"] if tok.get("t_dtw", -1) >= 0 and norm(tok["text"])]
            if dt:
                t = dt[0] / 100
        words.append((w, t, dtw))
    return words


def transcribe_pool(sources, model, cache_dir):
    """sources: [(name, audio path, chunks)]. Returns pooled [(token, time, is_dtw)]."""
    os.makedirs(cache_dir, exist_ok=True)
    pool = []
    with tempfile.TemporaryDirectory() as tmp:
        for src, audio, chunks in sources:
            wav = os.path.join(tmp, f"{src}.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", audio, "-ar", "16000", "-ac", "1", wav], check=True)
            runs = [(f"{src}_full", False, 0, 0), (f"{src}_full_dtw", True, 0, 0)]
            runs += [(f"{src}_chunk{i}_dtw", True, int(a * 1000), int((b - a) * 1000))
                     for i, (a, b) in enumerate(chunks)]
            for name, dtw, off, dur in runs:
                path = os.path.join(cache_dir, f"{name}.json")
                run_whisper(wav, model, path, dtw, off, dur)
                words = read_words(path, dtw)
                pool += words
                print(f"  whisper run {name:20s} {len(words):4d} words")
    return sorted(pool, key=lambda w: w[1])


def vocal_segments(path, min_gap=0.15, drop_db=18.0):
    """[(onset, offset)] of the isolated vocal, split by at least min_gap of silence."""
    import numpy as np
    sr, hop = 16000, 160
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, "<f4")
    n = len(x) // hop
    db = 20 * np.log10(np.sqrt(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-6)
    db = np.convolve(db, np.ones(5) / 5, "same")
    active = db > np.percentile(db, 90) - drop_db
    segs, start, quiet = [], None, 0
    for i, a in enumerate(active):
        if a:
            if start is None:
                start = i
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet >= min_gap * 100:
                segs.append((start / 100, (i - quiet + 1) / 100))
                start, quiet = None, 0
    if start is not None:
        segs.append((start / 100, n / 100))
    return segs


def read_lrc(path):
    """Returns (raw lines, [(line_no, source_time, text)])."""
    with open(path, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    entries = []
    for no, line in enumerate(raw):
        stamps = STAMP.findall(line)
        text = STAMP.sub("", line).strip()
        if len(stamps) == 1 and text:
            m, s = stamps[0]
            entries.append((no, int(m) * 60 + float(s), text))
    return raw, entries


def similar(a, b):
    """Match reward; short function words are weak evidence."""
    if a == b:
        return 2.0 if len(a) > 3 else 0.8
    if len(a) > 3 and len(b) > 3 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75:
        return 1.2
    return None


def global_align(lyr, pool, window, skip_lyric=-0.4, skip_heard=-0.05):
    """Needleman-Wunsch between lyric tokens [(token, rough_t)] and heard [(token, t)].

    Returns {lyric index: heard time} for matched tokens.
    """
    n, m = len(lyr), len(pool)
    neg = float("-inf")
    score = [[neg] * (m + 1) for _ in range(n + 1)]
    move = [[0] * (m + 1) for _ in range(n + 1)]
    score[0][0] = 0.0
    for j in range(1, m + 1):
        score[0][j] = j * skip_heard
        move[0][j] = 2
    for i in range(1, n + 1):
        score[i][0] = i * skip_lyric
        move[i][0] = 1
        tok, rough = lyr[i - 1]
        for j in range(1, m + 1):
            best, mv = score[i - 1][j] + skip_lyric, 1
            s = score[i][j - 1] + skip_heard
            if s > best:
                best, mv = s, 2
            ht, htime, dtw = pool[j - 1]
            if abs(htime - rough) <= window:
                sim = similar(tok, ht)
                if sim is not None and dtw:
                    sim += 0.1  # prefer DTW timestamps when both runs heard the word
                if sim is not None and score[i - 1][j - 1] + sim > best:
                    best, mv = score[i - 1][j - 1] + sim, 3
            score[i][j], move[i][j] = best, mv
    matched, i, j = {}, n, m
    while i > 0 or j > 0:
        mv = move[i][j]
        if mv == 3:
            matched[i - 1] = pool[j - 1][1]
            i, j = i - 1, j - 1
        elif mv == 1:
            i -= 1
        else:
            j -= 1
    return matched


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("lrc")
    ap.add_argument("out")
    ap.add_argument("--offset", default="0", help="rough pre-alignment, same syntax as render_mv --lyrics-offset")
    ap.add_argument("--chunks", default="", help='vocal regions for extra DTW runs, e.g. "0:20-2:00,3:25-4:43"')
    ap.add_argument("--window", type=float, default=15.0, help="a word may match +/- N s from its rough time")
    ap.add_argument("--min-coverage", type=float, default=0.34, help="matched-word share needed to trust a line")
    ap.add_argument("--vocals", help="isolated vocal stem (e.g. from demucs): extra whisper runs + onset snapping")
    ap.add_argument("--snap", type=float, default=1.5,
                    help="lines without heard words snap to a vocal onset within +/- N s")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--cache", default="out/whisper")
    args = ap.parse_args()

    chunks = []
    for c in filter(None, args.chunks.split(",")):
        a, b = c.split("-")
        chunks.append((parse_time(a), parse_time(b)))
    sources = [("mix", args.audio, chunks)]
    if args.vocals:
        sources.append(("vocals", args.vocals, []))
    pool = transcribe_pool(sources, args.model, args.cache)
    segments = vocal_segments(args.vocals) if args.vocals else []
    raw, entries = read_lrc(args.lrc)
    shift = parse_shift(args.offset)

    def rough(src):
        off = [o for s, o in shift if s <= src]
        return src + (off[-1] if off else 0.0)

    lyr, owner = [], []
    for k, (no, src, text) in enumerate(entries):
        for wi, w in enumerate(t for t in (norm(x) for x in text.split()) if t):
            lyr.append((w, rough(src) + wi * WORD_LEAD))
            owner.append((k, wi))
    matched = global_align(lyr, pool, args.window)

    # A sung line is one phrase: keep each line's largest cluster of matches
    # (consecutive matched words <= 3 s apart) and drop stray far-away hits.
    by_line = {}
    for i in sorted(matched):
        by_line.setdefault(owner[i][0], []).append(i)
    for k, ids in by_line.items():
        clusters, cur = [], [ids[0]]
        for i in ids[1:]:
            if matched[i] - matched[cur[-1]] <= 3.0:
                cur.append(i)
            else:
                clusters.append(cur)
                cur = [i]
        clusters.append(cur)
        keep = max(clusters, key=len)
        for i in ids:
            if i not in keep:
                del matched[i]

    # Line starts from their first matched word.
    starts = [None] * len(entries)
    cover = [0.0] * len(entries)
    for k, (no, src, text) in enumerate(entries):
        idx = [i for i, (lk, _) in enumerate(owner) if lk == k]
        hits = [i for i in idx if i in matched]
        cover[k] = len(hits) / max(1, len(idx))
        if hits and (cover[k] >= args.min_coverage or len(hits) >= 3):
            # Back-date from each matched word and take the median, so one stray
            # early match of a common word cannot drag the line start.
            est = sorted(matched[i] - owner[i][1] * WORD_LEAD for i in hits)
            first = hits[0]
            starts[k] = matched[first] if owner[first][1] == 0 else est[len(est) // 2]

    # Enforce increasing starts; drop anchors that break the order.
    last = float("-inf")
    for k in range(len(starts)):
        if starts[k] is not None:
            if starts[k] <= last:
                starts[k] = None
            else:
                last = starts[k]

    # Interpolate the rest by source time between neighbouring anchors.
    srcs = [e[1] for e in entries]
    final = list(starts)
    for k in range(len(final)):
        if final[k] is not None:
            continue
        prev = next((p for p in range(k - 1, -1, -1) if starts[p] is not None), None)
        nxt = next((q for q in range(k + 1, len(starts)) if starts[q] is not None), None)
        if prev is not None and nxt is not None and srcs[nxt] > srcs[prev]:
            r = (srcs[k] - srcs[prev]) / (srcs[nxt] - srcs[prev])
            cand = starts[prev] + r * (starts[nxt] - starts[prev])
            # Stay with the previous anchor's offset if the source gap spans a cut section.
            same = starts[prev] + (srcs[k] - srcs[prev])
            final[k] = same if abs(same - rough(srcs[k])) < abs(cand - rough(srcs[k])) and same < starts[nxt] else cand
        elif prev is not None:
            final[k] = starts[prev] + (srcs[k] - srcs[prev])
        elif nxt is not None:
            final[k] = starts[nxt] - (srcs[nxt] - srcs[k])
        else:
            final[k] = rough(srcs[k])

    # Refine with the isolated vocal: a line starts where its vocal phrase starts.
    snapped = [""] * len(final)
    if segments:
        def seg_of(t):
            return next((i for i, (on, off) in enumerate(segments) if on - 0.25 <= t <= off + 0.25), None)

        # Only words longer than 3 letters are trusted evidence for phrase ownership.
        strong = {}
        for i, t in matched.items():
            if len(lyr[i][0]) > 3:
                strong.setdefault(owner[i][0], []).append((owner[i][1], t))
        claimed = {}
        for k, hits in strong.items():
            for _, t in hits:
                si = seg_of(t)
                if si is not None:
                    claimed.setdefault(si, k)
        prev_end = float("-inf")
        for k in range(len(final)):
            hits = sorted(strong.get(k, []))
            # Keep at least part of the source spacing to the previous line, so a
            # line cannot steal the previous line's trailing phrase.
            gap = min(0.5 * (srcs[k] - srcs[k - 1]), 3.0) if k else 0.0
            floor_t = final[k - 1] + max(0.3, gap) if k else float("-inf")
            if hits:
                wi0, t0 = hits[0]
                si = seg_of(t0)
                start = segments[si][0] if si is not None else t0
                # Leading words not heard (e.g. a held first word before a pause):
                # take the unclaimed phrase right before, if it is close.
                if si is not None and wi0 > 0 and si > 0:
                    on = segments[si - 1][0]
                    if on >= start - 4.0 and on > max(prev_end, floor_t) and claimed.get(si - 1, k) == k:
                        start = on
                if start > floor_t:
                    final[k], snapped[k] = start, "phrase"
                prev_end = max(t for _, t in hits)
            else:
                near = [on for i, (on, _) in enumerate(segments)
                        if abs(on - final[k]) <= args.snap and on > floor_t and claimed.get(i) in (None, k)]
                if near:
                    final[k], snapped[k] = min(near, key=lambda o: abs(o - final[k])), "onset"
                    # Heard only short words, first word missing: same held-first-word rule.
                    first_tok = next(i for i, (lk, _) in enumerate(owner) if lk == k)
                    si = next(i for i, (on, _) in enumerate(segments) if on == final[k])
                    if starts[k] is not None and first_tok not in matched and si > 0:
                        on = segments[si - 1][0]
                        if on >= final[k] - 4.0 and on > max(prev_end, floor_t) and claimed.get(si - 1) is None:
                            final[k], snapped[k] = on, "phrase*"

    # Final ordering pass: anything that ended up out of order follows its
    # predecessor (only happens for the crammed spoken lines at the very end).
    for k in range(1, len(final)):
        if final[k] <= final[k - 1] + 0.3:
            final[k], snapped[k] = final[k - 1] + 1.2, "reordered"

    new = list(raw)
    print(" line   rough  aligned   shift  coverage")
    for k, (no, src, text) in enumerate(entries):
        t = max(0.0, final[k])
        m, s = divmod(t, 60)
        new[no] = f"[{int(m):02d}:{s:05.2f}]" + text
        tag = ("" if starts[k] is not None else "  (interpolated)") + (f"  {snapped[k]}" if snapped[k] else "")
        print(f"{no + 1:5d}  {rough(src):7.2f}  {t:7.2f}  {t - rough(src):+6.2f}  {cover[k]:5.0%}{tag}")
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(new) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    sys.exit(main())
