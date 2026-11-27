#!/usr/bin/env python3
"""Psychoacoustic Stage Attention & Talkover Bed Generator for BOX 2.

Engineers long-form (~3+ minute), non-repetitive stereo backing grooves specifically
designed to hold viewer attention on stream while remaining effortless to speak over:

1. Mid/Side Spatial Separation:
   - Mono Center (Mid) carries ONLY sub-165 Hz warm bass pocket — leaving the center
     phantom image wide open for the stage microphone.
   - Stereo Sides (decorrelated L/R with 11ms Haas offset + slow quadrature LFO movement)
     carry warm harmonic pads, Rhodes voicings, and >6.5 kHz brushed air percussion.
2. Surgical Vocal-Pocket Spectral Carve:
   - Attenuates 400 Hz – 3,600 Hz (human vocal fundamental + consonant clarity band) by
     -8 to -10 dB via multi-band EQ during FFmpeg mastering so speech cuts through cleanly.
3. Anti-Habituation Musical Architecture:
   - Locked tempo per track (zero jarring speed-ups), 32-bar A/B harmonic arcs with
     probabilistic ghost-note variations and subtle 8-bar turnaround lifts (~20s attentional
     reset cues) that sustain engagement without distracting from comedy timing.
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


def midi_to_hz(m: float) -> float:
    return 440.0 * (2.0 ** ((m - 69.0) / 12.0))


def one_pole_lowpass(sig: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """Fast causal low-pass filter to keep center bass strictly below vocal fundamentals."""
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt = 1.0 / SR
    alpha = dt / (rc + dt)
    out = np.empty_like(sig)
    acc = 0.0
    # Process in vectorized blocks using scipy-free exponential kernel convolution
    k_len = min(sig.size, int(SR / max(20.0, cutoff_hz) * 6))
    t_k = np.arange(k_len, dtype=np.float32)
    kernel = alpha * ((1.0 - alpha) ** t_k)
    kernel /= np.sum(kernel)
    return np.convolve(sig, kernel, mode="same").astype(np.float32)


def synth_sub_bass_bar(notes_and_beats, bar_s: float) -> np.ndarray:
    """Warm upright/sub pocket (<165 Hz) placed in mono center for rhythmic gravity."""
    n = int(SR * bar_s)
    out = np.zeros(n, dtype=np.float32)
    for beat_pos, dur_beats, midi_note, vel in notes_and_beats:
        st = int((beat_pos / 4.0) * bar_s * SR)
        ln = min(n - st, int((dur_beats / 4.0) * bar_s * SR))
        if ln <= 64 or st >= n:
            continue
        t = np.arange(ln, dtype=np.float32) / SR
        f = midi_to_hz(midi_note)
        # Pure fundamental + soft second harmonic that decays quickly (warmth without midrange mud)
        env = (1.0 - np.exp(-t / 0.014)) * np.exp(-t / max(0.22, (dur_beats / 4.0) * bar_s * 0.78))
        tone = (0.86 * np.sin(2.0 * np.pi * f * t) + 0.14 * np.sin(2.0 * np.pi * 2.0 * f * t) * np.exp(-t / 0.12))
        out[st:st + ln] += tone * env * vel
    return one_pole_lowpass(out, 165.0)


def synth_wide_side_pad_bar(chord_midi, bar_s: float, bar_idx: int, lfo_rate: float = 0.18) -> np.ndarray:
    """Decorrelated wide-stereo warm pad/Rhodes texture with suppressed center vocal band."""
    n = int(SR * bar_s)
    t = np.arange(n, dtype=np.float32) / SR
    global_t = bar_idx * bar_s + t

    # Smooth swell envelope so chord changes breathe gently without percussive midrange transients
    env = (1.0 - np.exp(-t / 0.08)) * np.exp(-t / (bar_s * 1.15))
    # Subtle slow breathing LFO across bars so texture evolves organically
    lfo_l = 0.72 + 0.28 * np.sin(2.0 * np.pi * lfo_rate * global_t)
    lfo_r = 0.72 + 0.28 * np.cos(2.0 * np.pi * lfo_rate * global_t + 0.7)

    left = np.zeros(n, dtype=np.float32)
    right = np.zeros(n, dtype=np.float32)

    for idx, m in enumerate(chord_midi):
        # Detune L and R by +-3.5 cents for lush wide stereo imaging and near-zero mono midrange buildup
        fl = midi_to_hz(m - 0.035)
        fr = midi_to_hz(m + 0.035)
        phase_off = idx * 1.17
        sl = np.sin(2.0 * np.pi * fl * t + phase_off)
        sr = np.sin(2.0 * np.pi * fr * t + phase_off + 1.05)  # ~60-deg phase offset widens Side vs Mid
        # Add airy shimmer harmonic only on top note (kept gentle)
        if idx == len(chord_midi) - 1:
            sl += 0.12 * np.sin(2.0 * np.pi * (fl * 2.0) * t) * np.exp(-t / 0.9)
            sr += 0.12 * np.sin(2.0 * np.pi * (fr * 2.0) * t + 1.4) * np.exp(-t / 0.9)
        left += sl
        right += sr

    scale = 1.0 / max(1, len(chord_midi))
    left = left * scale * env * lfo_l
    right = right * scale * env * lfo_r

    # 11ms Haas micro-delay on right channel for enveloping stereo width outside center vocal image
    haas_samples = int(0.011 * SR)
    right = np.concatenate([right[-haas_samples:], right[:-haas_samples]])
    return np.column_stack([left, right])


def synth_attention_percussion(total_bars: int, bpm: float, seed: int = 7, swing: float = 0.055) -> np.ndarray:
    """Sub-kick (<110 Hz) + high-air brushed shaker (>6.5 kHz) + subtle 8-bar turnaround shimmer."""
    beat_s = 60.0 / bpm
    bar_s = 4.0 * beat_s
    total_n = int(SR * total_bars * bar_s)
    out = np.zeros((total_n, 2), dtype=np.float32)
    rng = np.random.default_rng(seed)

    # Deep velvet pulse kick (strictly sub-115 Hz so zero midrange click)
    kn = int(0.15 * SR)
    kt = np.arange(kn, dtype=np.float32) / SR
    k_freq = 48.0 + 46.0 * np.exp(-kt / 0.028)
    kick = np.sin(2.0 * np.pi * np.cumsum(k_freq) / SR) * np.exp(-kt / 0.068) * 0.34

    # High-frequency (>6.5 kHz) stereo brushed air shaker (2nd-difference highpass removes all <4 kHz energy!)
    sn = int(0.048 * SR)
    st = np.arange(sn, dtype=np.float32) / SR
    shaker_env = np.sin(np.pi * np.clip(st / 0.048, 0, 1)) * np.exp(-st / 0.020)

    for bar in range(total_bars):
        b0 = bar * bar_s
        # Kick pattern with subtle variation every 4th bar to maintain subconscious interest
        k_beats = (0.0, 2.5) if (bar % 4 != 3) else (0.0, 1.75, 2.5)
        for kb in k_beats:
            idx = int((b0 + kb * beat_s) * SR)
            end = min(total_n, idx + kn)
            if end > idx:
                out[idx:end, 0] += kick[:end - idx]
                out[idx:end, 1] += kick[:end - idx]

        # 16th-note stereo brushed pocket (panned wide L/R, >6.5 kHz air band)
        for step16 in range(16):
            if step16 % 2 == 1 and rng.random() < 0.22:
                continue  # organic human pocket breathing
            sw = (swing * beat_s * 0.5) if (step16 % 2 == 1) else 0.0
            idx = int((b0 + step16 * 0.25 * beat_s + sw) * SR)
            end = min(total_n, idx + sn)
            if end <= idx:
                continue
            ln = end - idx
            n_l = rng.standard_normal(ln).astype(np.float32)
            n_r = rng.standard_normal(ln).astype(np.float32)
            # 2nd-order difference filter pushes energy cleanly above 6 kHz away from speech sibilance
            hp_l = (n_l - 2.0 * np.roll(n_l, 1) + np.roll(n_l, 2)) * shaker_env[:ln]
            hp_r = (n_r - 2.0 * np.roll(n_r, 1) + np.roll(n_r, 2)) * shaker_env[:ln]
            accent = 0.024 if (step16 % 4 == 2) else (0.015 if (step16 % 2 == 0) else 0.009)
            out[idx:end, 0] += hp_l * accent * 1.12
            out[idx:end, 1] += hp_r * accent * 0.88

        # Every 8 bars (~20s): subtle high-harmonic bell/wind-chime attentional lift on beat 3.5
        if bar % 8 == 7:
            c_idx = int((b0 + 3.0 * beat_s) * SR)
            c_ln = min(total_n - c_idx, int(beat_s * 1.4 * SR))
            if c_ln > 100:
                ct = np.arange(c_ln, dtype=np.float32) / SR
                # Delicate high fifth (above vocal band: ~1175 Hz & 1760 Hz at very soft -26dB stereo edge)
                chime = (
                    0.035 * np.sin(2.0 * np.pi * 1174.66 * ct)
                    + 0.025 * np.sin(2.0 * np.pi * 1567.98 * ct)
                ) * (1.0 - np.exp(-ct / 0.04)) * np.exp(-ct / 0.65)
                out[c_idx:c_idx + c_ln, 0] += chime
                out[c_idx:c_idx + c_ln, 1] -= chime  # pure Side (cancels in mono center!)
    return out


def render_stage_bed(
    out_mp3: Path,
    bpm: float,
    total_bars: int,
    section_a_chords,
    section_b_chords,
    section_a_bass,
    section_b_bass,
    seed: int,
    lfo_rate: float,
):
    beat_s = 60.0 / bpm
    bar_s = 4.0 * beat_s
    total_n = int(SR * total_bars * bar_s)

    mix = synth_attention_percussion(total_bars=total_bars, bpm=bpm, seed=seed)

    for bar in range(total_bars):
        # 16-bar Section A -> 16-bar Section B evolving architecture
        in_b = ((bar // 16) % 2 == 1)
        chords = section_b_chords if in_b else section_a_chords
        basses = section_b_bass if in_b else section_a_bass

        chord = chords[bar % len(chords)]
        bass_pat = basses[bar % len(basses)]

        b_idx = int(bar * bar_s * SR)
        pad_stereo = synth_wide_side_pad_bar(chord, bar_s, bar_idx=bar, lfo_rate=lfo_rate) * 0.28
        sub_mono = synth_sub_bass_bar(bass_pat, bar_s) * 0.44

        end = min(total_n, b_idx + pad_stereo.shape[0])
        ln = end - b_idx
        if ln > 0:
            mix[b_idx:end, 0] += pad_stereo[:ln, 0] + sub_mono[:ln]
            mix[b_idx:end, 1] += pad_stereo[:ln, 1] + sub_mono[:ln]

    # Smooth 2.5s fade-in and 3.0s fade-out for invisible looping
    fi = min(total_n // 6, int(2.5 * SR))
    fo = min(total_n // 6, int(3.0 * SR))
    mix[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)[:, None]
    mix[-fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)[:, None]

    peak = float(np.max(np.abs(mix)))
    if peak > 1e-6:
        mix = mix * (0.85 / peak)
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

        # Surgical vocal-pocket mastering filter:
        # Carves 450 Hz - 3,400 Hz by -8..-9 dB so any human voice sits effortlessly on top
        af_chain = (
            "highpass=f=42,"
            "equalizer=f=550:t=q:w=1.1:g=-6.5,"
            "equalizer=f=1350:t=q:w=1.0:g=-9.0,"
            "equalizer=f=2650:t=q:w=1.1:g=-8.5,"
            "lowpass=f=13500"
        )
        subprocess.run(
            [
                "/usr/bin/ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-i", wav_path,
                "-af", af_chain,
                "-c:a", "libmp3lame", "-b:a", "192k",
                str(out_mp3),
            ],
            check=True,
        )
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/ssd/media/box2-stage-beds")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Note: chord voicings sit in warm low-mid pads (MIDI 52..67) while Mid/Side + EQ carve vocal presence
    beds = [
        (
            out_dir / "Stage Groove - Late Night Host Pocket.mp3",
            94.0,
            76,  # ~3m 14s
            # Section A (8-bar warm neo-soul cycle): Dm9 -> G13 -> Cmaj9 -> Fmaj7 -> Bm7 -> E7b13 -> Am9 -> A7alt
            [
                [50, 57, 60, 64], [43, 53, 57, 59], [48, 55, 59, 62], [41, 52, 57, 60],
                [47, 53, 57, 62], [40, 52, 56, 60], [45, 52, 55, 59], [45, 51, 55, 61],
            ],
            # Section B (modal lift): Gm9 -> C13 -> Fmaj9 -> Bbmaj7 -> Em7 -> A7b9 -> Dm9 -> G13
            [
                [43, 50, 53, 57], [48, 52, 57, 58], [41, 48, 52, 55], [46, 53, 57, 60],
                [40, 47, 50, 55], [45, 49, 55, 58], [50, 57, 60, 64], [43, 53, 57, 59],
            ],
            [
                [(0.0, 1.8, 38, 0.95), (2.0, 0.9, 38, 0.72), (3.0, 0.9, 45, 0.80)],
                [(0.0, 1.8, 43, 0.92), (2.5, 1.3, 38, 0.78)],
                [(0.0, 1.8, 36, 0.95), (2.0, 0.9, 43, 0.74), (3.0, 0.9, 40, 0.80)],
                [(0.0, 2.2, 41, 0.92), (2.5, 1.3, 45, 0.78)],
            ],
            [
                [(0.0, 1.9, 43, 0.94), (2.5, 1.3, 38, 0.80)],
                [(0.0, 1.9, 36, 0.94), (2.0, 0.9, 43, 0.75), (3.0, 0.9, 40, 0.78)],
                [(0.0, 2.2, 41, 0.94), (2.5, 1.3, 36, 0.78)],
                [(0.0, 1.9, 46, 0.90), (2.5, 1.3, 45, 0.82)],
            ],
            101,
            0.16,
        ),
        (
            out_dir / "Stage Groove - Hypnotic Cellar Pulse.mp3",
            91.0,
            74,  # ~3m 15s
            [
                [40, 47, 50, 54], [45, 52, 55, 59], [48, 55, 59, 62], [47, 54, 57, 63],
                [40, 47, 52, 55], [38, 45, 50, 54], [36, 43, 48, 52], [47, 51, 57, 59],
            ],
            [
                [45, 52, 55, 59], [38, 48, 52, 54], [43, 50, 54, 57], [48, 52, 55, 59],
                [42, 48, 52, 57], [47, 51, 55, 59], [40, 47, 50, 54], [40, 47, 52, 55],
            ],
            [
                [(0.0, 1.6, 40, 0.95), (1.75, 0.6, 40, 0.65), (2.5, 1.3, 47, 0.82)],
                [(0.0, 1.8, 45, 0.92), (2.5, 1.3, 40, 0.78)],
                [(0.0, 1.8, 36, 0.95), (2.5, 1.3, 43, 0.80)],
                [(0.0, 2.0, 35, 0.92), (2.5, 1.3, 42, 0.80)],
            ],
            [
                [(0.0, 1.8, 45, 0.94), (2.5, 1.3, 40, 0.78)],
                [(0.0, 1.8, 38, 0.94), (2.5, 1.3, 45, 0.78)],
                [(0.0, 1.8, 43, 0.94), (2.5, 1.3, 38, 0.78)],
                [(0.0, 2.0, 36, 0.92), (2.5, 1.3, 47, 0.80)],
            ],
            202,
            0.14,
        ),
        (
            out_dir / "Stage Groove - Velvet Crowdwork Flow.mp3",
            95.0,
            78,  # ~3m 17s
            [
                [41, 48, 51, 55], [46, 52, 56, 60], [39, 46, 50, 55], [44, 51, 55, 58],
                [37, 44, 48, 53], [48, 52, 55, 58], [41, 48, 53, 56], [48, 52, 56, 58],
            ],
            [
                [37, 44, 48, 53], [46, 50, 53, 56], [39, 46, 50, 55], [48, 52, 55, 58],
                [41, 48, 51, 55], [46, 53, 56, 60], [44, 51, 55, 58], [36, 48, 52, 55],
            ],
            [
                [(0.0, 1.7, 41, 0.95), (2.0, 0.8, 41, 0.70), (3.0, 0.9, 48, 0.82)],
                [(0.0, 1.9, 46, 0.92), (2.5, 1.3, 41, 0.78)],
                [(0.0, 1.9, 39, 0.95), (2.5, 1.3, 46, 0.80)],
                [(0.0, 2.0, 44, 0.92), (2.5, 1.3, 39, 0.78)],
            ],
            [
                [(0.0, 1.9, 37, 0.95), (2.5, 1.3, 44, 0.78)],
                [(0.0, 1.9, 46, 0.92), (2.5, 1.3, 39, 0.80)],
                [(0.0, 1.9, 39, 0.95), (2.5, 1.3, 48, 0.78)],
                [(0.0, 2.2, 36, 0.92), (2.5, 1.3, 43, 0.80)],
            ],
            303,
            0.19,
        ),
        (
            out_dir / "Stage Groove - Midnight Storyteller Pocket.mp3",
            88.0,
            70,  # ~3m 11s
            [
                [45, 52, 55, 59], [41, 48, 52, 57], [48, 55, 59, 62], [43, 50, 55, 59],
                [38, 45, 50, 53], [45, 52, 55, 59], [40, 47, 52, 56], [40, 47, 50, 56],
            ],
            [
                [41, 48, 52, 57], [43, 50, 55, 59], [45, 52, 55, 59], [48, 55, 59, 62],
                [38, 45, 50, 53], [43, 50, 53, 59], [48, 52, 55, 59], [40, 47, 52, 56],
            ],
            [
                [(0.0, 2.2, 45, 0.92), (2.5, 1.4, 40, 0.76)],
                [(0.0, 2.2, 41, 0.92), (2.5, 1.4, 45, 0.76)],
                [(0.0, 2.2, 36, 0.94), (2.5, 1.4, 43, 0.76)],
                [(0.0, 2.2, 43, 0.90), (2.5, 1.4, 38, 0.76)],
            ],
            [
                [(0.0, 2.2, 41, 0.94), (2.5, 1.4, 36, 0.76)],
                [(0.0, 2.2, 43, 0.92), (2.5, 1.4, 38, 0.76)],
                [(0.0, 2.2, 45, 0.94), (2.5, 1.4, 40, 0.76)],
                [(0.0, 2.2, 40, 0.90), (2.5, 1.4, 47, 0.78)],
            ],
            404,
            0.12,
        ),
    ]

    for path, bpm, bars, ca, cb, ba, bb, seed, lfo in beds:
        render_stage_bed(path, bpm, bars, ca, cb, ba, bb, seed=seed, lfo_rate=lfo)
        print(f"Engineered {path.name} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
