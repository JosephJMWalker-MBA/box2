"""Synthetic 1080p30 Framing and H.264 Software Encoding Benchmark for Jetson Orin Nano.

Evaluates whether the NVIDIA Jetson Orin Nano 8GB can sustain:
1. Portable Stage Director framing math (geometry, windowing, smoothing) per frame.
2. Software H.264 video encoding at 1080p30 (presets: ultrafast, veryfast, faster).
3. Real-time broadcast latency without dropped frames or thermal throttling.

Offline only: Uses synthetic test signals and drains to null; does not connect
to live cameras, production RTSP, OBS, Twitch, or booking services.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


def read_sysfs_file(path: str) -> Optional[str]:
    """Read a single line from sysfs/procfs safely."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def get_thermals() -> Dict[str, float]:
    """Read temperatures (°C) from all available hardware thermal zones."""
    thermals: Dict[str, float] = {}
    base = "/sys/class/thermal"
    if not os.path.exists(base):
        return thermals

    for name in os.listdir(base):
        if name.startswith("thermal_zone"):
            tz_dir = os.path.join(base, name)
            t_type = read_sysfs_file(os.path.join(tz_dir, "type")) or name
            t_temp = read_sysfs_file(os.path.join(tz_dir, "temp"))
            if t_temp:
                try:
                    thermals[t_type] = round(float(t_temp) / 1000.0, 1)
                except ValueError:
                    pass
    return thermals


def get_cpu_frequencies_mhz() -> Dict[str, int]:
    """Read current clock frequencies (MHz) for all CPU cores."""
    freqs: Dict[str, int] = {}
    cpu_base = "/sys/devices/system/cpu"
    if not os.path.exists(cpu_base):
        return freqs

    for cpu in sorted(os.listdir(cpu_base)):
        if re.match(r"^cpu[0-9]+$", cpu):
            freq_path = os.path.join(cpu_base, cpu, "cpufreq", "scaling_cur_freq")
            val = read_sysfs_file(freq_path)
            if val:
                try:
                    freqs[cpu] = int(val) // 1000
                except ValueError:
                    pass
    return freqs


def get_memory_info_mb() -> Dict[str, float]:
    """Read total and available memory in MB from /proc/meminfo."""
    mem: Dict[str, float] = {}
    raw = read_sysfs_file("/proc/meminfo")
    if not raw:
        return mem

    for line in raw.splitlines():
        parts = line.split(":")
        if len(parts) == 2:
            key = parts[0].strip()
            if key in ("MemTotal", "MemFree", "MemAvailable", "SwapTotal", "SwapFree"):
                val_kb = parts[1].strip().split()[0]
                try:
                    mem[key] = round(float(val_kb) / 1024.0, 1)
                except ValueError:
                    pass
    return mem


def get_gpu_load_percent() -> float:
    """Read Tegra GPU load percentage."""
    load = read_sysfs_file("/sys/devices/platform/17000000.gpu/load")
    if load is not None:
        try:
            return round(float(load) / 10.0, 1)  # scaled to 0-100%
        except ValueError:
            pass
    return 0.0


def benchmark_stage_director_math(iterations: int = 1800) -> Dict[str, Any]:
    """Benchmark pure Stage Director framing and tracking math on Jetson CPU."""
    # Portable inline simulation of Stage Director framing update
    # (Matches stage_director.framing and geometry logic without external dependencies)
    start_time = time.perf_counter()

    # Synthetic performer trajectory (cosine pacing)
    center_x = 1920.0
    center_y = 1080.0
    width = 3840.0
    height = 2160.0
    tau = 0.25
    dt = 1.0 / 30.0

    cur_cx = center_x
    cur_cy = center_y
    cur_w = width
    cur_h = height

    for i in range(iterations):
        t = i * dt
        # Performer face moves across stage
        face_x = 1920.0 + 400.0 * (1.0 if (i // 150) % 2 == 0 else -1.0)
        face_y = 900.0
        face_h = 300.0
        face_w = 240.0

        target_h = face_h / 0.20
        target_w = target_h * (16.0 / 9.0)
        target_cx = face_x
        target_cy = face_y + (0.5 - 0.33) * target_h

        # Exponential smoothing filter
        alpha = dt / (tau + dt)
        cur_cx += (target_cx - cur_cx) * alpha
        cur_cy += (target_cy - cur_cy) * alpha
        cur_w += (target_w - cur_w) * alpha
        cur_h = cur_w * (9.0 / 16.0)

    total_time = time.perf_counter() - start_time
    avg_per_frame_us = (total_time / iterations) * 1_000_000.0

    return {
        "iterations": iterations,
        "total_elapsed_s": round(total_time, 4),
        "avg_frame_latency_us": round(avg_per_frame_us, 2),
        "throughput_fps": round(iterations / total_time, 1),
    }


def benchmark_ffmpeg_encoding(
    duration_s: int = 30,
    preset: str = "ultrafast",
    bitrate_kbps: int = 4500,
    realtime: bool = True,
) -> Dict[str, Any]:
    """Run an isolated synthetic 1080p30 H.264 encoding benchmark with telemetry sampling."""
    fps_target = 30
    total_expected_frames = duration_s * fps_target

    # Build synthetic test pattern ffmpeg command
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info"]
    if realtime:
        cmd.append("-re")

    cmd.extend([
        "-f", "lavfi",
        "-i", f"testsrc=size=1920x1080:rate={fps_target}",
        "-t", str(duration_s),
        "-c:v", "libx264",
        "-preset", preset,
        "-tune", "zerolatency",
        "-b:v", f"{bitrate_kbps}k",
        "-maxrate", f"{bitrate_kbps}k",
        "-bufsize", f"{bitrate_kbps * 2}k",
        "-pix_fmt", "yuv420p",
        "-f", "null",
        "-",
    ])

    telemetry_samples: List[Dict[str, Any]] = []
    initial_thermals = get_thermals()
    initial_mem = get_memory_info_mb()

    start_time = time.perf_counter()
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)

    # Monitor hardware telemetry during execution
    while proc.poll() is None:
        sample_time = time.perf_counter() - start_time
        thermals = get_thermals()
        freqs = get_cpu_frequencies_mhz()
        mem = get_memory_info_mb()
        gpu_load = get_gpu_load_percent()

        telemetry_samples.append({
            "elapsed_s": round(sample_time, 2),
            "cpu_thermal_c": thermals.get("cpu-thermal", 0.0),
            "gpu_thermal_c": thermals.get("gpu-thermal", 0.0),
            "tj_thermal_c": thermals.get("tj-thermal", 0.0),
            "cpu_freqs_mhz": freqs,
            "gpu_load_pct": gpu_load,
            "mem_available_mb": mem.get("MemAvailable", 0.0),
        })
        time.sleep(1.0)

    _, stderr_text = proc.communicate()
    total_elapsed = time.perf_counter() - start_time
    final_thermals = get_thermals()

    # Parse final ffmpeg output for frames and encoding speed
    # e.g.: "frame=  900 fps= 30 q=... time=00:00:30.00 ... speed=   1x"
    match_frame = re.search(r"frame=\s*(\d+)", stderr_text)
    match_fps = re.search(r"fps=\s*([\d.]+)", stderr_text)
    match_speed = re.search(r"speed=\s*([\d.]+)x", stderr_text)

    frames_encoded = int(match_frame.group(1)) if match_frame else 0
    reported_fps = float(match_fps.group(1)) if match_fps else (frames_encoded / total_elapsed if total_elapsed > 0 else 0.0)
    reported_speed = float(match_speed.group(1)) if match_speed else round(reported_fps / fps_target, 2)

    # Calculate thermal rise
    cpu_temp_start = initial_thermals.get("cpu-thermal", 0.0)
    cpu_temp_max = max([s["cpu_thermal_c"] for s in telemetry_samples] or [cpu_temp_start])
    temp_rise_c = round(cpu_temp_max - cpu_temp_start, 1)

    # Detect throttling: check if min frequency is significantly below nominal
    all_freqs: List[int] = []
    for s in telemetry_samples:
        all_freqs.extend(s.get("cpu_freqs_mhz", {}).values())
    min_freq_mhz = min(all_freqs) if all_freqs else 0
    max_freq_mhz = max(all_freqs) if all_freqs else 0

    dropped_frames = max(0, total_expected_frames - frames_encoded)

    return {
        "preset": preset,
        "target_resolution": "1920x1080",
        "target_fps": fps_target,
        "target_bitrate_kbps": bitrate_kbps,
        "test_duration_s": duration_s,
        "realtime_paced": realtime,
        "actual_elapsed_s": round(total_elapsed, 2),
        "frames_encoded": frames_encoded,
        "expected_frames": total_expected_frames,
        "dropped_frames": dropped_frames,
        "sustained_fps": round(reported_fps, 2),
        "speed_ratio": reported_speed,
        "realtime_sustained": (reported_speed >= 0.98 and dropped_frames == 0),
        "thermal_start_c": cpu_temp_start,
        "thermal_peak_c": cpu_temp_max,
        "thermal_rise_c": temp_rise_c,
        "cpu_freq_range_mhz": (min_freq_mhz, max_freq_mhz),
        "throttled": (cpu_temp_max > 85.0 or (min_freq_mhz < 500 and min_freq_mhz > 0)),
        "samples_count": len(telemetry_samples),
    }


def run_full_jetson_benchmark(duration_s: int = 15) -> Dict[str, Any]:
    """Execute complete Jetson Orin Nano framing and encoding benchmark suite."""
    print("=" * 65)
    print("BOX2 JETSON ORIN NANO 8GB: SYNTHETIC BROADCAST BENCHMARK")
    print("=" * 65)

    # 1. System Inventory
    mem = get_memory_info_mb()
    thermals = get_thermals()
    freqs = get_cpu_frequencies_mhz()

    system_info = {
        "model": read_sysfs_file("/proc/device-tree/model") or "NVIDIA Jetson Orin Nano",
        "tegra_release": read_sysfs_file("/etc/nv_tegra_release") or "unknown",
        "total_memory_mb": mem.get("MemTotal", 0.0),
        "available_memory_mb": mem.get("MemAvailable", 0.0),
        "cpu_cores": len(freqs),
        "initial_temp_c": thermals.get("cpu-thermal", 0.0),
    }
    print(f"Hardware: {system_info['model']}")
    print(f"Memory:   {system_info['available_memory_mb']} MB available / {system_info['total_memory_mb']} MB total")
    print(f"CPU:      {system_info['cpu_cores']} cores active | Initial temp: {system_info['initial_temp_c']}°C\n")

    # 2. Stage Director Framing Math Benchmark
    print("--- 1. Stage Director Framing & Tracking Math ---")
    math_results = benchmark_stage_director_math(iterations=1800)
    print(f"Iterations:          {math_results['iterations']} frames (60s equivalent @ 30 FPS)")
    print(f"Total time:          {math_results['total_elapsed_s']} s")
    print(f"Frame latency:       {math_results['avg_frame_latency_us']} µs per frame")
    print(f"Throughput:          {math_results['throughput_fps']} FPS (math only)\n")

    # 3. H.264 Software Encoding Benchmarks across presets
    encoding_results = []
    presets_to_test = ["ultrafast", "veryfast", "faster"]

    print("--- 2. Synthetic 1080p30 H.264 Software Encoding ---")
    for preset in presets_to_test:
        print(f"Testing preset '{preset}' (duration={duration_s}s, target=30 FPS)...", end="", flush=True)
        res = benchmark_ffmpeg_encoding(duration_s=duration_s, preset=preset, bitrate_kbps=4500, realtime=True)
        encoding_results.append(res)
        status_str = "SUSTAINED" if res["realtime_sustained"] else "DROPPED/LAG"
        print(f" -> {status_str}: {res['sustained_fps']} FPS (speed {res['speed_ratio']}x, peak {res['thermal_peak_c']}°C)")

    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system_info": system_info,
        "math_benchmark": math_results,
        "encoding_benchmarks": encoding_results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jetson Orin Nano broadcast benchmark")
    parser.add_argument("--duration", type=int, default=15, help="Test duration in seconds per preset (default: 15)")
    args = parser.parse_args()

    full_results = run_full_jetson_benchmark(duration_s=args.duration)
    output_path = "jetson_benchmark_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2)
    print(f"\nBenchmark completed. Results written to {output_path}")
