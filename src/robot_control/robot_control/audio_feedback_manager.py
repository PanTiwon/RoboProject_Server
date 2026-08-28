#!/usr/bin/env python3

import os
import threading
import subprocess
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String, Int32

class AudioFeedbackManager(Node):
    def __init__(self):
        super().__init__('audio_feedback_manager')
        
        # --- Parameters ---
        self.declare_parameter('media_dir', '/home/spark/ros2_ws/src/robot_control/media')
        self.media_dir = self.get_parameter('media_dir').value
        
        # --- State Variables ---
        self.is_muted = False
        self.current_playback = None
        
        # --- Subscriptions ---
        # Mute toggle topic (Expects a Bool message: True to mute, False to unmute)
        self.mute_sub = self.create_subscription(
            Bool,
            '/audio/mute',
            self.mute_callback,
            10
        )
        
        # Mode change topic (Assuming it receives Int32 where 0=Manual, 1=Demo, 2=Auto)
        self.mode_sub = self.create_subscription(
            Int32,
            '/robot/mode',
            self.mode_callback,
            10
        )
        
        # Error state topic
        self.error_sub = self.create_subscription(
            Bool,
            '/robot/error',
            self.error_callback,
            10
        )
        
        # Internet status topic
        self.internet_sub = self.create_subscription(
            Bool,
            '/robot/internet_status',
            self.internet_callback,
            10
        )
        
        # Emergency stop topic
        self.emergency_sub = self.create_subscription(
            Bool,
            '/robot/emergency',
            self.emergency_callback,
            10
        )
        
        self.get_logger().info("Audio Feedback Manager Initialized.")
        
        # Play startup sound
        self.play_sound('Starting.wav')

    def mute_callback(self, msg):
        """Callback to toggle mute status."""
        self.is_muted = msg.data
        if self.is_muted:
            self.get_logger().info("Audio Status: [MUTED] - All sounds will be bypassed.")
            self._stop_current_playback()
        else:
            self.get_logger().info("Audio Status: [UNMUTED] - Sounds enabled.")

    def play_sound(self, filename, block=False):
        """
        Plays an audio file using 'aplay' (standard Linux ALSA player).
        If block is True, it waits for the audio to finish.
        If block is False, it runs in the background.
        """
        if self.is_muted:
            self.get_logger().info(f"Audio Bypassed (Muted): {filename}")
            return

        filepath = os.path.join(self.media_dir, filename)
        
        if not os.path.exists(filepath):
            self.get_logger().warn(f"Audio file not found: {filepath}")
            return
            
        self.get_logger().info(f"Playing Audio: {filename}")
        
        try:
            # We use 'aplay' for .wav files on Linux
            if block:
                subprocess.run(['aplay', '-q', filepath])
            else:
                self._stop_current_playback() # Stop previous non-blocking sound if any
                self.current_playback = subprocess.Popen(['aplay', '-q', filepath])
        except Exception as e:
            self.get_logger().error(f"Failed to play audio {filename}: {e}")

    def _stop_current_playback(self):
        """Stops the currently playing audio if it's running."""
        if self.current_playback and self.current_playback.poll() is None:
            self.current_playback.terminate()
            self.current_playback = None

    def play_auto_mode_sequence(self):
        """
        Special sequence for Auto Mode.
        Plays Auto_mode.wav, blocks until finished, then plays Underdeveloped_stopall.wav.
        Runs in a background thread so it doesn't block the ROS2 main loop.
        """
        if self.is_muted:
            self.get_logger().info("Audio Bypassed (Muted): Auto Mode Sequence")
            return

        def sequence_thread():
            self.get_logger().info("Starting Auto Mode Audio Sequence...")
            # Play first file and wait for it to finish
            self.play_sound('Auto_mode.wav', block=True)
            # Immediately play second file
            self.play_sound('Underdeveloped_stopall.wav', block=True)
            self.get_logger().info("Auto Mode Audio Sequence Complete.")
            
        # Start the sequence in a separate thread to keep ROS2 non-blocking
        threading.Thread(target=sequence_thread, daemon=True).start()

    # --- Feature Callbacks ---

    def mode_callback(self, msg):
        """Triggered when robot mode changes."""
        mode = msg.data
        if mode == 0:
            self.play_sound('Manual_mode.wav')
        elif mode == 1:
            self.play_sound('Demo_mode.wav')
        elif mode == 2:
            self.play_auto_mode_sequence()

    def internet_callback(self, msg):
        """Triggered when internet status changes (True=Connected, False=Disconnected)."""
        is_connected = msg.data
        if is_connected:
            self.play_sound('Internet_es.wav')
        else:
            self.play_sound('Internet_Lost.wav')

    def error_callback(self, msg):
        """Triggered on error state."""
        has_error = msg.data
        if has_error:
            self.play_sound('Error_debug.wav')

    def emergency_callback(self, msg):
        """Placeholder function for Emergency Stop."""
        is_emergency = msg.data
        if is_emergency:
            self.play_sound('Alert.wav')
            self.get_logger().warn("EMERGENCY STOP TRIGGERED! Playing Alert sound.")

def main(args=None):
    rclpy.init(args=args)
    node = AudioFeedbackManager()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Shutting down Audio Feedback Manager.")
    finally:
        node._stop_current_playback()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
