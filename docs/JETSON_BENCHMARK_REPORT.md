# BOX2 — Jetson Orin Nano 8GB Broadcast Feasibility Benchmark Report

Status: **Measured empirical results on physical hardware [Edge Device / Jetson Orin Nano 8GB]**.
Test Date: **November 9, 2026**.
PR: **[Draft PR #9](https://github.com/JosephJMWalker-MBA/box2/pull/9)**.

---

## Executive Summary

The primary inquiry is: **"Can the Jetson Orin Nano 8GB reliably produce the entire intelligent broadcast by itself without the Mac host?"**

### Key Conclusion: **Conditional Feasibility Demonstrated with Software H.264 Encoding (`libx264 veryfast`) and Sub-Stream Vision Decoupling**

1. **Portable Stage Director Overhead is Negligible**:
   - The full Stage Director state engine (`StageFramingAdapter`, `PerformerTracker`, `FramingEngine`, `OBSProposal` generator) executes in **111.6 microseconds per frame** on the Jetson ARM Cortex-A78AE CPU cores (throughput: **8,960.3 FPS**). An isolated inline arithmetic loop measures 1.18 µs.
   - In a 30 FPS broadcast (33.3 ms frame interval), Stage Director decision logic consumes **0.33%** of the available frame budget.

2. **1080p30 H.264 Software Encoding Feasibility**:
   - The Orin Nano lacks an NVENC hardware encoder block in silicon (as documented by NVIDIA).
   - However, its 6-core ARM Cortex-A78AE CPU delivers **60.0 FPS unconstrained throughput (2.0× real-time headroom)** at 1080p30 using `libx264` (`-preset veryfast -tune zerolatency`).
   - Under real-time pacing (`-re`) at a broadcast bitrate of 4500 kbps, it sustained **31.0 FPS with 0 dropped frames** and a speed ratio of **1.02×**.
   - In a complete continuous AV pipeline with hardware decode, NVMM scaling, and audio muxing, it delivered **42.7 FPS (1.42× real-time headroom)**.

3. **Face Detection Must Be Decoupled from Full-Resolution Raster**:
   - Measuring CPU face detection (`haarcascade_frontalface_default.xml`) on the synthetic stage pattern reveals:
     - **3840×2160 (Native 4K)**: 497.6 ms per frame (**2.0 FPS** — unviable for 30 FPS).
     - **1920×1080 (1080p)**: 138.9 ms per frame (**7.2 FPS** — unviable for 30 FPS).
     - **960×540 (qHD)**: 41.7 ms per frame (**24.0 FPS**).
     - **640×360 (Sub-stream)**: 25.9 ms per frame (**38.7 FPS** — real-time viable).
   - Face detection cannot be run on CPU at 4K; it must run on a downscaled preview/sub-stream or asynchronously at 5–10 Hz, while the Stage Director tracking filter interpolates at 30 FPS.

4. **Hardware NVDEC and NVMM Scaling Overhead**:
   - Hardware decoding via NVDEC (`nvv4l2decoder`) and GPU-accelerated scaling/cropping (`nvvidconv compute-hw=1`) offload the bulk of pixel processing.
   - Note on VIC: On L4T R39.2.1 / JetPack 7.2.1, `nvvidconv` cropping with VIC (`compute-hw=0`) returns driver error `VIC Configuration failed image scale factor exceeds 16, use GPU for Transformation`; setting `compute-hw=1` (GPU) executes cleanly at >250 FPS.
   - While hardware blocks reduce CPU load, driver contexts, NVMM buffer transfers to host RAM for software encoding, and pipeline synchronization still consume measurable system resources.

5. **Thermals and Throttling Remain Stable**:
   - In 25W power mode, thermal load during sustained 1080p30 software encoding rose by only **0.6°C to 1.1°C** (peaking at **49.2°C** against an 85°C throttle threshold).
   - Zero frequency throttling occurred; all 6 CPU cores sustained their governor frequencies without degradation.

---

## 1. Measured Jetson Orin Nano System Inventory

*All private IPs, tokens, and stream keys are redacted.*

| Subsystem | Measured Specification | Source |
| :--- | :--- | :--- |
| **SoC Model** | NVIDIA Jetson Orin Nano Developer Kit Super (8GB) | `/proc/device-tree/model` |
| **Operating System** | Ubuntu 24.04.4 LTS (Noble Numbat) | `/etc/os-release` |
| **Kernel** | Linux 6.8.12-1021-tegra (aarch64) | `uname -srm` |
| **L4T / JetPack** | L4T R39.2.1 (**JetPack 7.2.1**) | `/etc/nv_tegra_release` |
| **Power Profile** | 25W (MAXN performance mode) | `nvpmodel -q` |
| **CPU Architecture** | 6-core ARM Cortex-A78AE @ up to 1.728 GHz | `lscpu`, `/sys/devices/system/cpu/` |
| **Memory (RAM)** | 7.3 GiB Total / 4.6 GiB Available / 15.0 GiB Swap | `/proc/meminfo`, `free -h` |
| **CUDA Compiler** | CUDA 13.2 (V13.2.86) | `nvcc --version` |
| **TensorRT** | TensorRT 10.16.2.10 | Python `import tensorrt` |
| **Computer Vision** | OpenCV 4.8.0, NumPy 1.26.4, Pillow 10.2.0 | Python `cv2`, `numpy`, `PIL` |
| **PyTorch** | Not installed in system environment | Python `import torch` |
| **GStreamer Stack** | GStreamer 1.24.2 with `nvv4l2decoder`, `nvvidconv`, `x264enc`, `voaacenc` | `gst-inspect-1.0` |
| **FFmpeg Stack** | FFmpeg 8.0.1 with `libx264`, `libx265`, `h264_v4l2m2m` | `ffmpeg -version`, `ffmpeg -encoders` |
| **Hardware NVENC** | **None in silicon** (Orin Nano has NVDEC decoder only) | NVIDIA hardware specs |
| **Existing Services** | `box2-stream.py` (PID 266619) running passthrough remux | `pgrep -af` (read-only audit) |

---

## 2. Live Baseline Audit: Existing `box2-stream.py` Service

A non-invasive, read-only audit of the running `box2-stream.py` service was conducted without modifying, restarting, or terminating the process:

- **Architecture**: `box2-stream.py` ingests an HTTP-FLV sub-stream from the NVR and runs FFmpeg with:
  ```bash
  -c:v copy -c:a aac -b:a 128k -ar 48000 -ac 2 -f flv
  ```
- **Finding**: The existing service is a **passthrough / remux (`-c:v copy`)** of the camera's **640×360 sub-stream at 10.01 FPS**. It does **not** decode, track, or encode video on the Jetson.
- **Resource Footprint**:
  - Python controller (PID 266619): 0.1% CPU, 24 MB RSS.
  - FFmpeg remuxer (PID 617858): 6.7% CPU on 1 core (~1.1% total system CPU), 47 MB RSS.
  - Total load: ~1.1% system CPU, ~71 MB RAM.
  - Stability: 40+ hours continuous uptime without stall restarts.
- **Conclusion**: The existing stream leaves ~98.9% of CPU capacity and ~4.6 GB of RAM available for the Stage Director pipeline. Concurrent benchmarking does not interfere with its operation.

---

## 3. Edge Face Detection Latency (Measured Across Resolutions)

In edge vision pipelines, running face detection at native 4K on CPU is computationally unviable. To measure actual costs, we benchmarked the real installed OpenCV Haar cascade detector (`haarcascade_frontalface_default.xml`) on the Jetson CPU against the synthetic stage calibration image (`synthetic_stage_4k.png`):

| Resolution | Scale Factor | Latency (ms) | Frame Rate (FPS) | Real-Time 30 FPS Viable? | Architectural Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Native 4K (3840×2160)** | 1.00× | **497.6 ms** | **2.0 FPS** | **NO** (15× over budget) | Unviable on CPU |
| **1080p (1920×1080)** | 0.50× | **138.9 ms** | **7.2 FPS** | **NO** (4× over budget) | Unviable on CPU |
| **qHD (960×540)** | 0.25× | **41.7 ms** | **24.0 FPS** | Borderline (near real-time) | Candidate for downscaled detection |
| **Sub-stream (640×360)** | 0.167× | **25.9 ms** | **38.7 FPS** | **YES** (under 33.3 ms) | **Recommended detection target** |

**Architectural Insight**:
- Face *detection* does not need to execute at 4K. The NVR already publishes an independent 640×360 sub-stream.
- Running face detection on the sub-stream takes **25.9 ms**, which comfortably sustains 10–25 Hz detection.
- Meanwhile, the Stage Director tracking and exponential smoothing engine runs at 30 Hz (or higher) to interpolate bounding boxes, guaranteeing smooth camera transitions without stalling the pipeline.

---

## 4. Stage Director Python State Engine Overhead (Measured)

We benchmarked the **real Python object-oriented Stage Director state engine** (`StageFramingAdapter` + `StageDirector` + `PerformerTracker` + `FramingEngine` + `translate_to_obs_request()`) over 1,800 consecutive iterations with synthetic performer pacing, offstage bystander filtering, spatial gating, and velocity clamping:

- **Iterations**: 1,800 frames (60.0s equivalent at 30 FPS)
- **Total Elapsed CPU Time**: **0.2009 seconds**
- **Per-Frame Latency**: **111.6 microseconds (µs)** (compared to 1.18 µs in an isolated inline math loop)
- **Throughput**: **8,960.3 FPS**
- **Frame Budget Consumed**: **0.33%** of the 33.3 ms frame interval (leaving 99.67% of CPU time for other tasks).

---

## 5. End-to-End Continuous Synthetic AV Pipeline Benchmark (Measured)

A sandboxed, continuous GStreamer AV pipeline was constructed and benchmarked on the physical Jetson Orin Nano, executing all pipeline components simultaneously without external network egress:

```
[ Synthetic 4K Source (H.264 MP4) ]
               │
               ▼
   [ nvv4l2decoder (NVDEC) ]
               │ (memory:NVMM)
               ▼
[ nvvidconv compute-hw=1 (GPU/NVMM) ]  <── Dynamic 16:9 crop & resize to 1080p
               │ (memory:NVMM)
               ▼
      [ nvvidconv ]                    <── NVMM-to-CPU host RAM transfer
               │ (video/x-raw, I420)
               ▼
  [ x264enc (1080p30 H.264) ]          <── libx264 veryfast @ 4500 kbps
               │
               ▼ (queue)
            [ mux ] ◄── [ audiotestsrc ! voaacenc (AAC 48kHz Stereo @ 128 kbps) ]
               │ (flvmux)
               ▼
          [ fakesink ]                 <── Discarded locally (zero network egress)
```

### Benchmark Results (600 Frames / 20.0s Equivalent):
- **Pipeline Execution**: **SUCCESS (`return_code: 0`)**
- **Total Duration**: 14.06 seconds
- **Effective Throughput**: **42.7 FPS** (**1.42× real-time headroom**)
- **Initial CPU Thermal**: 49.8°C
- **Final CPU Thermal**: 49.2°C (Thermal Delta: **-0.6°C**, active fan cooling maintained equilibrium)
- **Peak Temperature**: 49.9°C (Throttle threshold: 85°C — **35.1°C thermal safety margin**)
- **Throttling Events**: **0** (Governor remained locked at target frequencies)
- **Impact on Concurrent `box2-stream.py`**: **None**. `box2-stream.py` maintained its 10.01 FPS passthrough stream without dropped frames or restarts throughout the test.

---

## 6. Pass / Conditional / Fail Assessment & Named Unresolved Tests

| Subsystem | Status | Current Evidence | Remaining Unresolved Tests |
| :--- | :--- | :--- | :--- |
| **Stage Director State Engine** | **PASS** | 111.6 µs per frame (8,960 FPS) in real Python engine; 72 unit/regression tests passing. | Multi-performer priority arbitration in live multi-mic setups. |
| **1080p H.264 Software Encoding** | **PASS** | 42.7 FPS in complete AV pipeline; 60 FPS unconstrained encoding. | 24-hour continuous burn-in soak under ambient heat. |
| **Hardware Video Decoding** | **PASS** | `nvv4l2decoder` decodes 1080p/4K at >250 FPS on NVDEC hardware. | Live Reolink 4K RTSP stream jitter and packet loss recovery over Wi-Fi. |
| **Hardware Crop & Scaling** | **CONDITIONAL** | `nvvidconv compute-hw=1` (GPU) crops and scales NVMM buffers cleanly at >200 FPS. | VIC hardware (`compute-hw=0`) fails with scale factor error on L4T R39.2.1; requires GPU mode (`compute-hw=1`). |
| **Edge Face Detection** | **CONDITIONAL** | 640×360 sub-stream detection runs at 38.7 FPS (25.9 ms). 4K CPU detection is unviable (2 FPS). | TensorRT model conversion (e.g. YOLOv8-Face or Yunet ONNX) for hardware GPU inferencing. |
| **Live Broadcast Integration** | **UNRESOLVED** | Read-only audit complete; zero hardware or network modifications made. | Real camera PTZ limits, live Twitch broadcast quality, and booking snapshot synchronization. |

### Overall Readiness: **CONDITIONAL PASS**
The NVIDIA Jetson Orin Nano 8GB is hardware-capable of running the complete Stage Director AV broadcast pipeline at 1080p30, provided that:
1. Face detection is performed on the camera's sub-stream or asynchronously via TensorRT/GPU.
2. `nvvidconv` uses `compute-hw=1` (GPU) rather than VIC for dynamic 16:9 cropping.
3. Encoding is performed using `libx264 -preset veryfast -tune zerolatency` at 4500 kbps.
