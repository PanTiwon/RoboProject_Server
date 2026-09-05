# 🤖 Teleoperated Waste Collection Robot (Autonomous-Ready Architecture)

[![ROS 2](https://img.shields.io/badge/ROS_2-Humble%20%2F%20Iron-blue.svg)](https://docs.ros.org/)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%20%7C%20ESP32-green.svg)](#)
[![Language](https://img.shields.io/badge/Language-Python%20%7C%20C%2B%2B-orange.svg)](#)
[![Network](https://img.shields.io/badge/Network-Tailscale%20VPN-black.svg)](#)

A modular, distributed robotics software stack for a 4-wheel Mecanum waste collection robot. Built on **ROS 2**, the current iteration focuses on reliable teleoperation with real-time kinematics calculation, hardware safety isolation, low-latency telemetry streaming, and remote dashboard monitoring via Tailscale mesh networking. The software architecture is explicitly designed to seamlessly integrate autonomous navigation in future updates.

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
|                 [ Speaker ]               | (PWM Actuation & Sweeper Control) |   |
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
        AudioNode["audio_feedback_manager\n(State Event Listener)"]
        TelemetryNode["websocket_telemetry_funnel\n(Web Server & I2C Battery)"]
    end

    subgraph Outputs ["Hardware & UI Layer"]
        ESP32["ESP32 Driver\n(M1-M4 PWM + Sweeper)"]
        AudioOut["aplay\n(Local Audio Jack)"]
        Dashboard["Web UI Dashboard\n(Browser)"]
        UPS["UPS HAT\n(I2C)"]
    end

    JoyNode -->|/joy| Teleop
    Teleop -->|/wheel_speeds| SerialNode
    Teleop -->|/robot/mode, /audio/mute| AudioNode
    Teleop -->|/telemetry| TelemetryNode
    
    UPS -->|I2C (0x2d)| TelemetryNode
    TelemetryNode -->|/battery_percent| Teleop

    SerialNode -->|Serial <M1,M2,M3,M4,Sw>| ESP32
    AudioNode --> AudioOut
    TelemetryNode --> Dashboard
```

---

## 🌐 3. Networking & Remote Telemetry (Tailscale Integration)

One of the core challenges in this project was enabling remote teleoperation and dashboard monitoring across different physical locations and ISPs without modifying router port-forwarding rules. To solve this, the system integrates **Tailscale** for secure overlay networking:

* **Tailscale Mesh VPN:** Connects the Raspberry Pi and the operator's PC into the same secure private network, regardless of their physical locations.
* **Tailscale Funnel:** Used to securely expose the local WebSocket telemetry server (`websocket_telemetry_funnel.py`) to the public internet. This allows the `WebSp.md` dashboard to receive real-time robot data (speed, mode, battery) over a secure HTTPS/WSS connection from any device.

```mermaid
flowchart LR
    subgraph Robot_Environment ["Robot Network (Location A)"]
        Pi["Raspberry Pi\n(ROS 2 Core)"]
        WSS["WebSocket Server\n(Local Port)"]
        TailscaleClient["Tailscale Daemon"]
        
        Pi --> WSS
        WSS --> TailscaleClient
    end

    subgraph Internet ["Cloud / WAN"]
        Funnel((Tailscale Funnel\nPublic WSS URL))
    end

    subgraph User_Environment ["Operator Network (Location B)"]
        Browser["Dashboard UI\n(WebSp.md)"]
    end

    TailscaleClient -->|Encrypted Tunnel| Funnel
    Funnel -->|Public WSS/HTTPS| Browser
```

---

## 🧠 4. Core Software Nodes & Features

| Node / File | Primary Responsibility |
|---|---|
| **`mecanum_joy_teleop.py`** | Central command node. Ingests raw `/joy` inputs, performs deadzone filtering, executes 4-wheel **Inverse Kinematics**, displays a CLI dashboard, and publishes `/wheel_speeds`. |
| **`serial_controller.py`** | High-speed, robust serial gateway to ESP32. Formats wheel commands into delimited ASCII packets (`<M1,M2,M3,M4,Sweeper>`) and reads hardware health acknowledgments. |
| **`websocket_telemetry_funnel.py`** | Real-time monitoring server **and hardware monitor**. Broadcasts system status, motor speeds, and reads **UPS HAT battery via I2C (`smbus`)**. It feeds data to `WebSp.md` via WebSockets (Tailscale Funnel) and publishes `/battery_percent` back to the CLI dashboard. |
| **`audio_feedback_manager.py`** | Headless status notifier. Uses `aplay` to play auditory cues for state transitions (e.g., Mode Switch, Emergency Stop, Connection Lost). |
| **`robot_core.launch.py`** | Automated orchestration. Brings up all core nodes, parameter configurations, and serial connections in a single command. |

---

## 💡 5. Engineering Decisions & Rationale

1. **Autonomous-Ready via ROS 2:**
   * While the robot currently operates strictly in Manual (Teleop) mode, using ROS 2 rather than a monolithic script provides structural fault isolation. It enables a seamless future transition to autonomous navigation simply by swapping the `/joy` topic with `Nav2`'s `cmd_vel` output, without rewriting the core actuation logic.
2. **Decoupled ESP32 Serial Actuation:**
   * Linux on a Raspberry Pi is a Non-Real-Time OS. Offloading PWM signal generation to the ESP32 ensures zero jitter on high-power motor drivers, maintaining smooth locomotion.
3. **Dedicated Audio Feedback Node:**
   * In field-testing without an attached monitor, auditory feedback provides immediate operator confirmation for network dropouts, E-Stop states, and mode shifts.

---

## 🚀 6. Future Roadmap
* **Vision & Object Detection:** Integrating a camera feed to run lightweight object detection models (e.g., YOLOv8) on the Raspberry Pi.
* **Full Autonomous Mode:** Developing the logic to transition from human-controlled `/joy` input to AI-driven navigation based on detected waste.
* **Closed-Loop Speed Control:** Adding PID velocity control using quadrature encoders on the ESP32.

---

## 📁 7. Repository Structure

```text
ros2_ws/
├── src/
│   └── robot_control/
│       ├── launch/
│       │   └── robot_core.launch.py       # Starts core nodes (joy, teleop, audio)
│       ├── media/                         # Audio assets for system feedback (*.wav)
│       ├── UPS_HAT_E/                     # UPS Battery hardware scripts & utilities
│       ├── robot_control/                 # Python module source
│       │   ├── audio_feedback_manager.py  # Event-based audio playback node
│       │   ├── mecanum_joy_teleop.py      # Core teleoperation & CLI Dashboard
│       │   ├── serial_controller.py       # USB-Serial ESP32 communication gateway
│       │   ├── websocket_telemetry_funnel.py # Tailscale Funnel WS & I2C Battery node
│       │   └── WebSp.md                   # Web dashboard UI source code
│       ├── package.xml                    # Package dependencies & metadata
│       └── setup.py                       # Console script entry points
```

---

## ⚙️ 8. Quick Start & Launch

### Prerequisites
* ROS 2 (Humble/Iron/Jazzy)
* Python 3.10+
* `alsa-utils` (for `aplay`)
* `python3-smbus` (for I2C Battery Monitoring)
* Tailscale (for remote telemetry)

### Build & Run
```bash
# Clone and build workspace
cd ~/ros2_ws
colcon build --symlink-install --packages-select robot_control
source install/setup.bash

# Launch full stack (Terminal 1)
ros2 launch robot_control robot_core.launch.py

# Launch Web Telemetry Server (Terminal 2)
ros2 run robot_control websocket_telemetry_funnel
```
