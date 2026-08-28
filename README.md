# Project Structure

This document outlines the directory structure of the ROS 2 workspace.

```text
ros2_ws/
├── build/                   # ROS 2 build artifacts (can be safely ignored/deleted)
├── install/                 # ROS 2 installed targets and setup scripts (can be safely ignored/deleted)
├── log/                     # ROS 2 runtime logs (can be safely ignored/deleted)
└── src/                     # Source code directory for ROS 2 packages
    └── robot_control/       # Main package for robot control and telemetry
        ├── launch/          # ROS 2 launch files
        │   └── robot_core.launch.py   # Main launch file to start core nodes (joy, teleop, audio)
        ├── media/           # Audio assets for feedback
        │   ├── Alert.wav
        │   ├── Auto_mode.wav
        │   ├── Demo_mode.wav
        │   ├── Error_debug.wav
        │   ├── Internet_es.wav
        │   ├── Internet_Lost.wav
        │   ├── Manual_mode.wav
        │   ├── Starting.wav
        │   └── Underdeveloped_stopall.wav
        ├── package.xml      # ROS 2 package metadata and dependencies
        ├── resource/        # ROS 2 resource markers
        ├── robot_control/   # Python module containing the actual ROS 2 nodes
        │   ├── audio_feedback_manager.py  # Node for playing audio feedback
        │   ├── joy_to_esp32.py            # Node for mapping joystick to ESP32
        │   ├── kinematics.py              # Kinematics calculations for mecanum wheels
        │   ├── mecanum_joy_teleop.py      # Main teleop node handling joystick and kinematics
        │   ├── serial_controller.py       # Serial interface to communicate with ESP32
        │   ├── websocket_telemetry.py     # WebSocket/HTTP server for telemetry (SSL)
        │   ├── websocket_telemetry_funnel.py # WebSocket/HTTP server for telemetry (Funnel/No SSL)
        │   └── WebSp.md                   # Web dashboard UI source code
        ├── setup.cfg        # Python setup configuration
        ├── setup.py         # Python package setup and entry points (console_scripts)
        └── test/            # Auto-generated testing directory
```

## Description of Main Components
- **`mecanum_joy_teleop.py`**: The central brain that reads `/joy` topics, calculates wheel speeds using `kinematics.py`, and outputs them to the `/wheel_speeds` topic.
- **`websocket_telemetry.py`**: Runs a web server (WebSocket + HTTP) to feed live data to the `WebSp.md` dashboard. 
- **`audio_feedback_manager.py`**: Listens for state changes (like connection drops or mode switches) and plays audio cues from the `media/` folder using `aplay`.
- **`robot_core.launch.py`**: Brings up the entire system automatically.
