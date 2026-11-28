#!/usr/bin/env python3
"""Generate royalty-free stereo warm-up / walk-up comedy club tracks for BOX 2.

Synthesizes warm Rhodes electric piano chords, upright/funk basslines, stereo tremolo,
and brushed club percussion into `/mnt/ssd/media/box2-music/*.mp3` so the 9:00 PM show
has ready-to-play stereo house music out of the box (drop any additional .mp3/.wav/.m4a
files into the same folder at any time).
"""
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave
import numpy as np

SR = 48000


def midi_to_hz(midi_note):
    return 440.0 * (2.0 ** ((midi_note - 69.0) / 12.0))


def synth_rhodes_chord(notes, dur_s, tremolo_hz=3.2, brightness=0.35):
    n = int(SR * dur_s)
    t = np.arange(n, dtype=np.float32) / SR
    env = (1.0 - np.exp(-t / 0.012)) * np.exp(-t / max(0.8, dur_s * 0.85))
    bell_env = np.exp(-t / 0.14) * brightness

    sig = np.zeros(n, dtype=np.float32)
    for m in notes:
        f = midi_to_hz(m)
        sig += 0.65 * np.sin(2.0 * np.pi * f * t)
        sig += 0.22 * np.sin(2.0 * np.pi * (2.0 * f) * t) * np.exp(-t / 0.6)
        sig += 0.10 * np.sin(2.0 * np.pi * (3.0 * f) * t) * bell_env
    sig *= env / max(1, len(notes))

    # Warm stereo Rhodes auto-panning tremolo
    pan = 0.5 + 0.28 * np.sin(2.0 * np.pi * tremolo_hz * t)
    left = sig * np.sqrt(1.0 - pan * 0.5)
    right = sig * np.sqrt(0.5 + pan * 0.5)
    return np.column_stack([left, right])


def synth_bass_note(midi_note, dur_s):
    n = int(SR * dur_s)
    t = np.arange(n, dtype=np.float32) / SR
    f = midi_to_hz(midi_note)
    env = (1.0 - np.exp(-t / 0.008)) * np.exp(-t / max(0.25, dur_s * 0.65))
    sig = (0.78 * np.sin(2.0 * np.pi * f * t) + 0.22 * np.sin(2.0 * np.pi * 2.0 * f * t) * np.exp(-t / 0.18)) * env
    return np.column_stack([sig, sig])


def synth_drums(bars, bpm, swing=0.04):
    beat_s = 60.0 / bpm
    bar_s = 4.0 * beat_s
    total_n = int(SR * bars * bar_s)
    out = np.zeros((total_n, 2), dtype=np.float32)
    rng = np.random.default_rng(42)

    # Soft club kick
    kick_n = int(0.16 * SR)
    kt = np.arange(kick_n, dtype=np.float32) / SR
    k_freq = 52.0 + 75.0 * np.exp(-kt / 0.025)
    k_phase = 2.0 * np.pi * np.cumsum(k_freq) / SR
    kick = np.sin(k_phase) * np.exp(-kt / 0.065) * 0.42

    # Brushed snare / rim
    snare_n = int(0.11 * SR)
    st = np.arange(snare_n, dtype=np.float32) / SR
    snare = (rng.standard_normal(snare_n).astype(np.float32) * 0.16 + 0.12 * np.sin(2.0 * np.pi * 185.0 * st)) * np.exp(-st / 0.04)

    # Crisp hi-hat
    hat_n = int(0.055 * SR)
    ht = np.arange(hat_n, dtype=np.float32) / SR
    noise = rng.standard_normal(hat_n).astype(np.float32)
    hat = (noise - np.roll(noise, 1)) * np.exp(-ht / 0.016) * 0.07

    for bar in range(bars):
        b0 = bar * bar_s
        for k_beat in (0.0, 1.5, 2.5):
            idx = int((b0 + k_beat * beat_s) * SR)
            end = min(total_n, idx + kick_n)
            if end > idx:
                out[idx:end, 0] += kick[:end - idx]
                out[idx:end, 1] += kick[:end - idx]

        for s_beat in (1.0, 3.0):
            idx = int((b0 + s_beat * beat_s) * SR)
            end = min(total_n, idx + snare_n)
            if end > idx:
                out[idx:end, 0] += snare[:end - idx] * 0.95
                out[idx:end, 1] += snare[:end - idx] * 1.05

        for eighth in range(8):
            offset = (swing * beat_s) if (eighth % 2 == 1) else 0.0
            idx = int((b0 + eighth * 0.5 * beat_s + offset) * SR)
            end = min(total_n, idx + hat_n)
            if end > idx:
                vel = 1.0 if (eighth % 2 == 0) else 0.65
                out[idx:end, 0] += hat[:end - idx] * vel * 0.85
                out[idx:end, 1] += hat[:end - idx] * vel * 1.15
    return out


def render_track(out_mp3: Path, bpm: float, bars: int, progression, bass_pattern, tremolo_hz=3.0, brightness=0.35):
    beat_s = 60.0 / bpm
    bar_s = 4.0 * beat_s
    total_n = int(SR * bars * bar_s)
    mix = synth_drums(bars=bars, bpm=bpm)

    for bar in range(bars):
        ch_notes = progression[bar % len(progression)]
        b_notes = bass_pattern[bar % len(bass_pattern)]
        b0 = bar * bar_s

        chord_audio = synth_rhodes_chord(ch_notes, bar_s, tremolo_hz=tremolo_hz, brightness=brightness) * 0.58
        idx = int(b0 * SR)
        end = min(total_n, idx + chord_audio.shape[0])
        mix[idx:end] += chord_audio[:end - idx]

        step_s = bar_s / len(b_notes)
        for j, bn in enumerate(b_notes):
            b_audio = synth_bass_note(bn, step_s * 0.92) * 0.44
            b_idx = int((b0 + j * step_s) * SR)
            b_end = min(total_n, b_idx + b_audio.shape[0])
            if b_end > b_idx:
                mix[b_idx:b_end] += b_audio[:b_end - b_idx]

    # Smooth 1.5s fade-in and 2.0s fade-out for seamless playlist transitions
    fi = min(total_n // 4, int(1.5 * SR))
    fo = min(total_n // 4, int(2.0 * SR))
    mix[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)[:, None]
    mix[-fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)[:, None]

    peak = float(np.max(np.abs(mix)))
    if peak > 1e-6:
        mix = mix * (0.82 / peak)
    pcm16 = np.clip(mix * 32767.0, -32767.0, 32767.0).astype(np.int16)

    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav_path = tf.name
    try:
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes(pcm16.tobytes())
        subprocess.run(
            ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", wav_path, "-c:a", "libmp3lame", "-b:a", "192k", str(out_mp3)],
            check=True,
        )
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/ssd/media/box2-music")
    out_dir.mkdir(parents=True, exist_ok=True)

    tracks = [
        (
            out_dir / "01_box2_warm_rhodes_lounge.mp3",
            86.0,
            28,
            # Dm9 -> G13 -> Cmaj9 -> A7alt (classic warm comedy cellar jazz-lounge)
            [[62, 65, 69, 72, 76], [59, 65, 69, 71, 76], [60, 64, 67, 71, 74], [57, 61, 67, 70, 73]],
            [[38, 38, 45, 43], [43, 43, 47, 45], [36, 36, 43, 40], [45, 45, 40, 37]],
            2.8,
            0.32,
        ),
        (
            out_dir / "02_showtime_funk_walkup.mp3",
            104.0,
            36,
            # Em9 -> A13 -> Cmaj7 -> B7#9 (upbeat show-intro / walk-up groove)
            [[64, 67, 71, 74, 78], [61, 67, 69, 73, 78], [60, 64, 67, 71, 74], [59, 63, 69, 74]],
            [[40, 40, 47, 45, 40, 43, 45, 47], [45, 45, 52, 49, 45, 47, 49, 52],
             [36, 36, 43, 40, 36, 40, 43, 45], [35, 35, 42, 39, 35, 39, 42, 45]],
            4.0,
            0.48,
        ),
        (
            out_dir / "03_canton_midnight_groove.mp3",
            78.0,
            24,
            # Fm9 -> Bb13 -> Ebmaj9 -> C7b9 (late-night mellow intermission)
            [[65, 68, 72, 75, 79], [62, 68, 70, 74, 79], [63, 67, 70, 74, 77], [60, 64, 70, 73]],
            [[41, 48, 46, 44], [46, 41, 43, 46], [39, 46, 43, 41], [36, 43, 40, 39]],
            2.4,
            0.26,
        ),
    ]

    for path, bpm, bars, prog, bass, trem, bright in tracks:
        render_track(path, bpm, bars, prog, bass, tremolo_hz=trem, brightness=bright)
        print(f"Generated {path.name} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
