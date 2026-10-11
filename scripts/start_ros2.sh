#!/usr/bin/env bash
# ==============================================================================
# Robot ROS 2 Startup Script
# Automatically sources ROS 2 environment & launches robot_core stack
# ==============================================================================

set -e

# 1. Source System ROS 2 Environment (auto-detect jazzy, humble, iron, etc.)
ROS_DISTRO_PATH=""
for d in /opt/ros/*; do
    if [ -f "$d/setup.bash" ]; then
        ROS_DISTRO_PATH="$d"
        break
    fi
done

if [ -n "$ROS_DISTRO_PATH" ]; then
    echo "[start_ros2] Sourcing ROS 2 distro from $ROS_DISTRO_PATH/setup.bash"
    source "$ROS_DISTRO_PATH/setup.bash"
else
    echo "[start_ros2] ERROR: No ROS 2 installation found under /opt/ros/!" >&2
    exit 1
fi

# 2. Source Workspace Setup
WS_SETUP="/home/spark/ros2_ws/install/setup.bash"
if [ -f "$WS_SETUP" ]; then
    echo "[start_ros2] Sourcing workspace from $WS_SETUP"
    source "$WS_SETUP"
else
    echo "[start_ros2] ERROR: Workspace setup not found at $WS_SETUP. Did you run colcon build?" >&2
    exit 1
fi

# 3. Environment Variables
export PYTHONUNBUFFERED=1
export RCUTILS_COLORIZED_OUTPUT=1

# 4. Launch Full Stack
echo "[start_ros2] Launching robot_core.launch.py..."
exec ros2 launch robot_control robot_core.launch.py
