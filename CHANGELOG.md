# Changelog

All notable changes to the **Refuse Robot (Escape Velocity)** software stack will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.2] - 2026-10-16

### 🚀 Highlights
- **Sub-Second WebRTC FPV Video Streaming**: Upgraded from MJPEG to standard WebRTC via MediaMTX broker and WHEP.
- **Deep Learning OCR & Multi-Meter Vision**: Added RapidOCR (ONNX) pipeline with automated HSV blue meter detection, left-to-right sorting, and split uploads.
- **Lean Firebase RTDB Payload**: Eliminated redundant base64 image data and normalized reading values for immediate dashboard rendering.
- **Joystick Safety & Camera Recenter**: Added Emergency Brake (E-Stop Toggle) and L3 Camera Recenter with chassis screw offset.

### 🎥 Vision & FPV Streaming
- **MediaMTX WebRTC Broker**: Integrated MediaMTX binary for ultra-low-latency video streaming (`rtsp://127.0.0.1:8554/live` -> WebRTC WHEP on port 8889).
- **WHEP Client Demo (`whep_client_demo.html`)**: Added standalone HTML5 WebRTC player with auto-reconnect and fullscreen support.
- **Dual Capture Mode**:
  - `STREAM_GRAB`: Instant zero-downtime capture directly from active MediaMTX RTSP stream (keeps FPV screen 100% continuous).
  - `HARDWARE_STILL`: High-resolution capture with sensor HDR and rapid stream re-launch.

### 🔍 Meter Detection & OCR Pipeline
- **Hybrid Detection & OCR**: Added RapidOCR ONNX deep learning engine with PaddleOCR fallback.
- **HSV Blue Box Segmentation**: Detects multiple meters with noise suppression (Morphology close/open, area 0.5%–70%, aspect ratio 0.35–3.0) and sorts bounding boxes strictly left-to-right.
- **Dynamic Crop & Padding**: Expands meter ROI by +15% horizontally and +12% vertically to prevent digit clipping.
- **2D Suppression & Header Filter**: Eliminates non-digit headers (such as "REAI") and handles 2D spatial character overlap.
- **Center ROI Fallback**: Seamless fallback to fixed center region when multi-meter detection is disabled or 0 meters are found.

### ☁️ Cloud & Firebase RTDB
- **Payload Optimization**: Removed duplicate `image_data` field (keeping only `image_base64`), reducing payload size by ~50% and saving Firebase bandwidth.
- **Normalized `meter_reading`**: Standardized reading values to pure numeric strings (e.g., `"1515"`) for direct dashboard chart and table binding.
- **Admin Workflow Alignment**: Removed hardcoded `room_id` and `reviewed` status from robot uploads, allowing operators to assign rooms and review records on the web dashboard.
- **Multi-Meter Split Uploads**: Iterates through detected meters, generating independent RTDB push keys with cropped ROI Base64 images and `meter_index` (1, 2, 3).

### 🕹️ Joystick Teleoperation & Controls (`mecanum_joy_teleop.py`)
- **Emergency Brake (E-Stop Toggle)**:
  - Toggled via the left diamond button (Square on PS / X on Xbox).
  - Immediately locks motor speeds to `<0, 0, 0, 0>` and sets ROS 2 `/wheel_speeds` to zero.
  - Ignores all directional analog stick inputs while active.
  - Visual status alert on CLI Dashboard (`🚨 [ ENGAGED (STOPPED) ]`) and logger.
- **Camera Recenter with Hardware Offset (L3)**:
  - Button Index 9 resets camera servos to Yaw=0.0° and Pitch=8.0° (offset to eliminate lens obstruction by chassis mounting screws).
- **Intelligent Gamepad Layout Auto-Detection**:
  - Automatically identifies Xbox 360 / XInput controllers vs PlayStation DualShock pads to map Square/X and Triangle/Y correctly.

---

## [1.1.1] - 2026-09-22

### ⚡ Added & Improved
- **Graceful Hardware Shutdown**: Holding `L1 + R1` for 5s while stationary safely flushes filesystem buffers (`sync`), commands Waveshare UPS HAT (`0x2d`) to delay 5V cut-off by 30s, and executes OS poweroff.
- **Serial Auto-Detection & Recovery**: Added `find_esp32_port()` to dynamically detect `/dev/ttyACM*` or `/dev/ttyUSB*` with automatic reconnection on disconnect.
- **Live Battery Monitoring**: Continuous reading of Waveshare UPS HAT battery percentage via I2C (`smbus`).

---

## [1.1.0] - 2026-09-15

### 🤖 Initial Release (Escape Velocity)
- **4-Wheel Mecanum Omnidirectional Locomotion**: Inverse kinematics with speed scaling (25%, 50%, 75%, 100%).
- **On-Demand Camera System**: High-resolution image capture with hardware ISP 180° image rotation.
- **Offline Upload Queue**: Local storage quota (FIFO max 50 images) and automatic offline sync (`pending_uploads.json`).
- **Headless Wi-Fi Captive Portal**: AP hotspot (`Mecanum_Setup`) with mobile web setup UI.
- **Tailscale Mesh Networking**: Telemetry and control access over WAN via Tailscale Funnel.
