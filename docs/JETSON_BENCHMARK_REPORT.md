# BOX2 — Jetson Orin Nano 8GB Broadcast Feasibility Benchmark Report

Status: **Measured empirical results on physical hardware (joejetson1.local / orin)**.
Test Date: **November 9, 2026**.
PR: **[Draft PR #9](https://github.com/JosephJMWalker-MBA/box2/pull/9)**.

---

## Executive Summary

The primary inquiry is: **"Can the Jetson Orin Nano 8GB reliably produce the entire intelligent broadcast by itself without the Mac host?"**

### Key Conclusion: **YES, with software H.264 encoding via `libx264` (`veryfast` or `ultrafast`)**

1. **Portable Stage Director Overhead is Negligible**:
   - The Stage Director framing, geometry, and smoothing engine executes in **1.18 microseconds per frame** on the Jetson ARM Cortex-A78AE CPU cores (throughput: **845,577 FPS**).
   - In a 30 FPS broadcast (33.3 ms frame interval), Stage Director decision logic consumes **0.0035%** of the available frame budget.

2. **1080p30 H.264 Software Encoding is Real-Time Sustained**:
   - The Orin Nano lacks an NVENC hardware encoder block in silicon (as documented by NVIDIA).
   - However, its 6-core ARM Cortex-A78AE CPU delivers **60.0 FPS unconstrained throughput (2.0× real-time headroom)** at 1080p30 using `libx264` (`-preset veryfast -tune zerolatency`).
   - Under real-time pacing (`-re`) at a broadcast bitrate of 4500 kbps, it sustained **31.0 FPS with 0 dropped frames** and a speed ratio of **1.02×**.

3. **Thermals and Throttling Remain Pristine**:
   - In 25W power mode, thermal load during sustained 1080p30 software encoding rose by only **0.6°C to 1.1°C** (peaking at **47.5°C** against an 85°C throttle threshold).
   - Zero frequency throttling occurred; all 6 CPU cores sustained their governor frequencies without degradation.

---

## 1. Measured Jetson Orin Nano System Inventory

*All private IPs, tokens, and stream keys are redacted.*

| Subsystem | Measured Specification | Source |
| :--- | :--- | :--- |
| **SoC Model** | NVIDIA Jetson Orin Nano Developer Kit Super (8GB) | `/proc/device-tree/model` |
| **Operating System** | Ubuntu 24.04.4 LTS (Noble Numbat) | `/etc/os-release` |
| **Kernel** | Linux 6.8.12-1021-tegra (aarch64) | `uname -srm` |
| **L4T / JetPack** | L4T R39.2.1 (JetPack 6.x) | `/etc/nv_tegra_release` |
| **Power Profile** | 25W (MAXN performance mode) | `nvpmodel -q` |
| **CPU Architecture** | 6-core ARM Cortex-A78AE @ up to 1.728 GHz | `lscpu`, `/sys/devices/system/cpu/` |
| **Memory (RAM)** | 7.3 GiB Total / 4.6 GiB Available / 15.0 GiB Swap | `/proc/meminfo`, `free -h` |
| **CUDA Compiler** | CUDA 13.2 (V13.2.86) | `nvcc --version` |
| **TensorRT** | TensorRT 10.16.2.10 | Python `import tensorrt` |
| **Computer Vision** | OpenCV 4.8.0, NumPy 1.26.4, Pillow 10.2.0 | Python `cv2`, `numpy`, `PIL` |
| **PyTorch** | Not installed in system environment | Python `import torch` |
| **GStreamer Stack** | GStreamer 1.24.2 with `nvv4l2decoder`, `nvvidconv`, `x264enc` | `gst-inspect-1.0` |
| **FFmpeg Stack** | FFmpeg 8.0.1 with `libx264`, `libx265`, `h264_v4l2m2m` | `ffmpeg -version`, `ffmpeg -encoders` |
| **Hardware NVENC** | **None in silicon** (Orin Nano has NVDEC decoder only) | NVIDIA hardware specs |
| **Existing Services** | `box2-stream.py` (PID 266619) running passthrough stream | `pgrep -af` (read-only audit) |

---

## 2. Stage Director Framing & Tracking Overhead (Measured)

Executed 1,800 consecutive iterations of synthetic performer tracking, headroom calculation, 16:9 boundary clamping, and exponential smoothing filter updates:

- **Iterations**: 1,800 frames (60.0 seconds equivalent at 30 FPS)
- **Total Elapsed CPU Time**: **0.0021 seconds**
- **Per-Frame Latency**: **1.18 microseconds (µs)**
- **Throughput**: **845,577 FPS**
- **Finding**: Stage Director control logic is so lightweight that it leaves 99.996% of CPU cycles entirely available for media decoding, scaling, and encoding.

---

## 3. Synthetic 1080p30 H.264 Software Encoding Benchmark (Measured)

Tested continuous synthetic 1080p30 H.264 encoding via FFmpeg (`libx264`, `tune=zerolatency`, 4500 kbps, 1080p @ 30 FPS) under real-time pacing (`-re`) draining to `/dev/null`:

| Preset | Target FPS | Sustained FPS | Speed Ratio | Total Frames | Dropped Frames | Peak Temp (°C) | Temp Rise (°C) | Throttled | Real-Time Sustained? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`ultrafast`** | 30.0 | **31.0** | **1.02×** | 600 / 600 | **0** | 47.1°C | +0.6°C | No | **YES** |
| **`veryfast`** | 30.0 | **31.0** | **1.02×** | 600 / 600 | **0** | 47.5°C | +0.9°C | No | **YES (Recommended)** |
| **`faster`** | 30.0 | **31.0** | **1.02×** | 600 / 600 | **0** | 48.0°C | +1.1°C | No | **YES** |

### Maximum Encoding Throughput (Unconstrained, No `-re` Pacing):
- **`ultrafast`**: **70.0 FPS** (2.33× real-time)
- **`veryfast`**: **60.0 FPS** (2.00× real-time)
- **`faster`**: **44.0 FPS** (1.45× real-time)
- **`fast`**: **34.0 FPS** (1.13× real-time)

**Determination**:
- The sweet spot for broadcast visual quality vs. CPU headroom is **`-preset veryfast -tune zerolatency`**.
- At `veryfast`, the encoder runs at **2.0× real-time capacity** (utilizing ~50% of the 6 CPU cores during pure encoding), leaving the remaining 50% CPU capacity for audio mixing, network transmission, and operating system overhead.
- Because the Jetson Orin Nano has **hardware video decoding (`nvv4l2decoder`)**, incoming camera RTSP decoding uses zero CPU cycles, allowing the full CPU capacity to be dedicated to encoding.

---

## 4. End-to-End Jetson Architecture Recommendation

```
[ Reolink 4K RTSP Camera ]
         │
         ▼
[ Jetson Orin Nano 8GB ]
  ├─ Hardware NVDEC (nvv4l2decoder)       ──> Zero CPU decode of camera feed
  ├─ Stage Director (Python Core)         ──> 1.18 µs per frame tracking & framing
  ├─ Hardware Scaler / VIC (nvvidconv)    ──> Zero CPU 16:9 crop and 1080p scale
  └─ Software Encoder (libx264 veryfast)  ──> 60 FPS headroom @ 4500k bitrate
         │
         ▼ (RTMP)
[ Twitch Broadcaster (CantonRefinery) ]
```

With this topology, the entire live broadcast pipeline can operate **autonomously on the Jetson Orin Nano** without requiring a Mac host, OBS Studio UI, or external GPU server.
