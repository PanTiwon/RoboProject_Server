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

## [1.1.1] - 2026-10-14

### ✨ Added
- **On-Device Deep Learning Meter OCR (RapidOCR / ONNX Runtime)**: Integrated an on-device PP-OCRv4 deep learning inference engine via `rapidocr_onnxruntime` and `onnxruntime` optimized for ARM64 (Raspberry Pi 5 / Cortex-A76), achieving sub-second (~0.5s) meter number extraction directly from camera captures without external cloud dependencies.
- **Intelligent Digit Normalization & Spatial Deduplication**: Added character confusion mapping (e.g., `'O'/'o' -> '0'`, `'I'/'l' -> '1'`, `'Z' -> '2'`, `'S' -> '5'`) and Non-Maximum Suppression (NMS) containment filtering to eliminate overlapping ghost text boxes while strictly preserving left-to-right digit reading order.
- **Visual Character HUD Highlights**: Overlaid individual yellow polygon bounding boxes around each detected digit alongside the primary green ROI target border and detected reading readout directly on the captured JPEG.
- **Dynamic Serial Port Auto-Discovery & Hotplug Auto-Reconnect**: Enhanced `SerialController` to automatically discover and bind the active ESP32-S3 interface across both CDC-ACM (`/dev/ttyACM*`) and traditional USB-UART (`/dev/ttyUSB*`) ports based on USB VID/PID, coupled with a throttled auto-reconnect routine that seamlessly recovers if the USB cable is unplugged or power-cycled.
- **Live Hardware Link Telemetry**: Added live `ESP32 Link : [ CONNECTED (<port>) ]` status readouts to the CLI dashboard and updated the WebSocket telemetry funnel to accurately report ESP32 online state on `/dev/ttyACM*`.
- **Zero-Friction Open Wi-Fi Provisioning**: Updated `startup_network.sh` to broadcast `Mecanum_Setup` as an unencrypted Open Access Point, enabling field operators to tap and connect immediately from any mobile device without entering a password.
- **Pitch-Aware Smart Autofocus Range Selection**: Dynamically selects macro or normal autofocus range based on the camera tilt angle.

### 🐛 Fixed
- **Fixed Native PaddlePaddle ARM64 Segfault**: Replaced the crashing native PaddlePaddle C++ backend on Cortex-A76 with an ONNX Runtime engine, permanently resolving runtime crashes (`SIGSEGV`) and `show_log` argument deprecation errors.
- **Fixed Monotonic Image Sequence Numbering**: Resolved the repeating filename index bug (where `img_0051_...` repeated indefinitely once the 50-file FIFO ceiling was reached) by replacing array length counting with a persistent state counter (`.image_counter`) and regex-based filename inspection.
- **Hotspot Connection Cleanup**: Ensured temporary AP profiles are cleanly torn down and deleted upon completing Wi-Fi provisioning so the network device seamlessly transitions back to station mode.

---

## [1.1.0] - 2026-10-12

### ✨ Added
- **Boot-to-Run Systemd Autostart**: Automated startup on boot via `robot-core.service` and the one-step installer script `scripts/install_autostart.sh`.
- **Developer Bash Aliases**: High-productivity shell command shortcuts (`robot-log`, `robot-status`, `robot-restart`, `robot-stop`, `robot-start`) for live dashboard inspection and service management.
- **Offline Resilient Photo Queue & Cloud Auto-Sync**: Local caching and serialization queue (`pending_uploads.json`) with an asynchronous background worker that auto-syncs captured images to Firebase RTDB once network connectivity is restored.
- **Graceful Hardware Shutdown & Stationary Safety Interlock**: Gamepad-triggered safe shutdown (`L1 + R1` held for 5 seconds while strictly stationary), issuing an I2C delayed 5V power cut-off command to the Waveshare UPS HAT followed by OS poweroff.
- **Headless Wi-Fi Captive Portal**: Dynamic hotspot fallback (`Mecanum_Setup`) and a mobile-friendly Flask web portal (`setup_wifi.py`) for field network provisioning without peripherals.
- **4-Wheel Mecanum Omnidirectional Locomotion**: Inverse kinematics with speed scaling (25%, 50%, 75%, 100%).
- **On-Demand Camera System**: High-resolution image capture with hardware ISP 180° image rotation.
- **Tailscale Mesh Networking**: Telemetry and control access over WAN via Tailscale Funnel.

### 🔧 Improved & Optimized
- **Unified ROS 2 Launch Orchestration**: Merged `websocket_telemetry_funnel` directly into `robot_core.launch.py` to start the entire robot stack from a single launch command.
- **OpenCV HUD Real-Time Overlay**: Enhanced FPV stream with parking distance guidelines (0–60 cm), target crosshair, pan/tilt gimbal angle readouts, and visual capture notifications.
- **Zero-CPU Hardware ISP Flipping**: Offloaded 180° image rotation directly to the Raspberry Pi's Hardware Image Signal Processor (ISP).
- **Multi-Distro ROS 2 Compatibility**: Extended deployment compatibility to both Ubuntu 22.04 LTS (Humble) and Ubuntu 24.04 LTS (Jazzy).
