# 🤖 Teleoperated Waste Collection Robot (Escape Velocity V1.1.2)

[![ROS 2](https://img.shields.io/badge/ROS_2-Humble%20%2F%20Jazzy-blue.svg)](https://docs.ros.org/)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%205%20%7C%20ESP32-green.svg)](#)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%20OpenCV%20%7C%20ONNX-yellow.svg)](#)
[![Streaming](https://img.shields.io/badge/Streaming-MediaMTX%20WebRTC%20WHEP-purple.svg)](#)
[![Network](https://img.shields.io/badge/Network-Tailscale%20Funnel-red.svg)](#)
[![Storage](https://img.shields.io/badge/Storage-FIFO%2050%20Img%20%7C%20Offline%20Queue-orange.svg)](#)
[![License](https://img.shields.io/badge/License-Apache--2.0-lightgrey.svg)](LICENSE)

A modular, distributed robotics software stack for a 4-wheel Mecanum waste collection robot. Built on **ROS 2**, the **Escape Velocity V1.1.2** release features ultra-low-latency **WebRTC (WHEP)** FPV streaming via **MediaMTX**, Deep Learning **RapidOCR (ONNX)** with automated HSV multi-meter segmentation and split uploads, gamepad **Emergency Brake (E-Stop Toggle)**, one-touch **Camera Recenter (L3)** with hardware offset, and an optimized, lean **Firebase Realtime Database (RTDB)** cloud pipeline.

---

## ✨ Key Features & System Highlights

### 📸 1. Vision, Cloud Storage & Offline Resilience
* **Ultra-Low-Latency WebRTC FPV Streaming (MediaMTX & WHEP):** Upgraded from MJPEG to standard WebRTC via MediaMTX broker, providing sub-second glass-to-glass latency on port 8889 (`/live/whep`). Includes a standalone HTML5 WebRTC demo player (`whep_client_demo.html`).
* **Dual Capture Mode (Zero-Downtime vs High-Res Turbo):**
  * `STREAM_GRAB`: Instant zero-downtime capture directly from active MediaMTX RTSP stream without blacking out the FPV screen.
  * `HARDWARE_STILL`: High-resolution photo capture with sensor HDR and instant stream re-launch (< 1s).
* **Deep Learning RapidOCR & HSV Multi-Meter Detection:** Automatically segments blue meter enclosures via HSV color filtering with morphology cleanup and left-to-right spatial sorting. Includes 2D spatial suppression to eliminate non-digit header interference (e.g. "REAI").
* **Multi-Meter Split Uploads & Lean Payload:** Each detected meter is cropped with +15% horizontal / +12% vertical padding and uploaded as an individual RTDB record with its own Base64 image and pure 4-digit reading, reducing payload size by ~50% compared to legacy redundant schemas.
* **Automated Image Quota Management (FIFO Max 50 Photos):** Local storage (`images/`) maintains a strict 50-photo ceiling; oldest photos are automatically pruned using modification-time (`mtime`) FIFO sorting.
* **Offline-Resilient Capture Queue & Auto-Sync:** Photos captured during Wi-Fi or cellular dropouts are safely queued in `pending_uploads.json` and automatically synced to Firebase RTDB by a background daemon once connection restores.

### 🔋 2. Hardware Power Management & Fail-Safe Mechanics
* **Emergency Brake (E-Stop Toggle):** Square / X button on the gamepad immediately engages E-Stop, forcing all motor PWM commands to `<0, 0, 0, 0>`, publishing zero velocity to ROS 2 `/wheel_speeds`, and ignoring analog stick deflections until toggled off.
* **Camera Recenter with Hardware Offset (L3):** Left stick click instantly resets Pan to 0.0° and Tilt to 8.0° (calibrated to prevent camera lens obstruction by chassis screws).
* **Graceful Hardware Shutdown (`L1 + R1` Hold 5s):** Eliminates filesystem corruption by executing a safe OS shutdown (`sudo poweroff`) coupled with an I2C command to the Waveshare UPS HAT (`0x2d`) requesting a delayed 30-second 5V power cut-off.
* **Stationary Safety Interlock:** Prevents accidental shutdown during active driving. The shutdown countdown initiates **only** when the robot is completely stationary ($v_x = 0, v_y = 0, \omega_z = 0$). Any joystick deflection or wheel movement immediately cancels the timer.
* **Live I2C Battery Monitoring:** Continuous reading of battery percentage and voltage from the Waveshare UPS HAT via I2C (`smbus`), broadcasted to both the CLI dashboard and the remote web UI.

### 🤖 3. Boot-to-Run Autostart & Developer CLI Tools
* **Zero-Touch Autostart (Systemd):** The entire ROS 2 stack boots automatically on Raspberry Pi startup via `robot-core.service` with unbuffered real-time logging (`PYTHONUNBUFFERED=1`).
* **Developer Bash Aliases:** Includes high-productivity aliases (`robot-log`, `robot-status`, `robot-restart`, `robot-stop`, `robot-start`) for immediate live dashboard monitoring and service control from any terminal session.

### 📡 4. Field Networking & Remote Teleoperation
* **Headless Wi-Fi Captive Portal (`Mecanum_Setup`):** If no known Wi-Fi networks are found on boot, the robot creates a local AP Hotspot with a captive portal web UI (`setup_wifi.py`), allowing operators to reconfigure network credentials from their smartphone in the field without any external display or keyboard. The hotspot persists until the connection is fully verified.
* **Tailscale Mesh VPN & Funnel:** Enables cross-network teleoperation and telemetry dashboard access over public cellular / WAN networks without requiring router port-forwarding or public IP addresses.

### 🕹️ 5. Kinematics & Actuation Gateway
* **4-Wheel Mecanum Omnidirectional Drive:** Full holonomic locomotion (forward, strafe, rotate, and diagonal movement) with joystick deadzone filtering.
* **Decoupled ESP32 Gateway:** High-speed USB-Serial bridge isolating high-current motor PWM drivers and the vacuum relay from the Raspberry Pi host.

---

## 📌 1. System Architecture Overview

The system follows a distributed compute model, decoupling high-level compute and networking (Raspberry Pi) from real-time motor actuation (ESP32):

```text
+-----------------------------------------------------------------------------------+
|                                  USER / OPERATOR                                  |
|         [ Game Controller ]                     [ Web Dashboard (WebSp) ]         |
+------------------+------------------------------------------+---------------------+
                   |                                          ^
                   | (Bluetooth / USB)                        | (WebSocket / HTTPS)
                   V                                          |
+-------------------------------------------------------------+---------------------+
|                      RASPBERRY PI (ROS 2 Compute Brain)                           |
|                                                                                   |
|   [/joy] ----> [ mecanum_joy_teleop ] ----> [/wheel_speeds]                       |
|                       |                             |                             |
|                       | (kinematics.py)             v                             |
|                       |                     [ serial_controller ]                 |
|                       v                             |                             |
|             [ audio_feedback_manager ]              | (USB Serial / 115200 Baud)  |
|                       |                             v                             |
|                       | (aplay *.wav)     +-----------------------------------+   |
|                       v                   |             ESP32                 |   |
|                 [ Speaker ]               | (PWM Actuation & Vacuum Relay)    |   |
+-------------------------------------------+-----------------+-----------------+---+
                                                              |
                                                              V
                                              [ Motor Drivers & Actuators ]
```

---

## 🔄 2. ROS 2 Computational Graph & Data Flow

```mermaid
flowchart LR
    subgraph Inputs ["Input Layer"]
        JoyNode["joy_node\n(Standard ROS 2)"]
    end

    subgraph Core ["robot_control Package"]
        Teleop["mecanum_joy_teleop\n(Kinematics & Logic)"]
        SerialNode["serial_controller\n(ESP32 Gateway)"]
        CameraNode["camera_firebase_manager\n(On-Demand Stream & Capture)"]
        AudioNode["audio_feedback_manager\n[UNDER MAINTENANCE]"]
        TelemetryNode["websocket_telemetry_funnel\n(Web Server & I2C Battery)"]
    end

    subgraph Outputs ["Hardware & UI Layer"]
        ESP32["ESP32 Driver\n(M1-M4 PWM + Vacuum)"]
        AudioOut["aplay\n(Local Audio Jack)"]
        CameraOut["FPV Flask Stream\n(Port 5000) & Firebase"]
        Dashboard["Web UI Dashboard\n(Browser)"]
        UPS["UPS HAT\n(I2C)"]
    end

    JoyNode -->|/joy| Teleop
    Teleop -->|/wheel_speeds| SerialNode
    Teleop -->|/robot/mode, /audio/mute| AudioNode
    Teleop -->|/telemetry| TelemetryNode
    Teleop -->|Joy Start/Action 1| CameraNode
    
    UPS["UPS HAT"] -->|"I2C (0x2d)"| TelemetryNode
    TelemetryNode -->|/battery_percent| Teleop

    SerialNode -->|Serial <M1,M2,M3,M4,Vacuum,Yaw,Pitch>| ESP32
    AudioNode --> AudioOut
    CameraNode --> CameraOut
    TelemetryNode --> Dashboard
```

---

## 🌐 3. Networking & Remote Telemetry (Tailscale Integration)

One of the core challenges in this project was enabling remote teleoperation and dashboard monitoring across different physical locations and ISPs without modifying router port-forwarding rules. To solve this, the system integrates **Tailscale** for secure overlay networking:

* **Tailscale Mesh VPN:** Connects the Raspberry Pi and the operator's PC into the same secure private network, regardless of their physical locations.
* **Tailscale Funnel:** Used to securely expose both the WebSocket server (`websocket_telemetry_funnel.py`) and the Flask FPV Camera stream to the public internet without exposing the whole device.

```mermaid
flowchart LR
    subgraph Robot_Environment ["Robot Network (Location A)"]
        Pi["Raspberry Pi\n(ROS 2 Core)"]
        WSS["WebSocket Server\n(Port 8080)"]
        Flask["Camera Server\n(Port 5000)"]
        TailscaleClient["Tailscale Daemon"]
        
        Pi --> WSS
        Pi --> Flask
        WSS --> TailscaleClient
        Flask --> TailscaleClient
    end

    subgraph Internet ["Cloud / WAN"]
        Funnel((Tailscale Funnel\nPublic URLs))
    end

    subgraph User_Environment ["Operator Network (Location B)"]
        Browser["Dashboard UI\n(WebSp.md)"]
    end

    TailscaleClient -->|Encrypted Tunnels| Funnel
    Funnel -->|WSS / HTTPS| Browser
```

---

## 🧠 4. Core Software Nodes & Features (Escape Velocity V1.1.2)

| Node / File | Primary Responsibility |
|---|---|
| **`mecanum_joy_teleop.py`** | Central command node. Ingests raw `/joy` inputs, performs deadzone filtering, executes 4-wheel **Inverse Kinematics**, manages PTZ Camera angles, displays a CLI dashboard, and publishes `/wheel_speeds`. Includes **Emergency Brake (E-Stop Toggle)**, **Camera Recenter with Offset (L3)**, **Gamepad Auto-Detection** (Xbox 360 vs PS4), and **Graceful Hardware Shutdown** (`L1 + R1` 5s hold). |
| **`serial_controller.py`** | High-speed, robust serial gateway to ESP32. Formats wheel commands into delimited ASCII packets (`<M1,M2,M3,M4,Vacuum,Yaw,Pitch>`) with auto-reconnection and port auto-detection (`/dev/ttyACM*`, `/dev/ttyUSB*`). |
| **`camera_firebase_manager.py`** | Native Python camera state manager. Provides **WebRTC Live FPV Streaming (MediaMTX WHEP on Port 8889)**, **Dual Capture Mode** (`STREAM_GRAB` & `HARDWARE_STILL`), **Deep Learning RapidOCR (ONNX)** with **HSV Multi-Meter Segmentation**, and **Lean Firebase RTDB Split Uploads**. Enforces FIFO quota (max 50 images) and offline auto-sync. |
| **`websocket_telemetry_funnel.py`** | Real-time monitoring server **and hardware monitor**. Broadcasts system status, motor speeds, and reads **UPS HAT battery via I2C (`smbus`)**. It feeds data to the Web UI via WebSockets (Tailscale Funnel) and publishes `/battery_percent` back to the CLI dashboard. |
| **`audio_feedback_manager.py`** | **[CURRENTLY UNDER MAINTENANCE]** Headless status notifier. Uses `aplay` to play auditory cues for state transitions. |
| **`robot_core.launch.py`** | Automated orchestration. Brings up all core nodes, parameter configurations, and serial connections in a single command. |
| **`setup_wifi.py` & `startup_network.sh`** | **Headless Wi-Fi Captive Portal**. Spawns an AP Hotspot and mobile-friendly Flask web UI to easily switch Wi-Fi networks in the field without monitor/keyboard. |

---

## 💡 5. Engineering Decisions & Rationale

1. **Hardware ISP Image Flipping:**
   * In V1, we offload 180-degree image flipping to the `rpicam` Hardware Image Signal Processor. This completely removes CPU overhead for flipping frames while ensuring both the FPV Stream and the High-Res Photo Captures are perfectly oriented.
2. **OpenCV FPV Overlay (HUD):**
   * Real-time OpenCV drawings were added to provide an immersive operator experience. The FPV stream includes 0-60cm parking guidelines for tight navigation, a sniper-style crosshair, a black header bar indicating Pan/Tilt angles, and a flashing "PHOTO CAPTURED" notification.
3. **Decoupled ESP32 Serial Actuation:**
   * Linux on a Raspberry Pi is a Non-Real-Time OS. Offloading PWM signal generation and Relay triggering to the ESP32 ensures zero jitter on high-power motor drivers, maintaining smooth locomotion.
4. **On-Demand Camera Resource Management:**
   * FPV streaming drains bandwidth and battery. The camera system defaults to OFF. Using a gamepad toggle, it temporarily spawns an MJPEG Flask server via `rpicam-vid`. When a high-res photo is requested, the stream gracefully yields the hardware lock to `rpicam-still`, pushes to Firebase RTDB via Base64 string, and automatically resumes.
5. **Headless Wi-Fi Setup for Field Deployment (Dynamic Configuration):**
   * Field testing often involves unknown network environments where SSH or external monitors are unavailable. The `startup_network.sh` boot script uses `nmcli` to ping for internet access on boot. If it fails, it instantly broadcasts an AP Hotspot (Mecanum_Setup). Operators can connect via their smartphones to access the `setup_wifi.py` Flask portal, allowing them to enter new Wi-Fi credentials on the fly. This guarantees immediate, seamless network switching when migrating the robot between locations.
6. **Graceful Hardware Shutdown & Safety Interlock:**
   * Abruptly cutting DC power via a physical toggle switch risks corrupted file systems on the Raspberry Pi's SD card / NVMe storage. To prevent data corruption in the field, we introduced a gamepad-driven shutdown sequence: holding **L1 + R1 (Left & Right Bumpers) for 5 continuous seconds** while the robot is **completely stationary** (Safety Interlock: all wheel velocities and directional inputs $v_x, v_y, \omega_z$ must remain 0). Releasing the buttons or moving the robot immediately cancels the timer. Upon countdown completion, the node issues an I2C command to the Waveshare UPS HAT (`0x2d`) requesting a delayed 5V power cut-off in 30 seconds (`sudo i2cset -y 1 0x2d 0x01 0x55`), immediately followed by an OS-level graceful powerdown (`sudo poweroff`), allowing all file buffers to sync before power is removed.
7. **Local Storage FIFO Quota & Offline Resilient Cloud Sync:**
   * Field robotics frequently face intermittent Wi-Fi or cellular connections. Continuously capturing high-resolution photos without a storage boundary risks filling the Raspberry Pi's SD card / NVMe SSD, which can lead to filesystem corruption or OS failure. To solve this, `camera_firebase_manager` enforces a hard ceiling of 50 images (`self.max_images = 50`), automatically deleting the oldest image files via FIFO `os.path.getmtime` sorting. Additionally, if an upload fails due to network outage, the payload is persisted to `pending_uploads.json` and automatically flushed to Firebase RTDB by a background daemon as soon as internet connectivity returns.

---

## 🚀 6. Future Roadmap
* **[COMPLETED in V1.1.2] Vision & Object Detection (OCR):** Integrated RapidOCR ONNX Runtime with HSV multi-meter segmentation and Firebase RTDB split uploads.
* **[COMPLETED in V1.1.2] WebRTC Streaming:** Migrated from MJPEG to MediaMTX WHEP for sub-second FPV latency.
* **Full Autonomous Mode:** Developing the logic to transition from human-controlled `/joy` input to AI-driven navigation based on detected waste.
* **Closed-Loop Speed Control:** Adding PID velocity control using quadrature encoders on the ESP32.

---

## 📁 7. Repository Structure

```text
ros2_ws/
├── CHANGELOG.md                   # Full release history and version logs
├── whep_client_demo.html          # WebRTC WHEP HTML5 video player demo
├── scripts/
│   ├── setup_wifi.py              # Flask Wi-Fi Captive Portal UI
│   ├── startup_network.sh         # Network check & Hotspot boot script
│   ├── robot-portal.service       # Systemd unit for the captive portal
│   ├── start_ros2.sh              # ROS 2 Environment loader & stack launcher
│   ├── robot-core.service         # Systemd unit for the core robot stack
│   └── install_autostart.sh       # Automated autostart installer & aliases setup
├── src/
│   └── robot_control/
│       ├── launch/
│       │   └── robot_core.launch.py       # Starts all nodes (joy, teleop, audio, telemetry funnel)
│       ├── media/                         # Audio assets for system feedback (*.wav)
│       ├── UPS_HAT_E/                     # UPS Battery hardware scripts & utilities
│       ├── robot_control/                 # Python module source
│       │   ├── audio_feedback_manager.py  # [MAINTENANCE] Event-based audio playback node
│       │   ├── camera_firebase_manager.py # WebRTC WHEP FPV Stream, RapidOCR & Firebase RTDB
│       │   ├── mecanum_joy_teleop.py      # Core teleoperation, E-Stop, Recenter & CLI Dashboard
│       │   ├── serial_controller.py       # USB-Serial ESP32 communication gateway
│       │   ├── websocket_telemetry_funnel.py # Tailscale Funnel WS & I2C Battery node
│       │   └── WebSp.md                   # Web dashboard UI source code
│       ├── package.xml                    # Package dependencies & metadata
│       └── setup.py                       # Console script entry points
```

---

## 🛠️ 8. Prerequisites & Dependencies

**Operating System:** Ubuntu 22.04 (Jammy) or newer, with **ROS 2** (Humble/Iron/Jazzy) installed.

### 1. System Dependencies (OS Level)
Install the required system packages. This includes NetworkManager (essential for the Wi-Fi Captive Portal), audio utilities, and I2C tools:
```bash
sudo apt update && sudo apt install network-manager alsa-utils python3-smbus i2c-tools
```

> [!TIP]
> **Passwordless Sudo for Graceful Shutdown:**
> To allow the teleoperation node to execute system poweroff and I2C commands without prompting for a sudo password, configure a rule via `sudo visudo` or by creating `/etc/sudoers.d/robot-power`:
> ```text
> $USER ALL=(ALL) NOPASSWD: /sbin/poweroff, /usr/sbin/i2cset
> ```

### 2. Python Libraries
Install the necessary Python dependencies. Core libraries include `Flask` (for the FPV stream and Wi-Fi portal), `opencv-python-headless` (for the Camera HUD), and `pyserial`:
```bash
pip install -r requirements.txt
```

---

## 🚀 9. Quick Start & Launch

### 🤖 1. Automated Boot-to-Run (Recommended)
You can configure the robot to start automatically every time the Raspberry Pi powers on using the automated systemd installer:

```bash
# Run the autostart installer
bash ~/ros2_ws/scripts/install_autostart.sh

# Reload bash aliases in current session
source ~/.bashrc
```

#### 🛠️ Developer Management Shortcuts (Bash Aliases)
Once installed, managing the robot service and inspecting logs from any terminal is effortless:

| Command | Action | Description |
|---|---|---|
| **`robot-log`** | `journalctl -u robot-core.service -f -n 50` | Streams the live CLI Dashboard and ROS 2 console logs in real time. |
| **`robot-status`** | `systemctl status robot-core.service` | Displays current service health, uptime, and PID. |
| **`robot-stop`** | `sudo systemctl stop robot-core.service` | Temporarily halts the robot stack (e.g., for development/debugging). |
| **`robot-start`** | `sudo systemctl start robot-core.service` | Starts the robot stack background service. |
| **`robot-restart`** | `sudo systemctl restart robot-core.service` | Restarts the full robot stack cleanly. |

---

### 💻 2. Manual Launch (For Development)
If you prefer running the stack interactively in your terminal:

```bash
# Build workspace
cd ~/ros2_ws
colcon build --symlink-install --packages-select robot_control
source install/setup.bash

# Launch full stack (All nodes: Joy, Teleop, Audio, Telemetry Funnel)
ros2 launch robot_control robot_core.launch.py
```

---

### 🌐 3. Accessing the Dashboard & Camera

Once the system is running, you can monitor the robot remotely:

**1. Telemetry Web Dashboard (Hosted on Netlify)**
* Access the main control interface here: **[🔗 Refuse Robot - Netlify](https://refuserobot.netlify.app/)**
* **Local Network:** Dashboard WebSocket connects to `ws://<RASPBERRY_PI_IP>:8080`
* **Public Internet (Tailscale Funnel):** Dashboard connects securely via `wss://core.tailb47df1.ts.net:443` (Maps to 8080 locally).

**2. FPV Camera Live Stream**
* The stream defaults to **OFF** to save bandwidth and battery. 
* Press the **Start** button on your gamepad to toggle the stream **ON**.
* The stream features an advanced **OpenCV HUD Overlay** (Parking Guidelines, Crosshair, and Real-time Servo Angles).
* **Local Network:** `http://<RASPBERRY_PI_IP>:5000`
* **Public Internet (Tailscale Funnel):** `https://core.tailb47df1.ts.net:8443` (Maps to 5000 locally).

---

## 📝 10. Changelog & Version History

Detailed release notes, version milestones, and technical bug fixes are documented in **[CHANGELOG.md](CHANGELOG.md)**.

| Version | Release Date | Key Milestones |
|---|---|---|
| **[1.1.2](CHANGELOG.md#112---2026-10-16)** | 2026-10-16 | MediaMTX WebRTC (WHEP), RapidOCR Multi-Meter Detection, Lean RTDB Payload, E-Stop & Camera Recenter |
| **[1.1.1](CHANGELOG.md#111---2026-10-14)** | 2026-10-14 | RapidOCR ONNX ARM64 migration, Serial Auto-Discovery, Persistent Counter & Bugfixes |
| **[1.1.0](CHANGELOG.md#110---2026-10-12)** | 2026-10-12 | Systemd Autostart, Graceful Hardware Shutdown, Captive Portal Wi-Fi, Tailscale Funnel |
