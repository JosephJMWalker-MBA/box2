#!/usr/bin/env python3
"""BOX 2 On-Device Live Stand-Up Caption Engine, Overlay & SRT Clip Exporter.

Transcribes the isolated pre-music stage microphone feed in real time on Jetson Orin Nano
using `faster-whisper` (`base.en` int8 on `/mnt/ssd/models/box2-asr`), renders big punchy
stand-up comedy captions at bottom-center with active-phrase Stage Gold highlighting
(auto-fading after 2.5s of silence), logs timestamped utterances to `/mnt/ssd/box2-clips/captions.jsonl`,
and exports matching `.srt` sidecar files whenever clips are saved.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import List, Optional, Sequence, Tuple

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    np = None
    HAS_NUMPY = False

try:
    import cv2
    HAS_CV2 = True
except Exception:
    cv2 = None
    HAS_CV2 = False

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception:
    Image = ImageDraw = ImageFont = None
    HAS_PIL = False

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except Exception:
    WhisperModel = None
    HAS_WHISPER = False


DEFAULT_ASR_MODEL_DIR = Path("/mnt/ssd/models/box2-asr")
DEFAULT_CAPTIONS_LOG = Path("/mnt/ssd/box2-clips/captions.jsonl")

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

HALLUCINATION_EXACT = frozenset({
    "",
    "you",
    "you.",
    "yeah",
    "yeah.",
    "thank you",
    "thank you.",
    "thank you!",
    "thanks for watching",
    "thanks for watching.",
    "thanks for watching!",
    "thank you for watching",
    "thank you for watching.",
    "thank you for watching!",
    "please subscribe",
    "please subscribe.",
    "bye",
    "bye.",
    "bye-bye.",
    "okay.",
    "oh.",
    "uh",
    "um",
})

HALLUCINATION_SUBSTRINGS = (
    "subtitles by",
    "captioned by",
    "amara.org",
    "transcribed by",
    "thank you for watching",
    "thanks for watching",
    "like and subscribe",
    "www.",
    "http://",
    "https://",
)


@dataclass
class CaptionSnapshot:
    text: str = ""
    updated_mono: float = 0.0
    last_speech_mono: float = 0.0
    is_final: bool = False
    utterance_id: int = 0


def clean_caption_text(raw_text: str) -> str:
    """Clean raw ASR text while preserving punchy stand-up punctuation and contractions."""
    if not raw_text:
        return ""
    text = str(raw_text).strip()
    # Strip bracketed non-speech tags like [Music], (Laughter), *cough*
    text = re.sub(r"\[[^\]]*\]|\([^\)]*\)|\*[^\*]*\*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_whisper_hallucination(text: str) -> bool:
    """Return True if `text` matches known Whisper silence/noise hallucinations or loops."""
    cleaned = clean_caption_text(text)
    if len(cleaned) < 2:
        return True
    low = cleaned.lower().strip(" .,!?-\"'")
    if not low or low in HALLUCINATION_EXACT or cleaned.lower() in HALLUCINATION_EXACT:
        return True
    low_full = cleaned.lower()
    if any(sub in low_full for sub in HALLUCINATION_SUBSTRINGS):
        return True
    # Reject degenerate single-word / short-phrase repetition loops ("Yeah. Yeah. Yeah. Yeah.")
    words = [re.sub(r"[^a-z0-9']+", "", w.lower()) for w in cleaned.split()]
    words = [w for w in words if w]
    if not words:
        return True
    if len(words) >= 5 and len(set(words)) == 1:
        return True
    if len(words) >= 8 and len(set(words)) <= 2:
        return True
    return False


def layout_standup_lines(
    text: str,
    max_words_visible: int = 12,
    max_chars_per_line: int = 34,
    active_tail_words: int = 3,
) -> Tuple[List[List[Tuple[str, bool]]], str]:
    """Format caption text into at most 2 punchy bottom-center stand-up lines.

    Returns `(lines, visible_plain_text)` where each line is a list of `(word_str, is_highlighted)`.
    Only the latest `max_words_visible` words are shown so long monologues stay big and crisp,
    with the newest `active_tail_words` highlighted in Stage Gold.
    """
    cleaned = clean_caption_text(text)
    if not cleaned:
        return [], ""
    tokens = cleaned.split()
    if len(tokens) > max_words_visible:
        tokens = tokens[-max_words_visible:]

    n = len(tokens)
    hi_start = max(0, n - max(1, int(active_tail_words)))
    tagged = [(tok, idx >= hi_start) for idx, tok in enumerate(tokens)]

    # Fit into 1 line if short enough; otherwise split into 2 balanced lines
    joined = " ".join(tokens)
    if len(joined) <= max_chars_per_line or len(tagged) <= 4:
        return [tagged], joined

    # Find split point closest to half character length while respecting max_chars_per_line
    best_split = max(1, len(tagged) // 2)
    best_score = 1e9
    total_chars = len(joined)
    for split_idx in range(1, len(tagged)):
        l1 = " ".join(w for w, _ in tagged[:split_idx])
        l2 = " ".join(w for w, _ in tagged[split_idx:])
        overflow = max(0, len(l1) - max_chars_per_line) * 4 + max(0, len(l2) - max_chars_per_line) * 4
        imbalance = abs(len(l1) - (total_chars * 0.48))
        score = overflow + imbalance
        if score < best_score:
            best_score = score
            best_split = split_idx

    line1 = tagged[:best_split]
    line2 = tagged[best_split:]
    return [line1, line2], joined


def format_srt_timestamp(seconds: float) -> str:
    """Format non-negative offset in seconds as standard SubRip `HH:MM:SS,mmm`."""
    ms_total = max(0, int(round(float(seconds) * 1000.0)))
    hrs = ms_total // 3_600_000
    rem = ms_total % 3_600_000
    mins = rem // 60_000
    rem = rem % 60_000
    secs = rem // 1000
    ms = rem % 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def build_srt_content(entries: Sequence[dict], clip_start_epoch: float = 0.0, clip_duration_s: Optional[float] = None) -> str:
    """Convert timestamped caption dicts (`start_epoch`, `end_epoch`, `text`) into SubRip `.srt` text."""
    blocks = []
    idx = 1
    for item in entries:
        txt = clean_caption_text(item.get("text", ""))
        if not txt:
            continue
        raw_s = float(item.get("start_epoch", 0.0)) - float(clip_start_epoch)
        raw_e = float(item.get("end_epoch", raw_s + 2.0)) - float(clip_start_epoch)
        if clip_duration_s is not None and raw_s >= clip_duration_s:
            continue
        if raw_e <= 0.05:
            continue
        s_rel = max(0.0, raw_s)
        e_rel = max(s_rel + 0.60, raw_e)
        if clip_duration_s is not None:
            e_rel = min(float(clip_duration_s), e_rel)
            if e_rel <= s_rel + 0.15:
                e_rel = min(float(clip_duration_s), s_rel + 0.60)
        lines, _ = layout_standup_lines(txt, max_words_visible=18, max_chars_per_line=42, active_tail_words=0)
        formatted_txt = "\n".join(" ".join(w for w, _ in ln) for ln in lines) if lines else txt
        blocks.append(f"{idx}\n{format_srt_timestamp(s_rel)} --> {format_srt_timestamp(e_rel)}\n{formatted_txt}\n")
        idx += 1
    return "\n".join(blocks)


def append_caption_log(log_path: Path, start_epoch: float, end_epoch: float, text: str, max_age_hours: float = 24.0) -> None:
    """Append finalized utterance to `captions.jsonl` and periodically prune entries older than `max_age_hours`."""
    cleaned = clean_caption_text(text)
    if not cleaned:
        return
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "start_epoch": round(float(start_epoch), 3),
        "end_epoch": round(max(float(start_epoch) + 0.4, float(end_epoch)), 3),
        "text": cleaned,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Lightweight periodic prune (~1 in 64 writes) so captions.jsonl stays compact over multi-day marathons
    if int(rec["end_epoch"] * 10) % 64 == 0:
        cutoff = time.time() - max_age_hours * 3600.0
        try:
            kept = []
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                if float(obj.get("end_epoch", 0.0)) >= cutoff:
                    kept.append(json.dumps(obj, ensure_ascii=False))
            tmp = p.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            tmp.replace(p)
        except Exception:
            pass


def load_captions_in_window(log_path: Path, start_epoch: float, end_epoch: float) -> List[dict]:
    """Read finalized utterances overlapping `[start_epoch, end_epoch]` from `captions.jsonl`."""
    p = Path(log_path)
    if not p.exists():
        return []
    matches = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            s_ts = float(obj.get("start_epoch", 0.0))
            e_ts = float(obj.get("end_epoch", 0.0))
            if e_ts >= float(start_epoch) and s_ts <= float(end_epoch):
                matches.append(obj)
    except Exception:
        pass
    matches.sort(key=lambda x: float(x.get("start_epoch", 0.0)))
    return matches


def normalize_for_asr(samples_16k: "np.ndarray") -> Tuple["np.ndarray", float, float]:
    """Normalize quiet distant stage-mic speech (`peak ~0.04-0.08`) into Whisper's optimal amplitude range."""
    if samples_16k.size == 0:
        return samples_16k, -100.0, 0.0
    rms = float(np.sqrt(np.mean(np.square(samples_16k, dtype=np.float64))))
    rms_db = 20.0 * math.log10(max(rms, 1e-6))
    p98 = float(np.percentile(np.abs(samples_16k), 98.5))
    peak = float(np.max(np.abs(samples_16k)))
    if peak < 0.006 or rms_db < -58.0:
        return samples_16k, rms_db, peak
    ref = max(p98, peak * 0.7, 0.015)
    gain = min(14.0, max(1.0, 0.62 / ref))
    return np.clip(samples_16k * gain, -1.0, 1.0).astype(np.float32), rms_db, peak


def transcribe_media_to_srt(
    media_path: str | Path,
    srt_path: Optional[str | Path] = None,
    model_name: str = "base.en",
    model_dir: Path = DEFAULT_ASR_MODEL_DIR,
    ffmpeg_bin: str = "/usr/bin/ffmpeg",
) -> Optional[Path]:
    """Offline/clip fallback: transcribe an `.mp4`/audio file directly to `.srt` using `faster-whisper`."""
    if not HAS_WHISPER or not HAS_NUMPY:
        return None
    src = Path(media_path)
    if not src.exists():
        return None
    out_srt = Path(srt_path) if srt_path else src.with_suffix(".srt")
    ff = ffmpeg_bin if os.path.exists(ffmpeg_bin) else "ffmpeg"
    raw = subprocess.check_output(
        [ff, "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
        timeout=180,
    )
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size < 8000:
        out_srt.write_text("", encoding="utf-8")
        return out_srt

    # Normalize in 30s windows so quiet sets and loud laughs both transcribe cleanly
    win = 16000 * 30
    audio_norm = np.empty_like(audio)
    for start in range(0, audio.size, win):
        chunk = audio[start:start + win]
        norm_c, _, _ = normalize_for_asr(chunk)
        audio_norm[start:start + win] = norm_c

    Path(model_dir).mkdir(parents=True, exist_ok=True)
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=3, download_root=str(model_dir))
    segments, _ = model.transcribe(
        audio_norm,
        language="en",
        beam_size=1,
        best_of=1,
        temperature=0.0,
        vad_filter=True,
        vad_parameters={"threshold": 0.28, "min_silence_duration_ms": 320},
        condition_on_previous_text=False,
    )
    entries = []
    for seg in segments:
        if getattr(seg, "no_speech_prob", 0.0) >= 0.62 or getattr(seg, "avg_logprob", 0.0) <= -1.25:
            continue
        txt = clean_caption_text(seg.text)
        if txt and not is_whisper_hallucination(txt):
            entries.append({"start_epoch": float(seg.start), "end_epoch": float(seg.end), "text": txt})
    srt_text = build_srt_content(entries, clip_start_epoch=0.0)
    out_srt.write_text(srt_text, encoding="utf-8")
    return out_srt


def export_srt_for_clip(
    mp4_path: str | Path,
    clip_start_epoch: float,
    clip_end_epoch: float,
    captions_log: Path = DEFAULT_CAPTIONS_LOG,
    auto_transcribe_max_seconds: float = 900.0,
) -> Optional[Path]:
    """Write a matching `.srt` file beside `mp4_path` from live `captions.jsonl` (or fallback Whisper pass)."""
    mp4_p = Path(mp4_path)
    srt_p = mp4_p.with_suffix(".srt")
    dur = max(1.0, float(clip_end_epoch) - float(clip_start_epoch))
    entries = load_captions_in_window(captions_log, clip_start_epoch, clip_end_epoch)
    if entries:
        srt_text = build_srt_content(entries, clip_start_epoch=clip_start_epoch, clip_duration_s=dur)
        srt_p.write_text(srt_text, encoding="utf-8")
        return srt_p

    # Fallback for clips recorded before live captions were active (up to 15m auto, or any length via CLI)
    if HAS_WHISPER and dur <= auto_transcribe_max_seconds and mp4_p.exists():
        try:
            return transcribe_media_to_srt(mp4_p, srt_path=srt_p)
        except Exception:
            return None
    return None


class LiveCaptionEngine:
    """Real-time background streaming transcriber fed by isolated pre-music stage microphone PCM."""

    SAMPLE_RATE = 16000

    def __init__(
        self,
        enabled: bool = True,
        model_name: str = "base.en",
        model_dir: Path = DEFAULT_ASR_MODEL_DIR,
        captions_log: Path = DEFAULT_CAPTIONS_LOG,
        step_interval_s: float = 0.55,
        pause_commit_s: float = 0.90,
        max_utterance_s: float = 6.0,
        speech_rms_dbfs: float = -48.0,
    ):
        self.enabled = bool(enabled)
        self.model_name = str(model_name)
        self.model_dir = Path(model_dir)
        self.captions_log = Path(captions_log)
        self.step_interval_s = float(step_interval_s)
        self.pause_commit_s = float(pause_commit_s)
        self.max_utterance_s = float(max_utterance_s)
        self.speech_rms_dbfs = float(speech_rms_dbfs)

        self._lock = threading.Lock()
        self._in_chunks: collections.deque = collections.deque(maxlen=120)  # ~6s of 50ms chunks
        self._preroll: collections.deque = collections.deque(maxlen=7)      # 350ms pre-speech ring
        self._snapshot = CaptionSnapshot()
        self._utterance_seq = 0
        self._model = None
        self._model_ready = False
        self._model_error: Optional[str] = None
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._asr_loop, daemon=True)
        self._worker.start()

    def get_snapshot(self) -> CaptionSnapshot:
        with self._lock:
            return CaptionSnapshot(
                text=self._snapshot.text,
                updated_mono=self._snapshot.updated_mono,
                last_speech_mono=self._snapshot.last_speech_mono,
                is_final=self._snapshot.is_final,
                utterance_id=self._snapshot.utterance_id,
            )

    @property
    def stats(self) -> dict:
        snap = self.get_snapshot()
        return {
            "captions_enabled": bool(self.enabled),
            "captions_engine": f"faster-whisper ({self.model_name})" if self._model_ready else (
                "unavailable" if not HAS_WHISPER else "loading"
            ),
            "last_caption": snap.text,
        }

    def push_mic_pcm48_mono(self, mono_48k_f32: "np.ndarray", is_onstage: bool, now_epoch: Optional[float] = None) -> None:
        """Non-blocking (<0.02ms) 48kHz -> 16kHz decimation and enqueue from `BroadcastAudioMixer`."""
        if not self.enabled or not HAS_NUMPY or mono_48k_f32 is None or mono_48k_f32.size < 3:
            return
        if not is_onstage:
            return
        n3 = (mono_48k_f32.size // 3) * 3
        decimated = ((mono_48k_f32[:n3:3] + mono_48k_f32[1:n3:3] + mono_48k_f32[2:n3:3]) / 3.0).astype(np.float32)
        ts_epoch = float(now_epoch if now_epoch is not None else time.time())
        ts_mono = time.monotonic()
        with self._lock:
            self._in_chunks.append((decimated, ts_epoch, ts_mono))

    def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        if not HAS_WHISPER or self._model_error is not None:
            return False
        try:
            self.model_dir.mkdir(parents=True, exist_ok=True)
            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
                download_root=str(self.model_dir),
            )
            self._model_ready = True
            return True
        except Exception as exc:
            self._model_error = str(exc)
            return False

    def _run_whisper(self, pcm_16k: "np.ndarray") -> str:
        if not self._ensure_model() or pcm_16k.size < int(0.80 * self.SAMPLE_RATE):
            return ""
        norm_audio, rms_db, peak = normalize_for_asr(pcm_16k)
        if peak < 0.006 or rms_db < -58.0:
            return ""
        segments, _ = self._model.transcribe(
            norm_audio,
            language="en",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={"threshold": 0.28, "min_silence_duration_ms": 260},
            condition_on_previous_text=False,
        )
        parts = []
        for s in segments:
            if getattr(s, "no_speech_prob", 0.0) >= 0.60 or getattr(s, "avg_logprob", 0.0) <= -1.20:
                continue
            t = clean_caption_text(s.text)
            if t and not is_whisper_hallucination(t):
                parts.append(t)
        combined = clean_caption_text(" ".join(parts))
        if is_whisper_hallucination(combined):
            return ""
        return combined

    def _asr_loop(self) -> None:
        utt_samples: List["np.ndarray"] = []
        utt_total_len = 0
        utt_active = False
        utt_start_epoch = 0.0
        last_voice_epoch = 0.0
        last_voice_mono = 0.0
        last_decode_mono = 0.0

        while not self._stop_event.is_set():
            if not self.enabled or not HAS_NUMPY:
                utt_samples.clear()
                utt_total_len = 0
                utt_active = False
                time.sleep(0.25)
                continue

            # Lazy-load Whisper on background thread so video startup is instantaneous
            if self._model is None and HAS_WHISPER and self._model_error is None:
                self._ensure_model()

            drained = []
            with self._lock:
                while self._in_chunks:
                    drained.append(self._in_chunks.popleft())

            now_mono = time.monotonic()
            if not drained:
                # If performer stopped speaking or stepped off stage, commit pending utterance after pause_commit_s
                if utt_active and (now_mono - last_voice_mono) >= self.pause_commit_s:
                    full_pcm = np.concatenate(utt_samples) if utt_samples else np.zeros(0, dtype=np.float32)
                    final_txt = self._run_whisper(full_pcm)
                    if final_txt:
                        with self._lock:
                            self._snapshot = CaptionSnapshot(
                                text=final_txt,
                                updated_mono=time.monotonic(),
                                last_speech_mono=last_voice_mono,
                                is_final=True,
                                utterance_id=self._utterance_seq,
                            )
                        append_caption_log(self.captions_log, utt_start_epoch, last_voice_epoch, final_txt)
                    utt_samples.clear()
                    utt_total_len = 0
                    utt_active = False
                time.sleep(0.06)
                continue

            for chunk, c_epoch, c_mono in drained:
                rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64)))) if chunk.size else 0.0
                rms_db = 20.0 * math.log10(max(rms, 1e-6))
                peak = float(np.max(np.abs(chunk))) if chunk.size else 0.0
                is_voice = (rms_db >= self.speech_rms_dbfs) or (peak >= 0.014)

                if not utt_active:
                    if is_voice:
                        utt_active = True
                        self._utterance_seq += 1
                        pre_list = list(self._preroll)
                        utt_start_epoch = pre_list[0][1] if pre_list else (c_epoch - 0.05)
                        utt_samples = [p[0] for p in pre_list] + [chunk]
                        utt_total_len = sum(x.size for x in utt_samples)
                        self._preroll.clear()
                        last_voice_epoch = c_epoch
                        last_voice_mono = c_mono
                    else:
                        self._preroll.append((chunk, c_epoch, c_mono))
                else:
                    utt_samples.append(chunk)
                    utt_total_len += chunk.size
                    if is_voice:
                        last_voice_epoch = c_epoch
                        last_voice_mono = c_mono

            if not utt_active:
                continue

            now_mono = time.monotonic()
            utt_dur_s = utt_total_len / float(self.SAMPLE_RATE)
            silence_s = now_mono - last_voice_mono

            should_commit = (silence_s >= self.pause_commit_s) or (utt_dur_s >= self.max_utterance_s)
            should_partial = (not should_commit) and (utt_dur_s >= 1.15) and ((now_mono - last_decode_mono) >= self.step_interval_s)

            if should_commit or should_partial:
                full_pcm = np.concatenate(utt_samples)
                last_decode_mono = now_mono
                decoded = self._run_whisper(full_pcm)
                if decoded:
                    with self._lock:
                        self._snapshot = CaptionSnapshot(
                            text=decoded,
                            updated_mono=time.monotonic(),
                            last_speech_mono=last_voice_mono,
                            is_final=bool(should_commit),
                            utterance_id=self._utterance_seq,
                        )
                if should_commit:
                    if decoded:
                        append_caption_log(self.captions_log, utt_start_epoch, max(utt_start_epoch + 0.5, last_voice_epoch), decoded)
                    # Keep a tiny 150ms tail if force-committed mid-sentence so continuity across 6s boundary is seamless
                    if silence_s < 0.25 and full_pcm.size > int(0.15 * self.SAMPLE_RATE):
                        tail = full_pcm[-int(0.15 * self.SAMPLE_RATE):].copy()
                        self._preroll.clear()
                        self._preroll.append((tail, last_voice_epoch - 0.15, now_mono))
                    utt_samples.clear()
                    utt_total_len = 0
                    utt_active = False

    def stop(self) -> None:
        self._stop_event.set()


class LiveCaptionOverlay:
    """High-contrast stand-up clip caption renderer with cached RGBA sprites (<0.15ms/frame)."""

    def __init__(
        self,
        engine: LiveCaptionEngine,
        config_path: str = "/home/joseph1/box2-stream/ticker.json",
        state_path: str = "/home/joseph1/box2-stream/state.json",
        base_w: int = 1280,
        base_h: int = 720,
    ):
        self.engine = engine
        self.config_path = config_path
        self.state_path = state_path
        self.base_w = int(base_w)
        self.base_h = int(base_h)

        self.enabled = True
        self.font_size = int(round(38 * (self.base_h / 720.0)))
        self.fade_after_silence_s = 2.5
        self.fade_duration_s = 0.40
        self.bottom_margin = int(round(28 * (self.base_h / 720.0)))
        self.max_words_visible = 12
        self.max_chars_per_line = 34
        self.active_tail_words = 3

        self._last_cfg_check = 0.0
        self._font_cache: dict = {}
        self._sprite_key = None
        self._sprite_bgra: Optional["np.ndarray"] = None

    def _reload_config_if_needed(self, now_mono: float) -> None:
        if now_mono - self._last_cfg_check < 1.5:
            return
        self._last_cfg_check = now_mono
        enabled = True

        if self.config_path and os.path.exists(self.config_path):
            try:
                tk = json.loads(Path(self.config_path).read_text())
                lc = tk.get("live_captions", {})
                if isinstance(lc, dict):
                    if "enabled" in lc:
                        enabled = bool(lc["enabled"])
                    if "font_size" in lc:
                        self.font_size = max(20, min(68, int(lc["font_size"])))
                    if "fade_after_silence_s" in lc:
                        self.fade_after_silence_s = max(0.8, float(lc["fade_after_silence_s"]))
                    if "bottom_margin" in lc:
                        self.bottom_margin = max(12, int(lc["bottom_margin"]))
            except Exception:
                pass

        if self.state_path and os.path.exists(self.state_path):
            try:
                st = json.loads(Path(self.state_path).read_text())
                cc = st.get("captions", {})
                if isinstance(cc, dict) and "enabled" in cc:
                    enabled = bool(cc["enabled"])
            except Exception:
                pass

        self.enabled = enabled
        self.engine.enabled = enabled

    def _get_font(self, px_size: int):
        if not HAS_PIL:
            return None
        if px_size in self._font_cache:
            return self._font_cache[px_size]
        font = None
        for fp in FONT_CANDIDATES:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, px_size)
                    break
                except Exception:
                    continue
        if font is None:
            font = ImageFont.load_default()
        self._font_cache[px_size] = font
        return font

    def _render_sprite_bgra(self, lines: List[List[Tuple[str, bool]]]) -> Optional["np.ndarray"]:
        if not HAS_NUMPY or not lines:
            return None

        if HAS_PIL:
            font = self._get_font(self.font_size)
            stroke_w = max(3, int(round(self.font_size * 0.13)))
            space_w = int(round(self.font_size * 0.30))
            line_gap = int(round(self.font_size * 0.24))
            pad_x = int(round(self.font_size * 0.62))
            pad_y = int(round(self.font_size * 0.38))

            dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            ddraw = ImageDraw.Draw(dummy)

            measured_lines = []
            max_line_w = 0
            line_h = int(round(self.font_size * 1.18))
            for ln in lines:
                word_boxes = []
                cur_w = 0
                for idx, (word, is_hi) in enumerate(ln):
                    bbox = ddraw.textbbox((0, 0), word, font=font, stroke_width=stroke_w)
                    ww = max(1, bbox[2] - bbox[0])
                    wh = max(line_h, bbox[3] - bbox[1])
                    line_h = max(line_h, wh)
                    word_boxes.append((word, is_hi, ww))
                    cur_w += ww + (space_w if idx < len(ln) - 1 else 0)
                max_line_w = max(max_line_w, cur_w)
                measured_lines.append((word_boxes, cur_w))

            box_w = min(self.base_w - 40, max_line_w + pad_x * 2)
            box_h = len(measured_lines) * line_h + max(0, len(measured_lines) - 1) * line_gap + pad_y * 2

            img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Translucent dark stand-up pill + subtle top Stage Gold accent border
            radius = max(10, int(round(self.font_size * 0.36)))
            draw.rounded_rectangle(
                [(0, 0), (box_w - 1, box_h - 1)],
                radius=radius,
                fill=(10, 10, 14, 158),
                outline=(255, 212, 59, 92),
                width=1,
            )

            # Render centered words with heavy black outline + drop shadow + Stage Gold active highlight
            y_cursor = pad_y
            white_rgba = (255, 255, 255, 255)
            gold_rgba = (255, 214, 58, 255)
            shadow_rgba = (0, 0, 0, 210)
            stroke_rgba = (0, 0, 0, 255)

            for word_boxes, line_w in measured_lines:
                x_cursor = max(pad_x // 2, (box_w - line_w) // 2)
                for word, is_hi, ww in word_boxes:
                    fill_col = gold_rgba if is_hi else white_rgba
                    draw.text((x_cursor + 2, y_cursor + 3), word, font=font, fill=shadow_rgba, stroke_width=stroke_w, stroke_fill=shadow_rgba)
                    draw.text((x_cursor, y_cursor), word, font=font, fill=fill_col, stroke_width=stroke_w, stroke_fill=stroke_rgba)
                    x_cursor += ww + space_w
                y_cursor += line_h + line_gap

            rgba = np.array(img, dtype=np.uint8)
            # Convert RGBA -> BGRA for direct OpenCV BGR canvas compositing
            bgra = rgba[:, :, [2, 1, 0, 3]].copy()
            return bgra

        if HAS_CV2:
            # Minimal OpenCV fallback if Pillow is absent
            box_w, box_h = min(self.base_w - 80, 960), 110
            bgra = np.zeros((box_h, box_w, 4), dtype=np.uint8)
            bgra[:, :] = (14, 10, 10, 165)
            for idx, ln in enumerate(lines[:2]):
                s = " ".join(w for w, _ in ln)
                y = 44 + idx * 44
                cv2.putText(bgra, s, (24, y), cv2.FONT_HERSHEY_DUPLEX, 1.0, (0, 0, 0, 255), 5, cv2.LINE_AA)
                cv2.putText(bgra, s, (24, y), cv2.FONT_HERSHEY_DUPLEX, 1.0, (58, 214, 255, 255), 2, cv2.LINE_AA)
            return bgra

        return None

    def compute_opacity(self, snap: CaptionSnapshot, now_mono: float) -> float:
        if not snap.text or snap.last_speech_mono <= 0.0:
            return 0.0
        anchor = max(snap.last_speech_mono, snap.updated_mono - 0.35)
        age = max(0.0, float(now_mono) - anchor)
        if age <= self.fade_after_silence_s:
            return 1.0
        over = age - self.fade_after_silence_s
        if over >= self.fade_duration_s:
            return 0.0
        return 0.5 * (1.0 + math.cos(math.pi * (over / self.fade_duration_s)))

    def draw(self, canvas_bgr: "np.ndarray", is_performer_framed: bool, now_mono: Optional[float] = None) -> bool:
        """Composite live stand-up captions onto bottom-center of `canvas_bgr` when performer is onstage."""
        if not HAS_NUMPY or canvas_bgr is None:
            return False
        t_mono = float(now_mono if now_mono is not None else time.monotonic())
        self._reload_config_if_needed(t_mono)
        if not self.enabled or not is_performer_framed:
            return False

        snap = self.engine.get_snapshot()
        opacity = self.compute_opacity(snap, t_mono)
        if opacity <= 0.01:
            return False

        lines, _ = layout_standup_lines(
            snap.text,
            max_words_visible=self.max_words_visible,
            max_chars_per_line=self.max_chars_per_line,
            active_tail_words=self.active_tail_words,
        )
        if not lines:
            return False

        key = (tuple(tuple(ln) for ln in lines), self.font_size)
        if key != self._sprite_key or self._sprite_bgra is None:
            self._sprite_bgra = self._render_sprite_bgra(lines)
            self._sprite_key = key

        sp = self._sprite_bgra
        if sp is None:
            return False

        ch, cw = canvas_bgr.shape[:2]
        sh, sw = sp.shape[:2]
        if sw >= cw:
            sp = sp[:, :cw - 4]
            sh, sw = sp.shape[:2]
        if sh >= ch - 20:
            return False

        x0 = max(0, (cw - sw) // 2)
        y0 = max(0, ch - sh - self.bottom_margin)
        roi = canvas_bgr[y0:y0 + sh, x0:x0 + sw]

        alpha = (sp[:, :, 3:4].astype(np.float32) / 255.0) * float(opacity)
        fg_bgr = sp[:, :, :3].astype(np.float32)
        blended = roi.astype(np.float32) * (1.0 - alpha) + fg_bgr * alpha
        canvas_bgr[y0:y0 + sh, x0:x0 + sw] = blended.astype(np.uint8)
        return True
