"""课堂演示素材生成器（无版权）：合成 60s/96BPM 曲子，并从同一份乐谱写 timeline。

输出：
  demo/demo.wav        临时 44.1k 立体声
  demo/demo.mp3        发送/播放用（128k）
  demo/timeline.json   乐谱真值（notes/events/beats/downbeats/segments）
  demo/features.json   analyze.py 的分析结果（给五支装置）
  demo/demo.js         base64 音频 + 两个 JSON（file:// 下也能用）
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
SR = 44100
BPM = 96.0
BEAT = 60.0 / BPM          # 0.625
BAR = 4 * BEAT             # 2.5
BARS = 24
DUR = BARS * BAR           # 60.0
N = int(round(DUR * SR))
rng = np.random.default_rng(20261020)

# 和声：Am F C G（每小节一个），第 0 小节起
CHORDS = [
    (57, [57, 60, 64]),   # Am
    (53, [53, 57, 60]),   # F
    (48, [48, 52, 55]),   # C
    (55, [55, 59, 62]),   # G
]
SCALE = [57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 74, 76]  # A 小调音阶

L = np.zeros(N, dtype=np.float64)
R = np.zeros(N, dtype=np.float64)


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def add(sig: np.ndarray, start: float, gain: float = 1.0, pan: float = 0.0):
    i0 = int(round(start * SR))
    if i0 >= N:
        return
    n = min(len(sig), N - i0)
    if n <= 0:
        return
    gl = gain * np.sqrt((1 - pan) / 2)
    gr = gain * np.sqrt((1 + pan) / 2)
    L[i0:i0 + n] += sig[:n] * gl
    R[i0:i0 + n] += sig[:n] * gr


def env_ar(n: int, a: float, r: float) -> np.ndarray:
    e = np.ones(n)
    na = max(1, int(a * SR))
    nr = max(1, int(r * SR))
    na = min(na, n)
    nr = min(nr, n - na)
    e[:na] = np.linspace(0, 1, na) ** 1.5
    if nr > 0:
        e[n - nr:] = np.linspace(1, 0, nr) ** 1.4
    return e


def pad_note(midi: int, dur: float, vib: float = 0.0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = midi_hz(midi)
    ph = 2 * np.pi * f * t + vib * np.sin(2 * np.pi * 0.27 * t)
    s = np.sin(ph) + 0.35 * np.sin(2 * ph + 0.4) + 0.18 * np.sin(3 * ph)
    return s * env_ar(n, 0.35, 0.65) * 0.055


def pluck(midi: int, dur: float, bright: float = 0.35) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = midi_hz(midi)
    s = np.sin(2 * np.pi * f * t) + bright * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
    e = np.exp(-t / max(0.08, dur * 0.55))
    e[:min(n, 160)] *= np.linspace(0, 1, min(n, 160))
    return s * e


def kick() -> np.ndarray:
    n = int(0.32 * SR)
    t = np.arange(n) / SR
    f = 48 + 92 * np.exp(-t / 0.045)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.16)


def snare() -> np.ndarray:
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    noise = rng.normal(0, 1, n)
    hp = np.diff(np.concatenate([[0.0], noise]))
    body = np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.06)
    return (0.55 * hp + 0.45 * body) * np.exp(-t / 0.10)


def hat(open_: bool = False) -> np.ndarray:
    n = int((0.16 if open_ else 0.055) * SR)
    t = np.arange(n) / SR
    noise = rng.normal(0, 1, n)
    hp = np.diff(np.concatenate([[0.0], noise]))
    return hp * np.exp(-t / (0.09 if open_ else 0.022))


def crash() -> np.ndarray:
    n = int(1.4 * SR)
    t = np.arange(n) / SR
    noise = rng.normal(0, 1, n)
    hp = np.diff(np.concatenate([[0.0], noise]))
    return hp * np.exp(-t / 0.42)


# ---------------- 段落 ----------------
# bars: 0-4 intro, 4-10 build, 10-18 peak, 18-21 break, 21-24 outro
SECTIONS = [
    ("intro", 0, 4, 0.22, 0.30, 0.28, 0.12, 0.50),
    ("build", 4, 10, 0.55, 0.52, 0.50, 0.20, 0.62),
    ("peak", 10, 18, 0.90, 0.78, 0.70, 0.32, 0.74),
    ("break", 18, 21, 0.38, 0.44, 0.58, 0.18, 0.46),
    ("outro", 21, 24, 0.18, 0.32, 0.20, 0.10, 0.38),
]


def section_of_bar(bar: int):
    for s in SECTIONS:
        if s[1] <= bar < s[2]:
            return s
    return SECTIONS[-1]


# ---------------- 乐谱（同时用于合成与 timeline） ----------------
notes = []      # {start,end,midi,strength,glide_cents,vibrato_depth,voice}
onsets = []     # {t,kind,band,strength}

# 低音：每小节 8 分音符，根音（低八度），第 0/2 拍更重
for bar in range(BARS):
    root, _ = CHORDS[bar % 4]
    for k in range(8):
        t0 = bar * BAR + k * (BEAT / 2)
        if k in (0, 3, 4, 6) or bar >= 4:
            dur = 0.26 if k % 2 == 0 else 0.18
            strength = 0.85 if k in (0, 4) else 0.55
            notes.append({"start": t0, "end": t0 + dur, "midi": root - 12,
                          "strength": strength, "glide_cents": 0, "vibrato_depth": 0.02, "voice": "bass"})
            onsets.append({"t": t0, "kind": "note_on", "midi": root - 12, "strength": strength, "voice": "bass"})

# 旋律动机：每两小节一句；build 起进入，peak 加密，break 稀疏，outro 收尾
MOTIF = [
    [(0, 69, 1), (1, 72, 1), (2, 71, 2), (4, 67, 1), (5, 69, 1), (6, 64, 2)],
    [(0, 64, 1), (1, 67, 1), (2, 69, 2), (4, 72, 1), (5, 71, 1), (6, 69, 2)],
    [(0, 69, 1), (1, 72, 1), (2, 76, 2), (4, 74, 1), (5, 72, 1), (6, 71, 2)],
    [(0, 67, 1), (1, 69, 1), (2, 72, 2), (4, 71, 1), (5, 69, 1), (6, 67, 2)],
]
mel_notes = []
for bar in range(4, BARS):
    if bar >= 18 and bar < 21 and bar % 2 == 1:
        continue
    phrase = MOTIF[(bar // 2) % 4]
    step = BEAT / 2
    for (beat_off, midi, length) in phrase:
        t0 = bar * BAR + beat_off * step
        if t0 >= DUR - 0.2:
            continue
        dur = length * step * 0.92
        strength = 0.9 if section_of_bar(bar)[0] == "peak" else 0.7
        mel_notes.append({"start": t0, "end": min(DUR, t0 + dur), "midi": midi,
                          "strength": strength, "glide_cents": 0,
                          "vibrato_depth": 0.09 if length >= 2 else 0.05, "voice": "melody"})
        onsets.append({"t": t0, "kind": "note_on", "midi": midi, "strength": strength, "voice": "melody"})
notes.extend(mel_notes)

# ---------------- 合成 ----------------
for bar in range(BARS):
    sec = section_of_bar(bar)
    root, chord = CHORDS[bar % 4]
    # pad：整小节
    for j, m in enumerate(chord):
        add(pad_note(m, BAR * 0.98, 0.10 + 0.05 * j), bar * BAR, 0.9, pan=(-0.5 + 0.25 * j))
    # 低音
    for nn in [x for x in notes if x["voice"] == "bass" and bar * BAR <= x["start"] < (bar + 1) * BAR]:
        g = 0.16 if nn["strength"] > 0.7 else 0.11
        add(pluck(nn["midi"], nn["end"] - nn["start"] + 0.05, 0.5), nn["start"], g)
    # 鼓
    if bar >= 2:
        for beat in range(4):
            t0 = bar * BAR + beat * BEAT
            if beat in (0, 2):
                add(kick(), t0, 0.42 if sec[0] != "intro" else 0.26)
            if beat in (1, 3) and bar >= 4:
                add(snare(), t0, 0.20 if sec[0] != "peak" else 0.26)
            for half in (0, 1):
                if bar >= 4 or half == 0:
                    add(hat(open_=(half == 1 and beat == 3)), t0 + half * BEAT / 2,
                        0.045 if sec[0] == "intro" else 0.075, pan=0.25)
    if bar in (10, 18):
        add(crash(), bar * BAR, 0.13, pan=-0.2)

# 旋律
for nn in mel_notes:
    sec = section_of_bar(int(nn["start"] // BAR))
    g = 0.15 if sec[0] == "peak" else 0.115
    add(pluck(nn["midi"], nn["end"] - nn["start"] + 0.03, 0.28), nn["start"], g, pan=0.15)

# 母线：淡入/淡出、软限幅、归一
tt = np.arange(N) / SR
fade = np.minimum(1, tt / 0.8) * np.minimum(1, (DUR - tt) / 2.0)
L *= fade
R *= fade
mix = np.stack([L, R], axis=1)
mix = np.tanh(mix * 1.15)
mix *= 0.89 / max(1e-9, np.abs(mix).max())
pcm = (mix * 32767).astype(np.int16)

wav = DEMO / "demo.wav"
import wave
with wave.open(str(wav), "wb") as fh:
    fh.setnchannels(2)
    fh.setsampwidth(2)
    fh.setframerate(SR)
    fh.writeframes(pcm.tobytes())

import imageio_ffmpeg
ff = imageio_ffmpeg.get_ffmpeg_exe()
mp3 = DEMO / "demo.mp3"
r = subprocess.run([ff, "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3)],
                   capture_output=True)
if r.returncode != 0 or not mp3.exists():
    raise SystemExit("mp3 失败: " + r.stderr.decode("utf-8", "replace")[-300:])

# ---------------- timeline（乐谱真值） ----------------
beats = [round(k * BEAT, 6) for k in range(int(DUR / BEAT) + 1)]
downbeats = [round(k * BAR, 6) for k in range(BARS)]
events = []
for k, t in enumerate(beats):
    events.append({"t": round(t, 4), "kind": "downbeat" if k % 4 == 0 else "beat",
                   "strength": 0.9 if k % 4 == 0 else 0.55})
for nn in notes:
    events.append({"t": round(nn["start"], 4), "kind": "note_on", "midi": int(nn["midi"]),
                   "strength": nn["strength"], "voice": nn["voice"]})
    events.append({"t": round(nn["end"], 4), "kind": "note_off", "midi": int(nn["midi"]),
                   "strength": nn["strength"], "voice": nn["voice"]})
for o in onsets:
    if o["kind"] == "note_on":
        events.append({"t": round(o["t"], 4), "kind": "onset", "midi": int(o["midi"]),
                       "strength": o["strength"], "band": "mid"})
for bar in range(BARS):
    for beat in range(4):
        t0 = bar * BAR + beat * BEAT
        if beat in (0, 2):
            events.append({"t": round(t0, 4), "kind": "onset", "band": "low", "strength": 0.8})
        if beat in (1, 3) and bar >= 4:
            events.append({"t": round(t0, 4), "kind": "onset", "band": "high", "strength": 0.55})

segments = []
for (name, b0, b1, en, br, te, no, lh) in SECTIONS:
    a, z = b0 * BAR, b1 * BAR
    ons = [x for x in events if x["kind"] == "onset" and a <= x["t"] < z]
    segments.append({"start": round(a, 3), "end": round(z, 3), "bars": b1 - b0,
                     "energy": en, "bright": br, "tension": te, "noise": no,
                     "lowhigh": lh, "onset_per_s": round(len(ons) / max(1e-6, z - a), 3),
                     "novelty": 0.5, "name": name})

timeline = {
    "schema": 1, "kind": "timeline",
    "source": {"path": "demo.mp3", "name": "课堂演示 · 96 BPM",
               "sr_file": SR, "sr": 22050, "channels": 2, "duration": DUR, "fps": 30.0},
    "features": {"rhythm": {"bpm": BPM, "grid_significant": True, "bpm_basis": "manual_expect"},
                 "key": {"name": "A minor", "mode": "minor", "corr": 1.0},
                 "notes_rule": "合成乐谱真值（非检测）：notes 为作曲时写下的音符"},
    "beats": beats, "downbeats": downbeats,
    "onsets": [x for x in events if x["kind"] == "onset"],
    "notes": notes, "events": events, "segments": segments,
}
(DEMO / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")

# ---------------- analyze.py -> features ----------------
feat_dir = DEMO / "_feat"
feat_dir.mkdir(exist_ok=True)
py = sys.executable
r = subprocess.run([py, str(ROOT.parent / "音频标注台/tools/analyze.py"), str(mp3),
                    "--outdir", str(feat_dir), "--expect-bpm", str(int(BPM)),
                    "--stems", "hpss", "--mert", "off"], capture_output=True)
if r.returncode != 0:
    raise SystemExit("analyze 失败: " + r.stderr.decode("utf-8", "replace")[-400:])
cands = sorted(feat_dir.glob("*.features.json"))
if not cands:
    raise SystemExit("analyze 没有产出 features.json")
(DEMO / "features.json").write_text(cands[0].read_text(encoding="utf-8"), encoding="utf-8")

# 精简：features 里的 stems wav 指向不在包里的文件，契约允许缺失；删掉临时 wav
for w in feat_dir.glob("*.wav"):
    w.unlink()
wav.unlink(missing_ok=True)

# ---------------- demo.js（base64，file:// 可用） ----------------
audio_b64 = base64.b64encode(mp3.read_bytes()).decode()
feat = json.loads((DEMO / "features.json").read_text(encoding="utf-8"))
# 分析器读到 192（96 的倍层级，常见的 octave 歧义）；我们是作曲方，按真值人工确认 96。
# 这与标注台里"人工选定候选"等价，bundle 的 bpm_source 写"人工输入"。
raw_bpm = float((feat.get("rhythm") or {}).get("bpm") or 0)
if abs(raw_bpm / BPM - 2.0) < 0.02:
    r = feat["rhythm"]
    r["bpm"] = BPM
    r["period_s"] = BEAT
    r["bar_period_s"] = BAR
    r["beats"] = [round(k * BEAT, 6) for k in range(int(DUR / BEAT) + 1)]
    r["downbeats"] = [round(k * BAR, 6) for k in range(BARS)]
    r["bpm_half"] = BPM / 2
    r["bpm_double"] = BPM * 2
    r["bpm_basis"] = "manual_expect(96)；分析器原读 192，人工切回半速"
    r["grid_significant"] = True
    (DEMO / "features.json").write_text(json.dumps(feat, ensure_ascii=False), encoding="utf-8", )
    print("human octave fix: 192 -> 96")
# 自动建议段（非人工）：用于展示"建议段可显示但不驱动"
sugg = (feat.get("structure") or {}).get("suggestions_by_k", {}).get("6", [])
regions = [{"t0": float(s["start"]), "t1": float(s["end"]), "name": "建议段", "moods": [],
            "func": "", "sev": None, "auto": True, "confirmed": False, "sketch": []} for s in sugg]
payload = {"audio_b64": audio_b64, "audio_name": "demo.mp3", "audio_type": "audio/mpeg",
           "features": feat, "timeline": timeline, "regions": regions,
           "title": "课堂演示 · 96 BPM · 自制"}
js = "window.__DEMO__=" + json.dumps(payload, ensure_ascii=False) + ";\n"
(DEMO / "demo.js").write_text(js, encoding="utf-8")
print("ok", "mp3", mp3.stat().st_size, "features", (DEMO / "features.json").stat().st_size,
      "timeline", (DEMO / "timeline.json").stat().st_size, "demo.js", (DEMO / "demo.js").stat().st_size)
