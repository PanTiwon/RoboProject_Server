from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        # 1. Start the Joy Node to read gamepad input
        Node(
            package='joy',
            executable='joy_node',
            name='joy_node'
        ),
        
        # 2. Start our custom Mecanum Teleop node (Handles ESP32 serial & CLI dashboard)
        Node(
            package='robot_control',
            executable='mecanum_joy_teleop',
            name='mecanum_joy_teleop',
            output='screen'
        ),
        
        # 3. Start the Audio Feedback Manager
        Node(
            package='robot_control',
            executable='audio_feedback_manager',
            name='audio_feedback_manager',
            output='screen'
        ),
        
        # 4. Start the WebSocket Telemetry Funnel (Web Server, Tailscale Funnel & Battery I2C)
        Node(
            package='robot_control',
            executable='websocket_telemetry_funnel',
            name='websocket_telemetry_funnel',
            output='screen'
        )
    ])
