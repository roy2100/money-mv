#!/usr/bin/env python3
"""Render an original music video inspired by Pink Floyd's "Money".

Everything here is original: a synthesized 7/4 groove with cash-register
sound effects, a 4/4 solo section, and audio-reactive cash/coin visuals.
No recording, lyrics, riff or artwork from the song is used.

Usage:
  .venv/bin/python render_mv.py                      # original soundtrack
  .venv/bin/python render_mv.py --preview 12         # first 12 seconds only
  .venv/bin/python render_mv.py --audio my_copy.mp3 \
      --sections "0:00=intro,0:20=groove,2:00=rise,2:50=solo,4:50=crash,6:00=outro/4"
"""
import argparse
import bisect
import math
import os
import re
import subprocess
import sys
import time
import wave

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

SR = 44100
W, H = 1280, 720
FPS = 30

FONT_TITLE = "/System/Library/Fonts/Supplemental/Copperplate.ttc"
FONT_MONO = "/System/Library/Fonts/Menlo.ttc"
FONT_DIR = "/System/Library/Fonts/Supplemental/"

GOLD = (232, 184, 72)
GOLD_DARK = (140, 96, 28)
GOLD_HI = (255, 232, 160)
MINT = (120, 230, 160)
PAPER = (196, 214, 176)
RED = (232, 64, 52)
CREAM = (240, 232, 210)

SECTION_METER = {"intro": 7, "groove": 7, "rise": 7, "solo": 4, "crash": 7, "outro": 7, "end": 7}
SECTION_BG = {
    "intro": (6, 10, 8), "groove": (8, 22, 15), "rise": (6, 24, 20), "solo": (30, 13, 6),
    "crash": (28, 6, 8), "outro": (4, 6, 5), "end": (0, 0, 0),
}
SFX_LOOP = ["ching", "coin", "ratchet", "coin", "tear", "jingle", "thunk"]
SFX_LABEL = ["CHING", "CLINK", "RATCHET", "CLINK", "TEAR", "JINGLE", "THUNK"]

# Satirical copy (all original). Stamps: section -> [(progress from, to, text, fine print, colour)].
STAMPS = {
    "intro": [(0.50, 1.00, "SPONSORED BY YOUR DEBT", "*this broadcast accrues interest", RED)],
    "groove": [(0.36, 0.48, "WORK · SPEND · REPEAT", "*repeat until further notice", RED),
               (0.55, 0.68, "HAPPINESS IN 12 EASY INSTALLMENTS*", "*APR 39.9%. happiness not guaranteed.", GOLD),
               (0.75, 0.88, "YOUR VALUE HAS BEEN RECALCULATED", "*downward, for your convenience", RED)],
    "rise": [(0.10, 0.45, "LINE GOES UP", "*no other metrics were consulted", MINT),
             (0.55, 0.92, "ETHICS: OFF BALANCE SHEET", "*see footnote 47, page 912", GOLD)],
    "solo": [(0.04, 0.30, "THIS SOLO HAS BEEN MONETIZED", "*artist receives 0.003¢ per stream", GOLD),
             (0.62, 0.88, "NOW WITH 30% MORE SHAREHOLDER VALUE", "*value not available to non-shareholders", MINT)],
    "crash": [(0.06, 0.36, "SOMEONE ELSE WILL PAY FOR THIS", "*that someone is you", (245, 240, 225)),
              (0.48, 0.80, "BAILOUT APPROVED", "*for them. not for you.", GOLD)],
    "outro": [(0.50, 0.92, "THANK YOU FOR YOUR PURCHASE", "*no refunds. no exchanges. no exit.", RED)],
}
TICKER = [("GREED", "▲ ∞"), ("EMPATHY", "▼ 99.9%"), ("RENT", "▲ 12.0%"), ("WAGES", "▼ 0.0%"),
          ("CEO PAY", "▲ 940%"), ("FREE TIME", "▼ 18.2%"), ("BOTTLED AIR", "▲ 4.2%"), ("SLEEP", "▼ 3.1%"),
          ("PROFIT", "▲ RECORD"), ("TRUST", "▼ 0.0"), ("OUTRAGE", "▲ 7.4%"), ("HAPPINESS", "▼ DELISTED"),
          ("LOBBYING", "▲ 31%"), ("SAVINGS", "▼ N/A"), ("SHAREHOLDERS", "▲ DELIGHTED"), ("YOU", "▼ 2.7%")]
RECEIPT = [
    ("****  THANK YOU  ****", None), ("STORE #0001    TERMINAL 04", None), ("-", None),
    ("TIME, 40 YEARS", "52,000/yr"), ("SLEEP (PARTIAL)", "8.99"), ("ATTENTION (RESOLD)", "0.00"),
    ("DREAMS (DEFERRED)", "PENDING"), ("CONVENIENCE FEE", "14.99"), ("FEE FOR THE FEE", "4.99"),
    ("LOYALTY PENALTY", "9.99"), ("WEEKENDS (ONE)", "199.00"), ("SOUL (TRADE-IN)", "0.00"), ("-", None),
    ("SUBTOTAL", "EVERYTHING"), ("TAX", "YES"), ("TIP (MANDATORY)", "25%"), ("TOTAL", "EVERYTHING"),
    ("-", None), ("BALANCE DUE", "STILL"), ("", None), ("NO REFUNDS. NO EXCHANGES.", None),
    ("NO EXIT.", None), ("", None), ("BARCODE", None),
]
RANSOM_FONTS = [(FONT_TITLE, 2), (FONT_DIR + "Futura.ttc", 4), (FONT_DIR + "Didot.ttc", 2),
                (FONT_DIR + "Rockwell.ttc", 2), (FONT_DIR + "AmericanTypewriter.ttc", 2),
                (FONT_DIR + "Baskerville.ttc", 3), (FONT_MONO, 1), (FONT_DIR + "Impact.ttf", 0)]
RANSOM_PAPERS = [((236, 228, 206), (24, 22, 20)), (GOLD, (28, 18, 4)), ((22, 22, 22), CREAM),
                 (RED, CREAM), ((246, 246, 238), RED), (MINT, (10, 34, 22)), ((70, 120, 200), CREAM)]


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------

class Timeline:
    """Maps a time to its section and position on the beat grid.

    sections: list of (start_s, name) or (start_s, name, meter).
    beats: optional tracked beat times; when given, beat positions follow them
    (so the grid survives tempo drift) instead of a fixed bpm grid.
    """

    def __init__(self, sections, bpm, duration, beats=None):
        self.starts = [s[0] for s in sections]
        self.names = [s[1] for s in sections]
        self.meters = [s[2] if len(s) > 2 else SECTION_METER[s[1]] for s in sections]
        self.beats = beats
        self.beat = float(np.median(np.diff(beats))) if beats is not None else 60.0 / bpm
        self.duration = duration
        if beats is not None:
            self.start_pos = [round(self._bpos(s)) for s in self.starts]

    def _bpos(self, t):
        """Fractional beat index of time t in the tracked beat list."""
        b = self.beats
        i = bisect.bisect_right(b, t) - 1
        if i < 0:
            return (t - b[0]) / self.beat
        if i >= len(b) - 1:
            return i + (t - b[-1]) / self.beat
        return i + (t - b[i]) / (b[i + 1] - b[i])

    def at(self, t):
        i = max(0, bisect.bisect_right(self.starts, t) - 1)
        start = self.starts[i]
        end = self.starts[i + 1] if i + 1 < len(self.starts) else self.duration
        meter = self.meters[i]
        if self.beats is None:
            pos = (t - start) / self.beat
        else:
            pos = max(0.0, self._bpos(t) - self.start_pos[i])
        return {
            "name": self.names[i], "prev": self.names[i - 1] if i > 0 else self.names[i],
            "start": start, "t_in": t - start, "progress": (t - start) / max(1e-6, end - start),
            "length": end - start,
            "meter": meter, "beat": int(pos) % meter, "beat_frac": pos % 1.0, "bar": int(pos // meter),
            "beats": pos,
        }


def parse_time(s):
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec)
    return float(s)


def parse_sections(spec):
    """Parse "0:00=intro,2:53=solo,4:04=outro/4" into (start, name, meter) tuples."""
    out = []
    for item in spec.split(","):
        ts, name = item.strip().split("=")
        name, _, meter = name.partition("/")
        if name not in SECTION_METER:
            sys.exit(f"unknown section '{name}', expected one of {list(SECTION_METER)}")
        out.append((parse_time(ts), name, int(meter) if meter else SECTION_METER[name]))
    return sorted(out)


# --------------------------------------------------------------------------
# Original soundtrack synthesis
# --------------------------------------------------------------------------

def _t(d):
    return np.arange(int(d * SR)) / SR


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def smooth(x, k):
    return np.convolve(x, np.ones(k) / k, mode="same")


def place(out, i, sig):
    n = min(len(sig), len(out) - i)
    if n > 0:
        out[i:i + n] += sig[:n]
    return out


class Mixer:
    def __init__(self, duration):
        self.buf = np.zeros((2, int(duration * SR)))
        self.events = []

    def add(self, t, sig, gain=1.0, pan=0.0, kind=None, val=None):
        i = int(t * SR)
        n = min(len(sig), self.buf.shape[1] - i)
        if n <= 0:
            return
        a = (pan + 1) * math.pi / 4
        self.buf[0, i:i + n] += sig[:n] * gain * math.cos(a)
        self.buf[1, i:i + n] += sig[:n] * gain * math.sin(a)
        if kind:
            self.events.append((t, kind, val))


class Sounds:
    def __init__(self, rng):
        self.rng = rng

    def noise(self, n):
        return self.rng.standard_normal(n)

    def kick(self):
        t = _t(0.45)
        f = 45 + 90 * np.exp(-t / 0.035)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.22)

    def snare(self):
        t = _t(0.3)
        n = np.diff(self.noise(len(t) + 1)) * 0.5
        return n * np.exp(-t / 0.09) * 0.6 + np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.06) * 0.5

    def hat(self, open_=False):
        t = _t(0.3 if open_ else 0.07)
        n = np.diff(self.noise(len(t) + 1))
        return n * np.exp(-t / (0.09 if open_ else 0.018)) * 0.3

    def cymbal(self):
        t = _t(2.2)
        n = np.diff(self.noise(len(t) + 1))
        return n * np.exp(-t / 0.7) * 0.22

    def click(self, d=0.008):
        t = _t(d)
        return self.noise(len(t)) * np.exp(-t / 0.0015)

    def bell(self, f0, decay=0.9):
        t = _t(decay * 3)
        partials = [(1, 1.0), (2.76, 0.6), (5.40, 0.35), (8.93, 0.2)]
        return sum(a * np.sin(2 * np.pi * f0 * r * t) * np.exp(-t / (decay / r ** 0.5))
                   for r, a in partials) * 0.4

    def ratchet(self, clicks=8, gap=0.024):
        out = np.zeros(int((clicks * gap + 0.05) * SR))
        for k in range(clicks):
            place(out, int(k * gap * SR), self.click() * (1 - k / (clicks + 2)) * 0.6)
        return out

    def ching(self):
        out = np.zeros(int(2.0 * SR))
        place(out, 0, self.ratchet(3, 0.035))
        place(out, int(0.11 * SR), self.bell(1568.0))
        place(out, int(0.11 * SR), 0.6 * self.bell(2093.0, 0.7))
        return out

    def coin(self):
        t = _t(0.5)
        f0 = self.rng.uniform(3600, 4700)
        tone = sum(a * np.sin(2 * np.pi * f0 * r * t) for r, a in [(1, 1.0), (1.47, 0.6), (2.09, 0.4)])
        out = tone * np.exp(-t / 0.13) * 0.22
        place(out, 0, self.click() * 0.3)
        return out

    def jingle(self):
        out = np.zeros(int(0.8 * SR))
        for _ in range(6):
            place(out, int(self.rng.uniform(0, 0.2) * SR), self.coin() * 0.7)
        return out

    def tear(self):
        t = _t(0.42)
        n = self.noise(len(t))
        band = smooth(n, 4) - smooth(n, 40)
        crackle = np.repeat(self.rng.uniform(0.15, 1.0, 60), len(t) // 60 + 1)[:len(t)]
        return band * crackle * np.sin(np.pi * t / t[-1]) ** 0.5 * 1.4

    def thunk(self):
        t = _t(0.3)
        low = smooth(self.noise(len(t)), 60) * 6
        return np.sin(2 * np.pi * 85 * t) * np.exp(-t / 0.07) * 0.8 + low * np.exp(-t / 0.05)

    def sfx(self, kind):
        return getattr(self, kind)()

    def bass(self, midi, dur):
        f = midi_hz(midi)
        t = _t(dur + 0.03)
        sig = sum(np.sin(2 * np.pi * k * f * t) / k * 0.72 ** (k - 1) for k in range(1, 9))
        env = np.minimum(1, t / 0.004) * np.clip((dur + 0.03 - t) / 0.03, 0, 1) * np.exp(-t / 0.7)
        return sig * env * 0.42

    def organ(self, midi, dur):
        f = midi_hz(midi)
        t = _t(dur)
        sig = np.sin(2 * np.pi * f * t) + 0.5 * np.sin(4 * np.pi * f * t) + 0.25 * np.sin(6 * np.pi * f * t)
        env = np.minimum(1, t / 0.12) * np.clip((dur - t) / 0.2, 0, 1)
        return sig * env * (1 + 0.15 * np.sin(2 * np.pi * 6 * t)) * 0.07

    def lead(self, midi, dur, bend):
        f0 = midi_hz(midi)
        t = _t(dur + 0.15)
        vib = 0.007 * np.sin(2 * np.pi * 5.5 * t) * np.clip((t - 0.15) / 0.2, 0, 1)
        f = f0 * (1 + vib)
        if bend:
            f = f * 2 ** (-2 / 12 * np.clip(1 - t / 0.09, 0, 1))
        ph = 2 * np.pi * np.cumsum(f) / SR
        sig = np.tanh(2.2 * sum(np.sin(k * ph) / k for k in (1, 2, 3, 4, 5)))
        env = np.minimum(1, t / 0.008) * np.clip((dur + 0.15 - t) / 0.12, 0, 1)
        return sig * env * 0.16


# Bass in 7/4: (eighth position, length in eighths, semitones above root).
BASS_7 = [(0, 2, 0), (2, 1, 12), (3, 1, 10), (4, 2, 7), (6, 1, 3), (7, 1, 5),
          (8, 2, 0), (11, 1, 3), (12, 1, 5), (13, 1, 7)]
PROG_7 = [0, 0, 5, 7]                       # Em Em Am Bm
KICK_7, SNARE_7 = [0, 3, 8, 9], [4, 11]
BASS_4 = [0, 0, 12, 0, 7, 0, 10, 7]
PROG_4 = [0, 0, 5, 5, 8, 8, 7, 7]           # Em Em Am Am C C B B
KICK_4, SNARE_4 = [0, 3, 5], [2, 6]
PENTA = [64, 67, 69, 71, 74, 76, 79, 81, 83, 86, 88]
ROOT = 40                                   # E2


def build_soundtrack(bpm, seed):
    """Synthesize the soundtrack; returns (stereo audio, events, sections, duration)."""
    rng = np.random.default_rng(seed)
    snd = Sounds(rng)
    beat = 60.0 / bpm
    eighth = beat / 2
    plan = [("intro", 2), ("groove", 8), ("rise", 4), ("solo", 8), ("crash", 4), ("outro", 2)]
    sections, t = [], 0.0
    for name, bars in plan:
        sections.append((t, name, bars))
        t += bars * SECTION_METER[name] * beat
    sections.append((t, "end", 0))
    duration = t + 4.0
    mix = Mixer(duration)
    lead = Mixer(duration)

    for start, name, bars in sections:
        meter = SECTION_METER[name]
        for b in range(bars):
            bar_t = start + b * meter * beat
            # Cash-register loop, one sound per beat.
            sfx_gain = {"intro": 1.0, "groove": 0.35, "rise": 0.22, "crash": 0.35, "outro": 1.0}.get(name, 0)
            if name == "outro":
                sfx_gain *= 1 - b / bars * 0.6
            if sfx_gain:
                for k, kind in enumerate(SFX_LOOP):
                    pan = -0.6 + 1.2 * k / 6
                    mix.add(bar_t + k * beat, snd.sfx(kind), sfx_gain, pan, kind)
            if name in ("intro", "outro", "end"):
                continue
            if meter == 7:
                root = ROOT + PROG_7[b % 4]
                for pos, length, semi in BASS_7:
                    mix.add(bar_t + pos * eighth, snd.bass(root + semi, length * eighth * 0.92), 1.0, 0, "bass")
                for e in range(14):
                    tt = bar_t + e * eighth
                    if e in KICK_7:
                        mix.add(tt, snd.kick(), 0.9, 0, "kick")
                    if e in SNARE_7:
                        mix.add(tt, snd.snare(), 0.7, 0.1, "snare")
                    mix.add(tt, snd.hat(open_=(e == 13)), 0.8 if e % 2 == 0 else 0.5, 0.35)
                if name == "rise":
                    chord = [root + 12, root + 15, root + 19, root + 22]
                    for m in chord:
                        mix.add(bar_t, snd.organ(m, meter * beat), 1.0, -0.3)
            else:
                root = ROOT + PROG_4[b % 8]
                if b == 0:
                    mix.add(bar_t, snd.cymbal(), 1.0, 0.4, "cymbal")
                for e in range(8):
                    tt = bar_t + e * eighth
                    mix.add(tt, snd.bass(root + BASS_4[e], eighth * 0.9), 1.0, 0, "bass")
                    if e in KICK_4:
                        mix.add(tt, snd.kick(), 0.9, 0, "kick")
                    if e in SNARE_4:
                        mix.add(tt, snd.snare(), 0.75, 0.1, "snare")
                    mix.add(tt, snd.hat(), 0.7 if e % 2 == 0 else 0.45, 0.35)

    # Improvised pentatonic lead over the 4/4 section.
    solo_start = next(s for s, n, _ in sections if n == "solo")
    solo_end = solo_start + 8 * 4 * beat
    tt, idx = solo_start + beat, 4
    while tt < solo_end - 2 * beat:
        phrase_end = tt + beat * rng.choice([4, 6, 8])
        while tt < min(phrase_end, solo_end - 2 * beat):
            dur = beat * rng.choice([0.5, 0.5, 0.25, 0.25, 0.75, 1.0, 1.5])
            idx = int(np.clip(idx + rng.choice([-2, -1, -1, 1, 1, 2, 0]), 0, len(PENTA) - 1))
            lead.add(tt, snd.lead(PENTA[idx], dur * 0.95, rng.random() < 0.25), 1.0, 0.0, "note", idx)
            tt += dur
        tt += beat * rng.choice([0.5, 1.0, 1.5])
    lead.add(solo_end - 2 * beat, snd.lead(PENTA[-1], 2 * beat, True), 1.0, 0.0, "note", len(PENTA) - 1)
    d = int(0.75 * beat * SR)
    out = mix.buf + lead.buf
    for k in range(1, 5):
        echo = lead.buf * 0.38 ** k
        if k % 2:
            echo = echo[::-1]  # ping-pong: swap channels
        out[:, d * k:] += echo[:, :-d * k]
    events = sorted(mix.events + lead.events)

    out = np.tanh(out * 1.1)
    out *= 0.89 / np.max(np.abs(out))
    return out, events, [(s, n) for s, n, _ in sections], duration


def write_wav(path, stereo):
    pcm = (np.clip(stereo.T, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def load_audio(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


# --------------------------------------------------------------------------
# Audio analysis (drives visuals for both synth and user audio)
# --------------------------------------------------------------------------

def analyze(mono, n_frames, bands=16):
    win = 2048
    hop = SR / FPS
    window = np.hanning(win)
    freqs = np.fft.rfftfreq(win, 1 / SR)
    edges = np.geomspace(40, 12000, bands + 1)
    band_idx = [(freqs >= lo) & (freqs < hi) for lo, hi in zip(edges[:-1], edges[1:])]
    sel = {"bass": (freqs >= 20) & (freqs < 150), "mid": (freqs >= 150) & (freqs < 2000),
           "high": (freqs >= 2000) & (freqs < 12000)}
    padded = np.concatenate([np.zeros(win), mono, np.zeros(win)])
    raw = {k: np.zeros(n_frames) for k in sel}
    spec = np.zeros((n_frames, bands))
    for f in range(n_frames):
        c = int(f * hop) + win
        p = np.abs(np.fft.rfft(padded[c - win // 2:c + win // 2] * window)) ** 2
        for k, m in sel.items():
            raw[k][f] = p[m].sum()
        spec[f] = [np.log1p(p[m].sum()) for m in band_idx]

    feats = {}
    for k, v in raw.items():
        v = np.log1p(v)
        v = np.clip((v - np.percentile(v, 5)) / max(1e-9, np.percentile(v, 99) - np.percentile(v, 5)), 0, 1)
        out, y = np.zeros_like(v), 0.0
        for i, x in enumerate(v):
            y = max(x, y * 0.86)
            out[i] = y
        feats[k] = out
        feats[k + "_flux"] = np.maximum(0, np.diff(v, prepend=v[0]))
    lo, hi = np.percentile(spec, 10, axis=0), np.percentile(spec, 99, axis=0)
    feats["spec"] = np.clip((spec - lo) / np.maximum(1e-9, hi - lo), 0, 1)
    return feats


def track_beats(mono, min_bpm=100, max_bpm=150, tightness=100.0):
    """Dynamic-programming beat tracker (Ellis 2007) with a locally estimated tempo."""
    rate, win = 100, 1024
    hop = SR // rate
    n = len(mono) // hop
    frames = np.lib.stride_tricks.sliding_window_view(np.concatenate([mono, np.zeros(win)]), win)[::hop][:n]
    spec = np.log1p(10 * np.abs(np.fft.rfft(frames * np.hanning(win), axis=1)))
    onset = np.maximum(0, np.diff(spec, axis=0, prepend=spec[:1])).sum(1)
    onset = np.maximum(0, onset - smooth(onset, 30))
    onset /= onset.std() + 1e-9

    def autocorr(seg, lag):
        seg = seg - seg.mean()
        return (seg[:-lag] * seg[lag:]).sum() / ((seg * seg).sum() + 1e-9)

    # Local beat period (in envelope frames) from a 12 s window, once per second.
    lags = np.arange(int(rate * 60 / max_bpm), int(rate * 60 / min_bpm) + 1)
    centers = np.arange(0, n, rate)
    periods = []
    for c in centers:
        seg = onset[max(0, c - 6 * rate):c + 6 * rate]
        v = [autocorr(seg, lag) for lag in lags] if len(seg) > lags[-1] * 2 else [0] * len(lags)
        i = int(np.argmax(v))
        if 0 < i < len(v) - 1 and (v[i - 1] - 2 * v[i] + v[i + 1]) != 0:
            periods.append(lags[i] + 0.5 * (v[i - 1] - v[i + 1]) / (v[i - 1] - 2 * v[i] + v[i + 1]))
        else:
            periods.append(lags[i])
    periods = np.convolve(np.pad(periods, 3, mode="edge"), np.ones(7) / 7, mode="valid")
    period = np.interp(np.arange(n), centers, periods)

    score, back = onset.copy(), -np.ones(n, dtype=int)
    for t in range(n):
        lo, hi = max(0, int(t - 2 * period[t])), int(t - period[t] / 2)
        if hi <= lo:
            continue
        prev = np.arange(lo, hi)
        cand = score[prev] - tightness * np.log((t - prev) / period[t]) ** 2
        j = int(np.argmax(cand))
        score[t] = onset[t] + cand[j]
        back[t] = prev[j]
    tail = int(period[-1])
    t = int(np.argmax(score[-tail:])) + n - tail
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    return np.array(beats[::-1]) / rate


def detect_events(feats):
    """Approximate kick/coin events from onset flux (used for user audio)."""
    events = []
    for key, kind, gap in (("bass_flux", "kick", 6), ("high_flux", "coin", 5)):
        x = feats[key]
        thr = x.mean() + 1.5 * x.std()
        last = -gap
        for i in range(1, len(x) - 1):
            if x[i] > thr and x[i] >= x[i - 1] and x[i] >= x[i + 1] and i - last >= gap:
                events.append((i / FPS, kind, None))
                last = i
    return sorted(events)


# --------------------------------------------------------------------------
# Visuals
# --------------------------------------------------------------------------

def lerp(a, b, k):
    return a + (b - a) * k


def lerp_col(a, b, k):
    return tuple(int(lerp(x, y, k)) for x, y in zip(a, b))


def scale_col(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


class Assets:
    def __init__(self):
        self.title = ImageFont.truetype(FONT_TITLE, 150, index=2)
        self.title_s = ImageFont.truetype(FONT_TITLE, 34, index=1)
        self.title_m = ImageFont.truetype(FONT_TITLE, 96, index=2)
        self.mono = ImageFont.truetype(FONT_MONO, 20)
        self.mono_s = ImageFont.truetype(FONT_MONO, 14)
        self.mono_l = ImageFont.truetype(FONT_MONO, 64)
        self.mono_m = ImageFont.truetype(FONT_MONO, 30)
        self.vignette = self._vignette()
        self.ticker = self._ticker()
        self.coin_face = self._coin_face()
        self.receipt = self._receipt()
        self.grain = self._grain()
        self.futura = ImageFont.truetype(FONT_DIR + "Futura.ttc", 22, index=0)
        self.futura_s = ImageFont.truetype(FONT_DIR + "Futura.ttc", 15, index=2)

    def _vignette(self):
        y, x = np.mgrid[0:H, 0:W]
        r = np.hypot((x - W / 2) / (W / 2), (y - H / 2) / (H / 2))
        a = np.clip((r - 0.55) / 0.75, 0, 1) ** 1.6 * 235
        return Image.fromarray(a.astype(np.uint8), "L")

    def _ticker(self):
        items = []
        for label, val in TICKER:
            items.append((f"{label} ", CREAM))
            items.append((f"{val}     ", MINT if val.startswith("▲") else RED))
        width = int(sum(self.mono.getlength(s) for s, _ in items))
        im = Image.new("RGB", (width * 2, 34), (4, 8, 6))
        d = ImageDraw.Draw(im)
        for rep in range(2):
            x = rep * width
            for s, c in items:
                d.text((x, 6), s, font=self.mono, fill=c)
                x += self.mono.getlength(s)
        im.info["loop"] = width
        return im

    def _receipt(self):
        f = ImageFont.truetype(FONT_MONO, 16)
        rw, lh, pad = 370, 22, 22
        rh = pad * 2 + lh * len(RECEIPT) + 40
        im = Image.new("RGBA", (rw, rh))
        d = ImageDraw.Draw(im)
        teeth = [(x, 0 if (x // 10) % 2 else 8) for x in range(0, rw + 1, 10)]
        d.polygon(teeth + [(rw, rh - 8), (0, rh - 8)], fill=(240, 236, 224, 255))
        rng = np.random.default_rng(3)
        y = pad
        for left, right in RECEIPT:
            if left == "-":
                d.text((pad, y), "-" * 31, font=f, fill=(60, 60, 60))
            elif left == "BARCODE":
                x = pad + 20
                while x < rw - pad - 20:
                    bw = int(rng.integers(1, 5))
                    d.rectangle([x, y, x + bw, y + 46], fill=(25, 25, 25))
                    x += bw + int(rng.integers(2, 5))
            elif right is None:
                d.text((rw / 2, y + lh / 2), left, font=f, fill=(30, 30, 30), anchor="mm")
            else:
                d.text((pad, y), left, font=f, fill=(30, 30, 30))
                d.text((rw - pad, y), right, font=f, fill=(30, 30, 30), anchor="ra")
            y += lh
        return im

    def _grain(self):
        rng = np.random.default_rng(11)
        return [(Image.fromarray(rng.integers(0, 22, (H, W), dtype=np.uint8), "L"),
                 Image.fromarray(rng.integers(0, 34, (H, W), dtype=np.uint8), "L")) for _ in range(4)]

    def _coin_face(self):
        s = 320
        im = Image.new("RGBA", (s, s))
        d = ImageDraw.Draw(im)
        d.ellipse([0, 0, s - 1, s - 1], fill=GOLD_DARK)
        d.ellipse([10, 10, s - 11, s - 11], fill=GOLD)
        d.ellipse([34, 34, s - 35, s - 35], outline=GOLD_DARK, width=3)
        for k in range(12):
            a = -math.pi / 2 + k * 2 * math.pi / 12
            cx, cy = s / 2 + 128 * math.cos(a), s / 2 + 128 * math.sin(a)
            d.regular_polygon((cx, cy, 7), 5, rotation=math.degrees(a), fill=GOLD_DARK)
        d.text((s / 2, s / 2 - 10), "$", font=ImageFont.truetype(FONT_TITLE, 150, index=2), fill=GOLD_DARK,
               anchor="mm")
        d.text((s / 2, s / 2 + 72), "IN DEBT WE TRUST", font=ImageFont.truetype(FONT_TITLE, 17, index=2),
               fill=GOLD_DARK, anchor="mm")
        d.arc([22, 22, s - 23, s - 23], 200, 250, fill=GOLD_HI, width=5)
        return im


def parse_shift(spec):
    """"-14.9" or "0:00=-14.9,7:00=-247.5" -> [(from_source_time, offset)], sorted."""
    if "=" not in spec:
        return [(0.0, float(spec))]
    out = []
    for item in spec.split(","):
        src, off = item.strip().split("=")
        out.append((parse_time(src), float(off)))
    return sorted(out)


def load_lrc(path, shift=((0.0, 0.0),), min_len=0.5):
    """Parse a user-supplied .lrc file into [(start, end, text)].

    shift: piecewise offsets so lyrics timed for a different edit/version of the
    song can be re-aligned block by block. Lines shown for under min_len seconds
    are dropped (some LRC files cram trailing lines into a fraction of a second).
    """
    starts = [s for s, _ in shift]
    stamp = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
    entries = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            text = stamp.sub("", raw).strip()
            for m, sec in stamp.findall(raw):
                src = int(m) * 60 + float(sec)
                entries.append((src + shift[max(0, bisect.bisect_right(starts, src) - 1)][1], text))
    entries.sort()
    lines = []
    for i, (t, text) in enumerate(entries):
        end = entries[i + 1][0] if i + 1 < len(entries) else t + 5.0
        if text and end - t >= min_len:
            lines.append((t, min(end, t + 7.0), text))
    return lines


class Lyrics:
    """Ransom-note kinetic typography: every word cut from a different 'magazine'."""
    POP, EXIT = 0.14, 0.35

    def __init__(self, lines, seed):
        self.lines = lines
        self.starts = [ln[0] for ln in lines]
        self.seed = seed
        self.cache = {}
        self.fonts = {}

    def font(self, k, size):
        if (k, size) not in self.fonts:
            path, idx = RANSOM_FONTS[k]
            self.fonts[(k, size)] = ImageFont.truetype(path, size, index=idx)
        return self.fonts[(k, size)]

    def word_sprite(self, rng, word):
        f = self.font(int(rng.integers(len(RANSOM_FONTS))), int(rng.integers(40, 60)))
        bg, fg = RANSOM_PAPERS[int(rng.integers(len(RANSOM_PAPERS)))]
        l, t, r, b = f.getbbox(word)
        pw, ph = int(rng.integers(8, 16)), int(rng.integers(5, 11))
        w, h = r - l + 2 * pw, b - t + 2 * ph
        im = Image.new("RGBA", (w + 8, h + 8))
        d = ImageDraw.Draw(im)
        def j():
            return rng.uniform(-3, 3)
        d.polygon([(4 + j(), 4 + j()), (w + 4 + j(), 4 + j()), (w + 4 + j(), h + 4 + j()), (4 + j(), h + 4 + j())],
                  fill=bg + (255,))
        d.text((4 + pw - l, 4 + ph - t), word, font=f, fill=fg)
        return im.rotate(rng.uniform(-7, 7), resample=Image.BICUBIC, expand=True)

    def layout(self, i):
        if i in self.cache:
            return self.cache[i]
        t0, t1, text = self.lines[i]
        rng = np.random.default_rng(self.seed * 1000 + i)
        sprites = [self.word_sprite(rng, wd) for wd in text.split()]
        rows, row, rw = [], [], 0
        for sp in sprites:
            if row and rw + sp.width > W - 320:
                rows.append(row)
                row, rw = [], 0
            row.append(sp)
            rw += sp.width - 4
        if row:
            rows.append(row)
        heights = [max(sp.height for sp in r) for r in rows]
        y = H * 0.74 - (sum(heights) - 8 * (len(rows) - 1)) / 2
        placed = []
        for r, rh in zip(rows, heights):
            x = W / 2 - sum(sp.width - 4 for sp in r) / 2
            for sp in r:
                placed.append((sp, int(x), int(y + (rh - sp.height) / 2 + rng.uniform(-5, 5))))
                x += sp.width - 4
            y += rh - 8
        n = len(placed)
        span = min(0.7 * (t1 - t0), 0.38 * n)
        times = [t0 + span * k / max(1, n) for k in range(n)]
        self.cache = {k: v for k, v in self.cache.items() if k >= i - 1}
        self.cache[i] = (placed, times)
        return self.cache[i]

    def draw(self, img, t):
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0 or t >= self.lines[i][1]:
            return
        placed, times = self.layout(i)
        exit_k = max(0.0, (t - (self.lines[i][1] - self.EXIT)) / self.EXIT)
        for (sp, x, y), tw in zip(placed, times):
            if t < tw:
                continue
            k = min(1.0, (t - tw) / self.POP)
            sc = 1 + 0.5 * (1 - k) ** 2
            spr = sp if sc < 1.01 else sp.resize((int(sp.width * sc), int(sp.height * sc)), Image.BILINEAR)
            px = x - (spr.width - sp.width) // 2
            py = y - (spr.height - sp.height) // 2 + int(60 * exit_k ** 2)
            alpha = spr.getchannel("A")
            if exit_k > 0:
                alpha = alpha.point(lambda v: int(v * (1 - exit_k)))
            img.paste((0, 0, 0), (px + 5, py + 6), alpha.point(lambda v: v // 2))
            img.paste(spr, (px, py), alpha)


def make_stamp(text, col, seed):
    """Rubber-stamp sprite with worn ink."""
    rng = np.random.default_rng(seed)
    size = 56
    while True:
        f = ImageFont.truetype(FONT_DIR + "Futura.ttc", size, index=4)
        l, t, r, b = f.getbbox(text)
        if r - l + 56 < W - 160 or size <= 30:
            break
        size -= 4
    w, h = r - l + 56, b - t + 38
    im = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(im)
    d.rectangle([3, 3, w - 4, h - 4], outline=col + (255,), width=5)
    d.rectangle([11, 11, w - 12, h - 12], outline=col + (255,), width=2)
    d.text((28 - l, 19 - t), text, font=f, fill=col + (255,))
    a = np.asarray(im.getchannel("A"), dtype=np.float32)
    blotch = np.asarray(Image.fromarray((rng.random((8, 30)) * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR),
                        dtype=np.float32) / 255
    a *= np.clip(0.45 + 0.8 * blotch, 0, 1) * (rng.random(a.shape) > 0.1)
    im.putalpha(Image.fromarray(a.astype(np.uint8)))
    return im.rotate(rng.uniform(-8, 8), resample=Image.BICUBIC, expand=True)


class Video:
    def __init__(self, timeline, feats, events, assets, duration, seed, lyrics=None):
        self.tl = timeline
        self.f = feats
        self.a = assets
        self.duration = duration
        self.rng = np.random.default_rng(seed + 1)
        self.events = events
        self.ev_times = {}
        for t, kind, _ in events:
            self.ev_times.setdefault(kind, []).append(t)
        self.ev_cursor = 0
        self.synth = bool(self.ev_times.get("ching"))
        self.coins, self.notes, self.sparks = [], [], []
        self.them, self.you = 1_000_000.0, 12.40
        self.lyrics = lyrics
        self.seed = seed
        self.stamps = {}
        self.shake = 0.0
        self.eye_fonts = {}
        self.chart = [100.0]
        self.chart_origin = next((s for s, n in zip(timeline.starts, timeline.names) if n == "rise"), 0.0)
        self.scroll = 0.0
        self.frame_kicks = 0
        self.belt_pos = 0.0
        self.belt_coins, self.chute, self.smoke, self.dust = [], [], [], []
        self.worker_next = 0
        rng = np.random.default_rng(seed + 5)
        self.towers, x = [], 30.0
        while x < W - 60:
            w = float(rng.uniform(48, 84))
            self.towers.append({"x": x, "w": w, "base": float(rng.uniform(150, 360)),
                                "band": len(self.towers) % 16, "fall": float(rng.uniform(0.04, 0.78))})
            x += w + float(rng.uniform(6, 22))

    # --- helpers -----------------------------------------------------------
    def env(self, kind, t, tau):
        ts = self.ev_times.get(kind)
        if not ts:
            return 0.0
        i = bisect.bisect_right(ts, t) - 1
        return math.exp(-(t - ts[i]) / tau) if i >= 0 else 0.0

    def new_events(self, t):
        out = []
        while self.ev_cursor < len(self.events) and self.events[self.ev_cursor][0] <= t:
            out.append(self.events[self.ev_cursor])
            self.ev_cursor += 1
        return out

    def spawn_coin(self, x, y, vx=0.0, vy=0.0, r=None):
        self.coins.append({"x": x, "y": y, "vx": vx, "vy": vy, "r": r or self.rng.uniform(10, 24),
                           "ph": self.rng.uniform(0, 6.28), "spin": self.rng.uniform(4, 12)})

    def chart_value(self, k):
        while len(self.chart) <= k + 1:
            bt = self.chart_origin + len(self.chart) * self.tl.beat
            name = self.tl.at(bt)["name"]
            drift = {"rise": 2.2, "solo": 0.8, "crash": -4.2}.get(name, 0.3)
            self.chart.append(max(5.0, self.chart[-1] + drift + self.rng.normal(0, 2.4)))
        i = int(k)
        return lerp(self.chart[i], self.chart[i + 1], k - i)

    # --- drawing pieces ----------------------------------------------------
    def draw_background(self, d, info, t, dt, fi, kick):
        self.scroll += 1.5 + 6 * self.f["mid"][fi]
        name = info["name"]
        if name == "groove":
            self.draw_factory(d, info, t, dt, fi, kick)
        elif name in ("rise", "crash"):
            self.draw_skyline(d, info, t, dt, fi)
        elif name == "solo":
            self.draw_vault(d, info, t)

    # --- scenes ------------------------------------------------------------
    def draw_worker(self, d, x, belt_y, lift):
        """A worker in a shirt and tie behind the belt, lifting a coin on the beat."""
        body, skin = (84, 100, 112), (150, 138, 124)
        bend = 14 * (1 - lift)
        sh_x, sh_y = x + 6 * (1 - lift), belt_y - 64 + bend
        d.line([(x, belt_y + 12), (sh_x, sh_y)], fill=body, width=9)
        d.line([(sh_x, sh_y + 2), (sh_x + 1, sh_y + 20)], fill=(150, 46, 40), width=3)
        hx = lerp(x + 24, x + 10, lift)
        hy = lerp(belt_y - 6, sh_y - 38, lift)
        d.line([(sh_x, sh_y + 4), (hx, hy)], fill=body, width=6)
        d.ellipse([sh_x - 11 + 4 * (1 - lift), sh_y - 30, sh_x + 11 + 4 * (1 - lift), sh_y - 8], fill=skin)
        if lift > 0.4:
            d.ellipse([hx - 9, hy - 9, hx + 9, hy + 9], fill=GOLD, outline=GOLD_DARK)

    def draw_factory(self, d, info, t, dt, fi, kick):
        bass = self.f["bass"][fi]
        floor_y, belt_y, x1 = H * 0.92, H * 0.80, W - 270
        # Smokestacks; each kick puffs smoke from one of them.
        stacks = (W * 0.10, W * 0.25, W * 0.40)
        for sx in stacks:
            d.rectangle([sx - 22, H * 0.12, sx + 22, H * 0.34], fill=(26, 40, 33))
            d.rectangle([sx - 27, H * 0.12, sx + 27, H * 0.12 + 8], fill=(40, 60, 50))
        for _ in range(self.frame_kicks):
            sx = stacks[int(self.rng.integers(len(stacks)))]
            self.smoke.append({"x": sx, "y": H * 0.11, "r": 14.0, "life": 3.0})
        for p in self.smoke:
            p["y"] -= 26 * dt
            p["x"] += 10 * dt
            p["r"] += 12 * dt
            p["life"] -= dt
        self.smoke = [p for p in self.smoke if p["life"] > 0]
        for p in self.smoke:
            d.ellipse([p["x"] - p["r"], p["y"] - p["r"], p["x"] + p["r"], p["y"] + p["r"]],
                      fill=(110, 120, 112, int(60 * p["life"] / 3)))
        # Factory wall, sign, windows, clock.
        d.rectangle([0, H * 0.32, x1 + 10, floor_y], fill=(18, 32, 25))
        d.text(((x1 + 10) / 2, H * 0.355), "MARGIN & CO.  ·  WE MAKE MONEY. YOU MAKE IT FOR US.",
               font=self.a.futura_s, fill=(120, 150, 130), anchor="mm")
        for i in range(6):
            wx = 50 + i * (x1 - 260) / 5
            glow = 50 + int(70 * kick)
            d.rectangle([wx, H * 0.40, wx + 70, H * 0.57], fill=(60, 80, 40, glow), outline=(30, 46, 36), width=3)
            d.line([(wx + 35, H * 0.40), (wx + 35, H * 0.57)], fill=(30, 46, 36), width=3)
            d.line([(wx, H * 0.485), (wx + 70, H * 0.485)], fill=(30, 46, 36), width=3)
        cx, cy, cr = x1 - 80, H * 0.47, 40
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(206, 204, 190), outline=(60, 60, 56), width=4)
        m_ang = info["beats"] * math.pi / 2 - math.pi / 2
        h_ang = m_ang / 12 - math.pi / 2
        d.line([(cx, cy), (cx + cr * 0.8 * math.cos(m_ang), cy + cr * 0.8 * math.sin(m_ang))], fill=(30, 30, 30), width=3)
        d.line([(cx, cy), (cx + cr * 0.5 * math.cos(h_ang), cy + cr * 0.5 * math.sin(h_ang))], fill=(30, 30, 30), width=4)
        d.text((cx, cy + cr + 14), "OVERTIME", font=self.a.futura_s, fill=(120, 150, 130), anchor="mm")
        # Workers load a coin onto the belt on each kick.
        xs = [90 + i * (x1 - 220) / 5 for i in range(6)]
        for i, wx in enumerate(xs):
            phase = (info["beats"] + (i % 2) * 0.5) % 1.0
            self.draw_worker(d, wx, belt_y, math.sin(phase * math.pi))
        for _ in range(self.frame_kicks):
            self.belt_coins.append({"x": xs[self.worker_next % len(xs)] + 24})
            self.worker_next += 1
        # Conveyor belt.
        speed = 120 + 240 * bass
        self.belt_pos += speed * dt
        for lx in range(60, int(x1), 220):
            d.line([(lx, belt_y + 20), (lx, floor_y)], fill=(40, 44, 48), width=6)
        d.rectangle([0, belt_y, x1, belt_y + 20], fill=(46, 50, 54), outline=(20, 22, 24))
        for mx in range(-40, int(x1) + 40, 40):
            bx = mx + self.belt_pos % 40
            if 0 < bx < x1:
                d.line([(bx, belt_y + 4), (bx - 8, belt_y + 16)], fill=(74, 78, 82), width=2)
        for rx in range(20, int(x1), 70):
            d.ellipse([rx - 10, belt_y + 20, rx + 10, belt_y + 40], fill=(60, 64, 68))
            ang = self.belt_pos / 10
            d.line([(rx, belt_y + 30), (rx + 9 * math.cos(ang), belt_y + 30 + 9 * math.sin(ang))],
                   fill=(30, 32, 34), width=2)
        d.rectangle([0, floor_y, W, H], fill=(10, 16, 13))
        for c in self.belt_coins:
            c["x"] += speed * dt
        self.chute += [{"x": c["x"], "y": belt_y - 8, "vy": 0.0} for c in self.belt_coins if c["x"] > x1]
        self.belt_coins = [c for c in self.belt_coins if c["x"] <= x1]
        for c in self.belt_coins:
            d.ellipse([c["x"] - 11, belt_y - 9, c["x"] + 11, belt_y - 1], fill=GOLD, outline=GOLD_DARK)
        for c in self.chute:
            c["vy"] += 700 * dt
            c["y"] += c["vy"] * dt
            c["x"] += 40 * dt
        self.chute = [c for c in self.chute if c["y"] < belt_y + 50]
        for c in self.chute:
            d.ellipse([c["x"] - 8, c["y"] - 8, c["x"] + 8, c["y"] + 8], fill=GOLD, outline=GOLD_DARK)
        # The bank the belt feeds, with Mr. Margin on the roof.
        bx0, bx1, top = W - 250, W - 24, H * 0.50
        d.rectangle([bx0, top, bx1, floor_y], fill=(40, 52, 46))
        d.polygon([(bx0 - 14, top), (bx1 + 14, top), ((bx0 + bx1) / 2, top - 62)], fill=(54, 68, 60))
        d.rectangle([bx0 - 14, top, bx1 + 14, top + 12], fill=(64, 80, 70))
        d.text(((bx0 + bx1) / 2, top - 18), "BANK OF MARGIN", font=self.a.futura_s, fill=GOLD, anchor="mm")
        for k in range(4):
            colx = bx0 + 22 + k * (bx1 - bx0 - 60) / 3
            d.rectangle([colx, top + 12, colx + 16, floor_y - 10], fill=(70, 86, 76))
        d.rectangle([bx0 - 20, floor_y - 10, bx1 + 20, floor_y], fill=(64, 80, 70))
        d.rectangle([bx0 - 4, belt_y - 16, bx0 + 8, belt_y + 22], fill=(12, 14, 12))
        k = min(1.0, info["t_in"] / 1.5)
        bob = -abs(math.sin(info["beats"] * math.pi)) * 8
        self.draw_mascot(d, (bx0 + bx1) / 2, top - 62 - 66 + (1 - k) * 300 + bob, 44, t, kick)

    def tower_state(self, info, fi):
        spec = self.f["spec"][fi]
        out = []
        for tw in self.towers:
            if info["name"] == "rise":
                h, k = tw["base"] * (0.3 + 0.7 * info["progress"]) * (0.92 + 0.16 * spec[tw["band"]]), 0.0
            else:
                k = min(1.0, max(0.0, (info["progress"] - tw["fall"]) / 0.12))
                h = tw["base"] * (1 - k) ** 1.6
            out.append((h, k))
        return out

    def draw_skyline(self, d, info, t, dt, fi):
        ground = H * 0.92
        crash = info["name"] == "crash"
        p = info["progress"]
        sun_y = lerp(H * 0.30, H * 0.80, p) if crash else lerp(H * 0.66, H * 0.30, p)
        sx, sr = W * 0.16, 62
        d.ellipse([sx - sr, sun_y - sr, sx + sr, sun_y + sr], fill=GOLD + (60,), outline=GOLD + (110,), width=3)
        d.ellipse([sx - sr * 0.7, sun_y - sr * 0.7, sx + sr * 0.7, sun_y + sr * 0.7], outline=GOLD + (90,), width=2)
        if not crash:
            mx, jy = W * 0.60, H * 0.24
            d.line([(mx, ground), (mx, jy - 30)], fill=(60, 90, 80), width=6)
            d.line([(mx - 90, jy), (mx + 280, jy)], fill=(60, 90, 80), width=5)
            d.line([(mx, jy - 30), (mx + 280, jy)], fill=(60, 90, 80), width=2)
            d.rectangle([mx - 100, jy - 6, mx - 70, jy + 18], fill=(60, 90, 80))
            hook_x, hook_y = mx + 220, H * 0.42 + 18 * math.sin(t * 1.4)
            d.line([(hook_x, jy), (hook_x, hook_y)], fill=(90, 110, 100), width=1)
            d.ellipse([hook_x - 16, hook_y, hook_x + 16, hook_y + 10], fill=GOLD, outline=GOLD_DARK)
        face = (130, 82, 40) if crash else (176, 132, 48)
        edge = (90, 50, 24) if crash else (120, 86, 28)
        blink = info["beat"] % 2 == 0
        for tw, (h, k) in zip(self.towers, self.tower_state(info, fi)):
            x0, x1 = tw["x"], tw["x"] + tw["w"]
            top = ground - h
            if crash and 0 < k < 1:
                if self.rng.random() < 0.7:
                    self.spawn_coin(self.rng.uniform(x0, x1), top, self.rng.normal(0, 140),
                                    self.rng.uniform(-320, -80), r=self.rng.uniform(6, 12))
                if self.rng.random() < 0.5:
                    self.dust.append({"x": self.rng.uniform(x0 - 10, x1 + 10), "y": ground - 6,
                                      "r": 12.0, "life": 1.4})
            if h < 3:
                continue
            d.rectangle([x0, top, x1, ground], fill=face + (150,))
            y = ground - 9
            while y > top:
                d.line([(x0, y), (x1, y)], fill=edge + (170,), width=1)
                y -= 9
            d.ellipse([x0, top - 5, x1, top + 5], fill=GOLD + (170,), outline=edge)
            if h > 80:
                ax = (x0 + x1) / 2
                d.line([(ax, top - 5), (ax, top - 24)], fill=edge, width=2)
                if blink:
                    d.ellipse([ax - 3, top - 28, ax + 3, top - 22], fill=RED)
        for q in self.dust:
            q["r"] += 40 * dt
            q["y"] -= 18 * dt
            q["life"] -= dt
        self.dust = [q for q in self.dust if q["life"] > 0]
        for q in self.dust:
            d.ellipse([q["x"] - q["r"], q["y"] - q["r"], q["x"] + q["r"], q["y"] + q["r"]],
                      fill=(120, 100, 90, int(70 * q["life"] / 1.4)))
        d.rectangle([0, ground, W, H], fill=(14, 8, 8) if crash else (8, 18, 15))

    def draw_vault(self, d, info, t):
        cx, cy, R = W / 2, H / 2 + 10, 250
        k = min(1.0, info["t_in"] / 2.5)
        ang = math.radians(80) * k * k * (3 - 2 * k)
        d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(20, 12, 4))
        for rr, a in ((0.9, 30), (0.7, 45), (0.48, 70)):
            d.ellipse([cx - R * rr, cy - R * rr * 0.8 + 40, cx + R * rr, cy + R * rr * 0.8 + 40], fill=GOLD + (a,))
        for mx, mw, mh in ((cx - 120, 140, 80), (cx + 100, 170, 100), (cx - 10, 120, 56)):
            d.chord([mx - mw, cy + R * 0.86 - mh, mx + mw, cy + R * 0.86 + mh], 180, 360, fill=(206, 156, 54),
                    outline=GOLD_DARK, width=2)
        d.ellipse([cx - R - 24, cy - R - 24, cx + R + 24, cy + R + 24], outline=(96, 90, 86), width=28)
        for j in range(16):
            ba = j * math.pi / 8
            bx, by = cx + (R + 10) * math.cos(ba), cy + (R + 10) * math.sin(ba)
            d.ellipse([bx - 5, by - 5, bx + 5, by + 5], fill=(150, 144, 136))
        hinge = cx - R - 6
        hw = R * math.cos(ang)
        dcx = hinge + hw
        thick = 40 * math.sin(ang)
        if hw > 2:
            d.ellipse([dcx - hw - thick, cy - R, dcx + hw - thick, cy + R], fill=(52, 52, 56))
            d.ellipse([dcx - hw, cy - R, dcx + hw, cy + R], fill=(118, 116, 120), outline=(70, 70, 76), width=4)
            d.ellipse([dcx - hw * 0.78, cy - R * 0.78, dcx + hw * 0.78, cy + R * 0.78], outline=(88, 86, 92), width=3)
            rot = t * 0.8
            for j in range(3):
                a = rot + j * math.pi / 3
                dx, dy = 0.42 * R * math.cos(a) * math.cos(ang), 0.42 * R * math.sin(a)
                d.line([(dcx - dx, cy - dy), (dcx + dx, cy + dy)], fill=(60, 60, 66), width=9)
            d.ellipse([dcx - 26 * math.cos(ang), cy - 26, dcx + 26 * math.cos(ang), cy + 26], fill=(80, 80, 86))
        d.text((cx, cy - R - 48), "MARGIN & CO.  ·  PRIVATE RESERVES", font=self.a.futura_s,
               fill=(214, 180, 110), anchor="mm")

    def draw_icon(self, d, i, cx, cy, col):
        kind = SFX_LOOP[i]
        if kind == "ching":
            pts = [(cx - 26, cy + 16), (cx - 20, cy - 4), (cx - 14, cy - 18), (cx, cy - 24),
                   (cx + 14, cy - 18), (cx + 20, cy - 4), (cx + 26, cy + 16)]
            d.line(pts, fill=col, width=3)
            d.line([(cx - 30, cy + 16), (cx + 30, cy + 16)], fill=col, width=3)
            d.ellipse([cx - 5, cy + 18, cx + 5, cy + 28], fill=col)
        elif kind == "coin":
            d.ellipse([cx - 24, cy - 24, cx + 24, cy + 24], outline=col, width=3)
            d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=col, width=2)
        elif kind == "ratchet":
            d.ellipse([cx - 18, cy - 18, cx + 18, cy + 18], outline=col, width=3)
            for k in range(10):
                ang = k * math.pi / 5
                d.line([(cx + 18 * math.cos(ang), cy + 18 * math.sin(ang)),
                        (cx + 28 * math.cos(ang), cy + 28 * math.sin(ang))], fill=col, width=3)
        elif kind == "tear":
            zig = [(cx + 10 + (6 if k % 2 else -6), cy - 26 + k * 6.5) for k in range(9)]
            d.line([(cx + 4, cy - 26), (cx - 26, cy - 26), (cx - 26, cy + 26), (cx + 4, cy + 26)],
                   fill=col, width=3)
            d.line(zig, fill=col, width=3)
        elif kind == "jingle":
            for dx, dy in ((-14, 8), (14, 8), (0, -12)):
                d.ellipse([cx + dx - 13, cy + dy - 13, cx + dx + 13, cy + dy + 13], outline=col, width=3)
        elif kind == "thunk":
            d.rectangle([cx - 30, cy - 16, cx + 30, cy + 16], outline=col, width=3)
            d.line([(cx - 10, cy), (cx + 10, cy)], fill=col, width=4)

    def draw_register(self, d, info, t):
        """Seven sound slots of the cash-register loop (intro/outro)."""
        sp = 150
        x0 = W / 2 - 3 * sp
        y = H * 0.40
        for i in range(7):
            on = info["beat"] == i
            glow = math.exp(-info["beat_frac"] * 2.5) if on else 0.0
            col = lerp_col((40, 74, 54), GOLD_HI, glow)
            cx = x0 + i * sp
            if glow > 0.05:
                rr = 52 + 10 * glow
                d.ellipse([cx - rr, y - rr, cx + rr, y + rr], fill=GOLD + (int(40 * glow),))
            self.draw_icon(d, i, cx, y, col)
            d.text((cx, y + 70), SFX_LABEL[i], font=self.a.mono_s, fill=col, anchor="mm")

    def draw_counter(self, d, info, big):
        you_col = RED if self.you < 0 else CREAM
        if big:
            d.text((W / 2, H * 0.62), "YOUR BALANCE", font=self.a.futura_s, fill=CREAM + (150,), anchor="mm")
            d.text((W / 2, H * 0.69), f"$ {self.you:,.2f}", font=self.a.mono_l, fill=you_col, anchor="mm")
            return
        d.text((28, 46), "THEM", font=self.a.futura_s, fill=GOLD + (190,))
        d.text((90, 40), f"$ {self.them:,.2f}", font=self.a.mono_m, fill=GOLD)
        if info["name"] == "crash" and info["beat_frac"] < 0.5:
            d.text((90 + self.a.mono_m.getlength(f"$ {self.them:,.2f}") + 14, 46), "+BONUS",
                   font=self.a.futura_s, fill=MINT)
        d.text((28, 84), "YOU", font=self.a.futura_s, fill=you_col + (190,))
        d.text((90, 78), f"$ {self.you:,.2f}", font=self.a.mono_m, fill=you_col)

    def draw_ticker(self, img, info):
        tk = self.a.ticker
        loop = tk.info["loop"]
        speed = 3.0 if info["name"] != "crash" else 7.0
        off = int(self.scroll * speed / 2) % loop
        img.paste(tk.crop((off, 0, off + W, 34)), (0, 0))

    def draw_chart(self, d, info, t):
        k = (t - self.chart_origin) / self.tl.beat
        if k < 0:
            return
        n_vis, spacing, head_x = 30, W / 30, W - 90
        ks = [k - j for j in range(n_vis, -1, -1) if k - j >= 0]
        vals = [self.chart_value(x) for x in ks]
        lo, hi = min(vals), max(vals)
        if hi - lo < 30:
            mid = (hi + lo) / 2
            lo, hi = mid - 15, mid + 15
        def ymap(v):
            return lerp(H * 0.80, H * 0.24, (v - lo) / (hi - lo))
        pts = [(head_x - (k - x) * spacing, ymap(v)) for x, v in zip(ks, vals)]
        crash = info["name"] == "crash"
        col = RED if crash else MINT
        if len(pts) > 1:
            d.polygon(pts + [(pts[-1][0], H * 0.84), (pts[0][0], H * 0.84)], fill=col + (34,))
            d.line(pts, fill=col + (230,), width=3, joint="curve")
            hx, hy = pts[-1]
            g = 8 + 6 * self.env("kick", t, 0.2)
            d.ellipse([hx - g, hy - g, hx + g, hy + g], fill=col + (200,))
            d.text((hx - 60, hy + 26), f"{vals[-1] * 10:,.1f}", font=self.a.mono, fill=col, anchor="rm")
            return hx, hy
        return None

    def draw_tunnel(self, d, t, dt, bass):
        speed = 2.4 * (1 + 1.4 * bass)
        for n in self.notes:
            n["z"] -= speed * dt
            n["ang"] += n["spin"] * dt
        self.notes = [n for n in self.notes if n["z"] > 0.3]
        for n in sorted(self.notes, key=lambda n: -n["z"]):
            s = 300 / n["z"]
            cx, cy = W / 2 + n["x"] * s, H / 2 + n["y"] * s
            hw, hh = 0.55 * s, 0.25 * s
            ca, sa = math.cos(n["ang"]), math.sin(n["ang"])
            def rot(px, py):
                return (cx + px * ca - py * sa, cy + px * sa + py * ca)
            alpha = int(255 * min(1, (6.5 - n["z"]) / 2.5) * min(1, (n["z"] - 0.3) / 0.6))
            d.polygon([rot(-hw, -hh), rot(hw, -hh), rot(hw, hh), rot(-hw, hh)],
                      fill=PAPER + (alpha,), outline=(36, 88, 56, alpha))
            if s > 60:
                d.polygon([rot(-hw * 0.88, -hh * 0.8), rot(hw * 0.88, -hh * 0.8),
                           rot(hw * 0.88, hh * 0.8), rot(-hw * 0.88, hh * 0.8)], outline=(36, 88, 56, alpha))
                ox, oy = rot(0, 0)
                d.ellipse([ox - hh * 0.55, oy - hh * 0.62, ox + hh * 0.55, oy + hh * 0.62],
                          outline=(36, 88, 56, alpha), width=2)

    def draw_big_coin(self, img, t, kick):
        theta = t * math.pi * 1.1
        c = math.cos(theta)
        size = int(300 * (1 + 0.08 * kick))
        w = max(4, int(size * abs(c)))
        face = self.a.coin_face.resize((w, size), Image.BILINEAR)
        img.paste(face, (W // 2 - w // 2, H // 2 - size // 2), face)

    def update_coins(self, d, dt, gravity):
        for c in self.coins:
            c["vy"] += gravity * dt
            c["x"] += c["vx"] * dt
            c["y"] += c["vy"] * dt
            c["ph"] += c["spin"] * dt
        self.coins = [c for c in self.coins if c["y"] < H + 40]
        for c in self.coins:
            r = c["r"]
            k = abs(math.cos(c["ph"]))
            w = max(1.5, r * k)
            face = scale_col(GOLD, 0.5 + 0.5 * k)
            d.ellipse([c["x"] - w, c["y"] - r, c["x"] + w, c["y"] + r], fill=face,
                      outline=GOLD_DARK, width=max(1, int(r * 0.14)))
            if k > 0.45:
                iw, ir = w * 0.6, r * 0.6
                d.ellipse([c["x"] - iw, c["y"] - ir, c["x"] + iw, c["y"] + ir],
                          outline=GOLD_HI if k > 0.85 else GOLD_DARK, width=1)

    def update_sparks(self, d, dt):
        for s in self.sparks:
            s["x"] += s["vx"] * dt
            s["y"] += s["vy"] * dt
            s["life"] -= dt
        self.sparks = [s for s in self.sparks if s["life"] > 0]
        for s in self.sparks:
            a = int(255 * s["life"] / 0.7)
            d.line([(s["x"], s["y"]), (s["x"] - s["vx"] * 0.03, s["y"] - s["vy"] * 0.03)],
                   fill=GOLD_HI + (a,), width=2)

    def draw_title(self, d, text, y, alpha, font, spacing, col=CREAM):
        widths = [font.getlength(ch) for ch in text]
        total = sum(widths) + spacing * (len(text) - 1)
        x = W / 2 - total / 2
        for ch, w in zip(text, widths):
            d.text((x, y), ch, font=font, fill=col + (int(255 * alpha),), anchor="lm")
            x += w + spacing
        return x

    # --- satire layer -----------------------------------------------------
    def eye_font(self, r):
        size = max(8, int(r * 0.34))
        if size not in self.eye_fonts:
            self.eye_fonts[size] = ImageFont.truetype(FONT_MONO, size, index=1)
        return self.eye_fonts[size]

    def draw_mascot(self, d, x, y, r, t, laugh, parachute=False):
        """Mr. Margin: a top-hatted coin with dollar-sign eyes, monocle and cigar."""
        ink = (18, 16, 14)
        lw = max(2, int(r * 0.08))
        if parachute:
            cw = r * 4.8
            top = y - r * 4.3
            d.chord([x - cw / 2, top, x + cw / 2, top + cw * 0.75], 180, 360, fill=GOLD, outline=GOLD_DARK, width=3)
            rim = top + cw * 0.375
            for k in range(1, 6):
                gx = x - cw / 2 + cw * k / 6
                d.line([(gx, rim), (x + (gx - x) * 0.3, top + 4)], fill=GOLD_DARK, width=2)
            for k in range(7):
                gx = x - cw / 2 + cw * k / 6
                d.line([(gx, rim), (x + (k - 3) * r * 0.12, y - r * 0.85)], fill=(70, 50, 20, 220), width=1)
            d.text((x, rim - cw * 0.1), "GOLDEN PARACHUTE™", font=self.a.futura_s, fill=(70, 46, 8), anchor="mm")
        else:
            for sx in (-1, 1):
                d.line([(x + sx * r * 0.35, y + r * 0.8), (x + sx * r * 0.45, y + r * 1.45)], fill=ink, width=lw)
                d.ellipse([x + sx * r * 0.45 - r * 0.22, y + r * 1.38, x + sx * r * 0.45 + r * 0.22, y + r * 1.56],
                          fill=ink)
        wave = math.sin(t * 9) * r * 0.35
        d.line([(x - r * 0.9, y + r * 0.1), (x - r * 1.55, y - r * 0.55 + wave)], fill=ink, width=lw)
        d.line([(x + r * 0.9, y + r * 0.1), (x + r * 1.5, y + r * 0.45)], fill=ink, width=lw)
        d.ellipse([x - r, y - r, x + r, y + r], fill=GOLD, outline=GOLD_DARK, width=max(2, int(r * 0.1)))
        d.arc([x - r * 0.8, y - r * 0.8, x + r * 0.8, y + r * 0.8], 200, 250, fill=GOLD_HI, width=max(2, int(r * 0.08)))
        # top hat
        d.rectangle([x - r * 0.7, y - r * 1.0, x + r * 0.7, y - r * 0.88], fill=ink)
        d.rectangle([x - r * 0.42, y - r * 1.9, x + r * 0.42, y - r * 0.98], fill=ink)
        d.rectangle([x - r * 0.42, y - r * 1.2, x + r * 0.42, y - r * 1.06], fill=RED)
        # dollar eyes + monocle
        for ex in (-0.36, 0.36):
            cx, cy = x + ex * r, y - r * 0.22
            d.ellipse([cx - r * 0.21, cy - r * 0.21, cx + r * 0.21, cy + r * 0.21], fill=(250, 248, 240))
            d.text((cx, cy), "$", font=self.eye_font(r), fill=(20, 110, 50), anchor="mm")
        mx, my = x + 0.36 * r, y - 0.22 * r
        d.ellipse([mx - r * 0.28, my - r * 0.28, mx + r * 0.28, my + r * 0.28], outline=GOLD_HI,
                  width=max(2, int(r * 0.06)))
        d.line([(mx + r * 0.2, my + r * 0.2), (x + r * 0.75, y + r * 0.7)], fill=GOLD_HI, width=1)
        # grin
        hgt = r * (0.22 + 0.22 * laugh)
        my0 = y + r * 0.12
        d.chord([x - r * 0.52, my0 - hgt, x + r * 0.52, my0 + hgt], 0, 180, fill=(250, 248, 240),
                outline=(60, 30, 10), width=2)
        for k in range(1, 6):
            tx = x - r * 0.52 + r * 1.04 * k / 6
            d.line([(tx, my0), (tx, my0 + hgt * 0.35)], fill=(150, 140, 120), width=1)
        # cigar
        d.line([(x + r * 0.42, y + r * 0.3), (x + r * 1.0, y + r * 0.2)], fill=(110, 62, 30), width=max(3, int(r * 0.11)))
        d.ellipse([x + r * 0.96, y + r * 0.14, x + r * 1.08, y + r * 0.26], fill=(255, 120, 40))

    def draw_stamps(self, img, d, info):
        name = info["name"]
        for k, (p0, p1, text, fine, col) in enumerate(STAMPS.get(name, [])):
            if not p0 <= info["progress"] < p1:
                continue
            ts = (info["progress"] - p0) * info["length"]
            dur = (p1 - p0) * info["length"]
            key = (name, k)
            if key not in self.stamps:
                self.stamps[key] = make_stamp(text, col, self.seed + 31 * k + len(name))
            sp = self.stamps[key]
            land = min(1.0, ts / 0.12)
            if 0.12 <= ts < 0.16:
                self.shake = max(self.shake, 1.0)
            sc = 1 + 0.9 * (1 - land) ** 2
            fade = min(1.0, (dur - ts) / 0.3)
            spr = sp if sc < 1.01 else sp.resize((int(sp.width * sc), int(sp.height * sc)), Image.BILINEAR)
            cx = W / 2 + (-90 if k % 2 == 0 else 110)
            cy = H * 0.92 if name == "outro" else H * 0.24
            alpha = spr.getchannel("A")
            a = land * fade
            if a < 0.99:
                alpha = alpha.point(lambda v: int(v * a))
            img.paste(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)), alpha)
            if ts > 0.4 and name != "outro":
                shown = fine[:int((ts - 0.4) * 45)]
                d.text((cx, cy + sp.height / 2 + 14), shown, font=self.a.mono_s,
                       fill=CREAM + (int(210 * fade),), anchor="mm")

    def draw_skip_ad(self, d, info):
        ts = info["t_in"]
        click = min(7.0, info["length"] * 0.45)
        d.rounded_rectangle([28, H - 124, 150, H - 96], 4, fill=(250, 200, 40, 230))
        d.text((89, H - 110), f"Ad · 0:{max(0, int(info['length'] - ts)):02d}", font=self.a.futura_s,
               fill=(20, 20, 20), anchor="mm")
        if ts < 5:
            label, hot = f"Skip ad in {5 - int(ts)}", False
        elif ts < click:
            label, hot = "Skip ad  ▶|", True
        elif ts < click + 1.6:
            label, hot = "Nice try.", True
        else:
            label, hot = "Skip with Premium · $∞/mo", False
        # Size the button to its label so long labels never spill out.
        bw = max(260, int(self.a.futura.getlength(label)) + 48)
        box = [W - 40 - bw, H - 150, W - 40, H - 96]
        jolt = 6 * math.sin((ts - click) * 60) * math.exp(-(ts - click) * 6) if ts >= click else 0
        b = [box[0] + jolt, box[1], box[2] + jolt, box[3]]
        d.rectangle(b, fill=(10, 10, 10, 200), outline=(255, 255, 255, 200 if hot else 90), width=2)
        d.text(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), label, font=self.a.futura,
               fill=(255, 255, 255, 255 if hot else 150), anchor="mm")
        if 5 <= ts < click + 2.5:
            k = min(1.0, max(0.0, (ts - 5) / max(0.5, click - 5.3)))
            k = k * k * (3 - 2 * k)
            px = lerp(W * 0.62, (b[0] + b[2]) / 2 + 20, k)
            py = lerp(H * 0.62, (b[1] + b[3]) / 2 + 6, k)
            if click <= ts < click + 0.15:
                d.ellipse([px - 16, py - 16, px + 16, py + 16], outline=(255, 255, 255, 180), width=2)
            arrow = [(0, 0), (0, 26), (7, 20), (12, 31), (17, 29), (12, 18), (21, 18)]
            d.polygon([(px + ax, py + ay) for ax, ay in arrow], fill=(255, 255, 255), outline=(0, 0, 0))

    def draw_receipt(self, img, d, info):
        rc = self.a.receipt
        slot_y = int(H * 0.86)
        k = min(1.0, info["progress"] / 0.75)
        reveal = int(rc.height * k)
        if reveal > 0:
            part = rc.crop((0, 0, rc.width, reveal))
            img.paste(part, (W // 2 - rc.width // 2, slot_y - reveal), part)
        d.rounded_rectangle([W / 2 - 240, slot_y - 4, W / 2 + 240, slot_y + 60], 10, fill=(34, 34, 38))
        d.rectangle([W / 2 - 200, slot_y - 4, W / 2 + 200, slot_y + 4], fill=(8, 8, 8))
        d.text((W / 2, slot_y + 32), "PRINTING YOUR FUTURE ...", font=self.a.mono_s, fill=(120, 200, 140), anchor="mm")

    def post(self, img, info, fi, kick):
        """Print look: film grain + colour misregistration on hits."""
        light, dark = self.a.grain[fi % len(self.a.grain)]
        img.paste((255, 255, 255), (0, 0), light)
        img.paste((0, 0, 0), (0, 0), dark)
        hit = kick if info["name"] in ("groove", "rise", "solo", "crash") else 0.0
        dx = 1 + int(3 * hit) + int(5 * self.shake)
        r, g, b = img.split()
        img = Image.merge("RGB", (ImageChops.offset(r, dx, 0), g, ImageChops.offset(b, -dx, 1)))
        if self.shake > 0.05 or (info["name"] == "crash" and kick > 0.3):
            amp = 7 * max(kick if info["name"] == "crash" else 0, self.shake)
            img = ImageChops.offset(img, int(self.rng.normal(0, amp)), int(self.rng.normal(0, amp * 0.7)))
        self.shake *= 0.7
        return img

    # --- frame -------------------------------------------------------------
    def frame(self, fi):
        t = fi / FPS
        dt = 1 / FPS
        info = self.tl.at(t)
        name = info["name"]
        bass, high = self.f["bass"][fi], self.f["high"][fi]
        kick = self.env("kick", t, 0.18)

        bg = lerp_col(SECTION_BG[info["prev"]], SECTION_BG[name], min(1.0, info["t_in"] / 0.8))
        img = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(img, "RGBA")

        # React to events that happened since the previous frame.
        self.frame_kicks = 0
        for et, kind, val in self.new_events(t):
            if kind == "kick":
                self.frame_kicks += 1
            if kind == "coin" and name == "intro":
                self.you += 0.01
            if name in ("intro", "outro") and kind in ("coin", "jingle", "ching"):
                if name == "outro":
                    continue
                slot = SFX_LOOP.index(kind) if self.synth else info["beat"]
                x = W / 2 + (slot - 3) * 150
                for _ in range(6 if kind == "jingle" else 2):
                    self.spawn_coin(x + self.rng.normal(0, 12), H * 0.40 - 40,
                                    self.rng.normal(0, 60), self.rng.uniform(-260, -120))
            elif kind == "kick" and name in ("groove", "rise", "crash", "solo"):
                n = {"crash": 6, "solo": 1, "groove": 2}.get(name, 4)
                for _ in range(n):
                    self.spawn_coin(self.rng.uniform(40, W - 40), -30, self.rng.normal(0, 30),
                                    self.rng.uniform(80, 260))
                if name in ("groove", "rise"):
                    self.you += 0.01
                elif name == "crash":
                    self.you -= self.rng.uniform(1.5, 4.0)
            elif kind == "coin" and name in ("groove", "rise") and self.rng.random() < 0.3:
                self.spawn_coin(self.rng.uniform(40, W - 40), -30, 0, 120, r=self.rng.uniform(6, 12))
            elif kind == "note" or (kind == "coin" and name == "solo" and not self.synth):
                self.you -= 0.003
                self.notes.append({"x": self.rng.uniform(-2.2, 2.2), "y": self.rng.uniform(-1.3, 1.3),
                                   "z": 6.5, "ang": self.rng.uniform(0, 6.28), "spin": self.rng.normal(0, 1.5)})
                for _ in range(10):
                    ang = self.rng.uniform(0, 2 * math.pi)
                    sp = self.rng.uniform(250, 520)
                    self.sparks.append({"x": W / 2 + 150 * math.cos(ang), "y": H / 2 + 150 * math.sin(ang),
                                        "vx": sp * math.cos(ang), "vy": sp * math.sin(ang), "life": 0.7})
        self.them += {"groove": 1800 + 25000 * bass, "rise": 6000 + 70000 * bass,
                      "solo": 3000 + 20000 * bass, "crash": 90000 + 90000 * bass}.get(name, 0)
        if name == "solo" and fi % 8 == 0 and not self.ev_times.get("note"):
            # User audio has no note events; feed the tunnel from the beat grid instead.
            self.notes.append({"x": self.rng.uniform(-2.2, 2.2), "y": self.rng.uniform(-1.3, 1.3),
                               "z": 6.5, "ang": self.rng.uniform(0, 6.28), "spin": self.rng.normal(0, 1.5)})

        if name != "end":
            self.draw_background(d, info, t, dt, fi, kick)

        # Section content.
        bob = -abs(math.sin(info["beats"] * math.pi)) * 10
        if name == "intro":
            self.draw_register(d, info, t)
            self.draw_counter(d, info, big=True)
            a = min(1, info["t_in"] / 2.0) * min(1, max(0, 0.48 - info["progress"]) * 8)
            if a > 0:
                d.text((W / 2, H * 0.16), "A  S H A R E H O L D E R  P R E S E N T A T I O N", font=self.a.title_s,
                       fill=CREAM + (int(200 * a),), anchor="mm")
        elif name == "outro":
            self.draw_receipt(img, d, info)
            self.draw_mascot(d, W * 0.2, H * 0.55 + bob, 54, t, kick)
        elif name in ("groove", "rise", "crash"):
            head = self.draw_chart(d, info, t) if name in ("rise", "crash") else None
            if name == "groove" and info["t_in"] < 9:
                a = min(1, info["t_in"] / 0.4) * min(1, (9 - info["t_in"]) / 2.5)
                col = lerp_col(CREAM, GOLD_HI, kick)
                end_x = self.draw_title(d, "MONEY", H / 2 - 10, a, self.a.title, 30 + 14 * kick, col)
                d.text((end_x - 10, H / 2 - 70), "™", font=self.a.title_s, fill=col + (int(255 * a),))
            if name == "rise" and head:
                self.draw_mascot(d, head[0] - 10, head[1] - 86 + bob * 0.5, 40, t, kick)
            if name == "crash":
                drift = info["progress"]
                self.draw_mascot(d, lerp(W * 0.68, W * 0.82, drift) + 14 * math.sin(t * 1.3),
                                 H * 0.66 - 110 * drift + 10 * math.sin(t * 2.1), 44, t, 0.6 + 0.4 * kick,
                                 parachute=True)
                if info["beat"] in (0, 4):
                    a = math.exp(-info["beat_frac"] * 2) * 0.8
                    d.text((W - 40, H * 0.86), "SELL", font=self.a.title_m, fill=RED + (int(255 * a),), anchor="rm")
        elif name == "solo":
            self.draw_tunnel(d, t, dt, bass)
            self.draw_big_coin(img, t, kick + 0.6 * self.env("note", t, 0.12))
            d = ImageDraw.Draw(img, "RGBA")
            self.update_sparks(d, dt)

        if name != "end":
            gravity = 900 if name != "crash" else 1400
            self.update_coins(d, dt, gravity)
        if name == "solo":
            self.draw_skip_ad(d, info)
        if name not in ("intro", "outro", "end"):
            self.draw_ticker(img, info)
            self.draw_counter(d, info, big=False)
        if name != "end":
            self.draw_stamps(img, d, info)
        if self.lyrics:
            self.lyrics.draw(img, t)
        if name in ("groove", "rise", "solo", "crash"):
            d.rectangle([0, 0, W, H], fill=(255, 236, 190, int(22 * kick + 10 * high * kick)))

        if name == "end":
            a = min(1, info["t_in"] / 1.0) * min(1, (self.duration - t) / 1.2)
            self.draw_title(d, "MONEY", H / 2 - 50, a, self.a.title_m, 22, GOLD)
            if self.synth:
                line1, line2 = ("a satire  ·  original music & visuals",
                                "inspired by Pink Floyd, “Money” (1973)")
            else:
                line1, line2 = ("fan-made satirical visuals",
                                "music: Pink Floyd, “Money” (1973)")
            d.text((W / 2, H / 2 + 40), line1,
                   font=self.a.mono, fill=CREAM + (int(220 * a),), anchor="mm")
            d.text((W / 2, H / 2 + 76), line2,
                   font=self.a.mono_s, fill=CREAM + (int(150 * a),), anchor="mm")
            d.text((W / 2, H / 2 + 104), "this video has been monetized.",
                   font=self.a.mono_s, fill=CREAM + (int(90 * a),), anchor="mm")

        img.paste((0, 0, 0), (0, 0), self.a.vignette)
        img = self.post(img, info, fi, kick)
        fade = min(1.0, t / 1.2)
        if name == "outro":
            fade *= max(0.0, 1 - max(0.0, info["progress"] - 0.85) / 0.15)
        if fade < 1:
            img = Image.blend(Image.new("RGB", (W, H)), img, fade)
        return img


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", help="render against your own audio file instead of the synth track")
    ap.add_argument("--bpm", type=float, default=120.0,
                    help="tempo of the synth track (default 120); beats are tracked for --audio")
    ap.add_argument("--sections", help='e.g. "0:00=intro,0:20=groove,2:50=solo,4:50=crash,6:00=outro/4" '
                    '(append /N to override a section\'s meter)')
    ap.add_argument("--lyrics", help="time-stamped .lrc file you supply; rendered as ransom-note typography")
    ap.add_argument("--lyrics-offset", default="0",
                    help='shift lyric timing: "N" seconds, or piecewise by source time, e.g. "0:00=-14.9,7:00=-247.5"')
    ap.add_argument("--preview", type=float, help="only render the first N seconds")
    ap.add_argument("--out", default="out/money_mv.mp4")
    ap.add_argument("--seed", type=int, default=1973)
    ap.add_argument("--crf", type=int, default=23, help="x264 quality, higher = smaller file (default 23)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if args.audio:
        mono = load_audio(args.audio)
        duration = len(mono) / SR
        if args.sections:
            sections = parse_sections(args.sections)
        else:
            fr = [(0, "intro"), (0.06, "groove"), (0.30, "rise"), (0.45, "solo"), (0.78, "crash"), (0.93, "outro")]
            sections = [(f * duration, n) for f, n in fr]
        sections.append((max(sections[-1][0] + 1, duration - 4.0), "end"))
        audio_path = args.audio
        events = None
        print("tracking beats ...")
        beats = track_beats(mono)
        print(f"  {len(beats)} beats, median tempo {60 / np.median(np.diff(beats)):.1f} bpm")
    else:
        print("synthesizing soundtrack ...")
        stereo, events, sections, duration = build_soundtrack(args.bpm, args.seed)
        beats = None
        mono = stereo.mean(axis=0)
        audio_path = os.path.splitext(args.out)[0] + "_soundtrack.wav"
        write_wav(audio_path, stereo)
        print(f"  wrote {audio_path} ({duration:.1f}s)")

    render_dur = min(duration, args.preview) if args.preview else duration
    n_frames = int(render_dur * FPS)
    print("analyzing audio ...")
    feats = analyze(mono, int(duration * FPS) + 1)
    if events is None:
        events = detect_events(feats)

    timeline = Timeline(sections, args.bpm, duration, beats)
    lyrics = None
    if args.lyrics:
        lines = [ln for ln in load_lrc(args.lyrics, parse_shift(args.lyrics_offset)) if 0 <= ln[0] < duration]
        print(f"  {len(lines)} lyric lines in range")
        lyrics = Lyrics(lines, args.seed)
    video = Video(timeline, feats, events, Assets(), duration, args.seed, lyrics)

    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", audio_path, "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "256k", "-t", f"{render_dur:.3f}", "-movflags", "+faststart", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    for fi in range(n_frames):
        proc.stdin.write(video.frame(fi).tobytes())
        if fi % (FPS * 10) == 0:
            el = time.time() - t0
            print(f"  frame {fi}/{n_frames}  ({el:.0f}s elapsed)", flush=True)
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"done: {args.out}  ({n_frames} frames in {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
