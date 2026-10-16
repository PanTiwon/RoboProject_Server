#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import Int32MultiArray, Bool, Int32
import sys
import os
import time
from robot_control.serial_controller import SerialController
from robot_control.camera_firebase_manager import CameraFirebaseManager

class RobotMode:
    MANUAL = 0
    DEMO = 1
    AUTO = 2

class MecanumJoyTeleop(Node):
    def __init__(self):
        super().__init__('mecanum_joy_teleop')
        self.subscription = self.create_subscription(
            Joy,
            'joy',
            self.joy_callback,
            10)
            
        self.wheels_pub = self.create_publisher(
            Int32MultiArray,
            'wheel_speeds',
            10)
            
        self.mute_pub = self.create_publisher(Bool, '/audio/mute', 10)
        self.mode_pub = self.create_publisher(Int32, '/robot/mode', 10)
        
        self.bat_sub = self.create_subscription(Int32, 'battery_percent', self.battery_callback, 10)
        self.battery_percent = -1
        
        # State Machine
        self.current_mode = RobotMode.MANUAL
        
        # Button state tracking for edge detection
        self.last_action1_state = 0
        self.last_action2_state = 0
        self.last_action3_state = 0
        self.last_action_start_state = 0
        self.last_action_estop_state = 0
        self.last_action_recenter_state = 0
        self.last_speed_down_state = 0
        self.last_speed_up_state = 0
        
        # Camera Mount Angles
        self.yaw_angle = 0.0
        self.pitch_angle = 0.0
        
        # Robot States
        self.vacuum_active = False
        self.is_muted = False
        self.is_e_stop = False
        
        # Speed levels (Multiplier for max_speed)
        self.speed_levels = [0.25, 0.50, 0.75, 1.0]
        self.current_speed_idx = 3 # Start at 1.0 (100%)

        # Graceful Hardware Shutdown states
        self.shutdown_start_time = None
        self.shutdown_countdown_sec = 0.0
        self.is_shutting_down = False
        
        # Joystick mappings (standard PS4/Xbox mappings)
        self.declare_parameter('axis_forward', 5) # R2 (Right Trigger)
        self.declare_parameter('axis_backward', 2) # L2 (Left Trigger)
        self.declare_parameter('axis_strafe', 0) # Left Analog X
        self.declare_parameter('axis_rotate', 3) # Right Analog X
        self.declare_parameter('axis_dpad_x', 6) # D-pad Horizontal
        self.declare_parameter('axis_dpad_y', 7) # D-pad Vertical
        
        # Auto-detect Gamepad Layout (Xbox vs PlayStation)
        is_xbox = False
        try:
            if os.path.exists('/proc/bus/input/devices'):
                with open('/proc/bus/input/devices', 'r') as f:
                    content = f.read().lower()
                    if 'x-box' in content or 'xbox' in content or 'xinput' in content:
                        is_xbox = True
        except Exception:
            pass

        default_btn_estop = 2 if is_xbox else 3 # Left diamond button: X on Xbox (2), Square on PS (3)
        default_btn_mute = 3 if is_xbox else 2  # Top diamond button: Y on Xbox (3), Triangle on PS (2)
        
        self.declare_parameter('btn_photo', 0) # Bottom: Cross/A
        self.declare_parameter('btn_vacuum', 1) # Right: Circle/B
        self.declare_parameter('btn_mute', default_btn_mute) # Top: Triangle/Y
        self.declare_parameter('btn_estop', default_btn_estop) # Left: Square/X (E-Stop Toggle)
        self.declare_parameter('btn_mode', 6) # Action 3 / Mode Switch (Select / Share / Back)
        self.declare_parameter('btn_start', 7) # Start / Options
        self.declare_parameter('btn_speed_down', 4) # L1 (Left Bumper)
        self.declare_parameter('btn_speed_up', 5) # R1 (Right Bumper)
        self.declare_parameter('btn_recenter', 9) # L3 (Left Stick click - Camera Recenter)
        
        # Serial parameters
        self.declare_parameter('serial_port', '/dev/ttyACM0')
        self.declare_parameter('serial_baudrate', 115200)
        self.declare_parameter('max_speed', 255.0)
        
        serial_port = self.get_parameter('serial_port').value
        baudrate = self.get_parameter('serial_baudrate').value
        self.serial_ctrl = SerialController(port=serial_port, baudrate=baudrate, logger=self.get_logger())

        # Initialize Camera & Firebase Subsystem
        self.camera_manager = CameraFirebaseManager(
            cred_path="/home/spark/firebase_key.json",
            database_url="https://roboproject1-a9c63-default-rtdb.asia-southeast1.firebasedatabase.app/",
            # processing_mode="OPENCV_OCR",  # Uncomment to override DEFAULT_PROCESSING_MODE from the class
            logger=self.get_logger()
        )

        self.get_logger().info("Mecanum Joy Teleop Node Started.")
        self.print_mode_status()
        
        # Store latest joy message
        self.last_joy_msg = None
        
        # Create a 20Hz control loop
        self.create_timer(0.05, self.control_loop)

    def map_trigger(self, val):
        # joy_node typically maps triggers from 1.0 (unpressed) to -1.0 (fully pressed)
        return (1.0 - val) / 2.0

    def battery_callback(self, msg):
        self.battery_percent = msg.data

    def joy_callback(self, msg):
        self.last_joy_msg = msg

    def control_loop(self):
        if self.last_joy_msg is None:
            return
            
        msg = self.last_joy_msg
        
        # Extract indices
        axis_fwd = self.get_parameter('axis_forward').value
        axis_bwd = self.get_parameter('axis_backward').value
        axis_strafe = self.get_parameter('axis_strafe').value
        axis_rot = self.get_parameter('axis_rotate').value
        axis_dpad_x = self.get_parameter('axis_dpad_x').value
        axis_dpad_y = self.get_parameter('axis_dpad_y').value
        
        btn_photo_idx = self.get_parameter('btn_photo').value
        btn_vacuum_idx = self.get_parameter('btn_vacuum').value
        btn_mute_idx = self.get_parameter('btn_mute').value
        btn_estop_idx = self.get_parameter('btn_estop').value
        btn_mode_idx = self.get_parameter('btn_mode').value
        btn_start_idx = self.get_parameter('btn_start').value
        btn_speed_down_idx = self.get_parameter('btn_speed_down').value
        btn_speed_up_idx = self.get_parameter('btn_speed_up').value
        btn_recenter_idx = self.get_parameter('btn_recenter').value
        
        # Get raw values
        try:
            fwd_val = self.map_trigger(msg.axes[axis_fwd])
            bwd_val = self.map_trigger(msg.axes[axis_bwd])
            strafe_val = msg.axes[axis_strafe] 
            rot_val = msg.axes[axis_rot] 
            dpad_x_val = msg.axes[axis_dpad_x]
            dpad_y_val = msg.axes[axis_dpad_y]
        except IndexError:
            fwd_val = bwd_val = strafe_val = rot_val = dpad_x_val = dpad_y_val = 0.0

        try:
            action1 = msg.buttons[btn_photo_idx] if len(msg.buttons) > btn_photo_idx else 0
            action2 = msg.buttons[btn_vacuum_idx] if len(msg.buttons) > btn_vacuum_idx else 0
            action_mute = msg.buttons[btn_mute_idx] if len(msg.buttons) > btn_mute_idx else 0
            action_estop = msg.buttons[btn_estop_idx] if len(msg.buttons) > btn_estop_idx else 0
            action3 = msg.buttons[btn_mode_idx] if len(msg.buttons) > btn_mode_idx else 0
            action_start = msg.buttons[btn_start_idx] if len(msg.buttons) > btn_start_idx else 0
            speed_down = msg.buttons[btn_speed_down_idx] if len(msg.buttons) > btn_speed_down_idx else 0
            speed_up = msg.buttons[btn_speed_up_idx] if len(msg.buttons) > btn_speed_up_idx else 0
            action_recenter = msg.buttons[btn_recenter_idx] if len(msg.buttons) > btn_recenter_idx else 0
        except IndexError:
            action1 = action2 = action_mute = action_estop = action3 = action_start = speed_down = speed_up = action_recenter = 0

        # Edge detection for buttons
        action1_pressed = (action1 == 1 and self.last_action1_state == 0)
        action2_pressed = (action2 == 1 and self.last_action2_state == 0)
        action_mute_pressed = (action_mute == 1 and getattr(self, 'last_action_mute_state', 0) == 0)
        action_estop_pressed = (action_estop == 1 and getattr(self, 'last_action_estop_state', 0) == 0)
        action3_pressed = (action3 == 1 and self.last_action3_state == 0)
        action_start_pressed = (action_start == 1 and self.last_action_start_state == 0)
        speed_down_pressed = (speed_down == 1 and self.last_speed_down_state == 0)
        speed_up_pressed = (speed_up == 1 and self.last_speed_up_state == 0)
        action_recenter_pressed = (action_recenter == 1 and getattr(self, 'last_action_recenter_state', 0) == 0)

        self.last_action1_state = action1
        self.last_action2_state = action2
        self.last_action_mute_state = action_mute
        self.last_action_estop_state = action_estop
        self.last_action3_state = action3
        self.last_action_start_state = action_start
        self.last_speed_down_state = speed_down
        self.last_speed_up_state = speed_up
        self.last_action_recenter_state = action_recenter
        
        # Speed Control (L1 / R1) - Only adjust speed if NOT holding both together (which is shutdown combo)
        if speed_down_pressed and not speed_up:
            self.current_speed_idx = max(0, self.current_speed_idx - 1)
        if speed_up_pressed and not speed_down:
            self.current_speed_idx = min(len(self.speed_levels) - 1, self.current_speed_idx + 1)
        
        # Check L1 and R1 combo for graceful shutdown
        # L1 is Button 4 (btn_speed_down), R1 is Button 5 (btn_speed_up)
        l1_held = (len(msg.buttons) > btn_speed_down_idx and msg.buttons[btn_speed_down_idx] == 1)
        r1_held = (len(msg.buttons) > btn_speed_up_idx and msg.buttons[btn_speed_up_idx] == 1)
        combo_held = l1_held and r1_held

        # Action 3: Cycle modes
        if action3_pressed:
            # Stop the robot immediately when leaving a mode that could be moving it
            self.serial_ctrl.send_command([0, 0, 0, 0], self.vacuum_active, self.yaw_angle, self.pitch_angle)
            
            if self.current_mode == RobotMode.MANUAL:
                self.current_mode = RobotMode.DEMO
            elif self.current_mode == RobotMode.DEMO:
                self.current_mode = RobotMode.AUTO
            else:
                self.current_mode = RobotMode.MANUAL
            
            # Notify audio manager of mode change
            mode_msg = Int32()
            mode_msg.data = self.current_mode
            self.mode_pub.publish(mode_msg)
            
            # Clear screen when switching modes
            sys.stdout.write('\033[2J\033[H')
            sys.stdout.flush()

        # Action Mute Toggle
        if action_mute_pressed:
            self.is_muted = not self.is_muted
            mute_msg = Bool()
            mute_msg.data = self.is_muted
            self.mute_pub.publish(mute_msg)

        # Action Start: Toggle FPV Stream
        if action_start_pressed:
            self.camera_manager.toggle_stream()

        # Action 1: Photo
        photo_trigger = action1_pressed
        if action1_pressed:
            self.camera_manager.capture_and_upload_task(self.pitch_angle)

        # Action 2: Vacuum Toggle
        if action2_pressed:
            self.vacuum_active = not self.vacuum_active

        # Action E-Stop Toggle (Square / X - Button Index 3)
        if action_estop_pressed:
            self.is_e_stop = not self.is_e_stop
            if self.is_e_stop:
                self.get_logger().warn("🚨 [E-STOP] EMERGENCY BRAKE ENGAGED! All motors locked to 0.")
                self.serial_ctrl.send_command([0, 0, 0, 0], self.vacuum_active, self.yaw_angle, self.pitch_angle)
            else:
                self.get_logger().info("✅ [E-STOP] Emergency brake released. Normal drive controls unlocked.")

        # Action Recenter Camera with Offset (L3 - Button Index 9)
        if action_recenter_pressed:
            self.yaw_angle = 0.0
            self.pitch_angle = 8.0
            self.camera_manager.current_yaw = int(self.yaw_angle)
            self.camera_manager.current_pitch = int(self.pitch_angle)
            self.get_logger().info("📷 [CAMERA] Recenter: Yaw=0.0°, Pitch=8.0° (Hardware Offset)")
        else:
            # Continuous Camera Yaw/Pitch Control via D-pad (approx 2 degrees per 0.05s tick = 40 deg/sec)
            if dpad_x_val > 0.5:
                self.yaw_angle = min(90.0, self.yaw_angle + 2.0)
            elif dpad_x_val < -0.5:
                self.yaw_angle = max(-90.0, self.yaw_angle - 2.0)
                
            if dpad_y_val > 0.5:
                self.pitch_angle = min(90.0, self.pitch_angle + 2.0)
            elif dpad_y_val < -0.5:
                self.pitch_angle = max(-30.0, self.pitch_angle - 2.0)
                
            self.camera_manager.current_yaw = int(self.yaw_angle)
            self.camera_manager.current_pitch = int(self.pitch_angle)

        # Compute combined linear_x
        linear_x = fwd_val - bwd_val
        linear_y = strafe_val
        angular_z = rot_val

        # Safety Interlock: check if robot is stationary (0.15 deadzone to eliminate analog stick resting drift)
        is_stationary = (abs(fwd_val) < 0.15 and abs(bwd_val) < 0.15 and abs(strafe_val) < 0.15 and abs(rot_val) < 0.15)
        
        # Save state for dashboard display
        self.last_l1_held = l1_held
        self.last_r1_held = r1_held
        self.last_is_stationary = is_stationary

        # Graceful Hardware Shutdown Logic (Safety Interlock)
        current_time = time.time()
        if combo_held and is_stationary and not self.is_shutting_down:
            if self.shutdown_start_time is None:
                self.shutdown_start_time = current_time
                self.get_logger().warn("[POWER] Hold L1 + R1 for 5 seconds to SHUTDOWN...")

            elapsed = current_time - self.shutdown_start_time
            self.shutdown_countdown_sec = max(0.0, 5.0 - elapsed)

            if elapsed >= 5.0:
                self.is_shutting_down = True
                self.get_logger().error("==================================================")
                self.get_logger().error("🛑 [POWER] GRACEFUL HARDWARE SHUTDOWN TRIGGERED!")
                self.get_logger().error("==================================================")

                # 1) Stop all motors immediately
                self.serial_ctrl.send_command([0, 0, 0, 0], False, self.yaw_angle, self.pitch_angle)

                # 2) Flush filesystem buffers to disk immediately
                self.get_logger().info("Flushing file system buffers (sync)...")
                os.system("sync")

                # 3) Command Waveshare UPS HAT via I2C (Address 0x2d) to cut 5V power in 30 seconds
                self.get_logger().info("Sending I2C cut-off command to Waveshare UPS HAT (0x2d)...")
                os.system("sudo i2cset -y 1 0x2d 0x01 0x55 || i2cset -y 1 0x2d 0x01 0x55")

                # 4) Gracefully power off the Ubuntu OS
                self.get_logger().info("Executing system poweroff...")
                os.system("sudo poweroff || sudo systemctl poweroff || systemctl poweroff")
        else:
            if self.shutdown_start_time is not None and not self.is_shutting_down:
                self.get_logger().info("[POWER] Shutdown canceled (buttons released or robot moved).")
            self.shutdown_start_time = None
            self.shutdown_countdown_sec = 0.0

        # If shutting down or E-Stop is active, lock all wheel velocities to 0
        if self.is_shutting_down or self.is_e_stop:
            linear_x = linear_y = angular_z = 0.0

        # Execute Mode Logic
        if self.current_mode == RobotMode.AUTO:
            self.execute_auto_mode()
        else:
            # Calculate raw intended speeds
            if self.is_e_stop:
                v_fl = v_fr = v_rl = v_rr = 0
            else:
                v_fl, v_fr, v_rl, v_rr = self.calculate_kinematics(linear_x, linear_y, angular_z)
            
            # Safety Logic: Check if ESP32 is actually connected
            is_esp32_connected = (self.serial_ctrl.ser is not None and self.serial_ctrl.ser.is_open)
            
            if self.current_mode == RobotMode.MANUAL:
                if is_esp32_connected:
                    self.serial_ctrl.send_command([v_fl, v_fr, v_rl, v_rr], self.vacuum_active, self.yaw_angle, self.pitch_angle)
                else:
                    # In Manual mode, if hardware is disconnected, wheels cannot move physically
                    v_fl = v_fr = v_rl = v_rr = 0
            
            # Publish wheel speeds and mode for the WebSocket node to catch
            wheels_msg = Int32MultiArray()
            wheels_msg.data = [v_fl, v_fr, v_rl, v_rr, self.current_mode, 1 if self.vacuum_active else 0]
            self.wheels_pub.publish(wheels_msg)
            
            # Show Dashboard for BOTH modes!
            self.render_dashboard(linear_x, linear_y, angular_z, v_fl, v_fr, v_rl, v_rr, photo_trigger)

    def print_mode_status(self):
        pass # Status is now strictly shown on the Dashboard UI

    def calculate_kinematics(self, vx, vy, wz):
        v_fl_raw = vx - vy - wz
        v_fr_raw = vx + vy + wz
        v_rl_raw = vx + vy - wz
        v_rr_raw = vx - vy + wz
        
        # Scale to max_speed based on current speed level multiplier
        base_max_speed = self.get_parameter('max_speed').value
        current_multiplier = self.speed_levels[self.current_speed_idx]
        actual_max_speed = base_max_speed * current_multiplier
        
        # Normalize
        max_val = max(abs(v_fl_raw), abs(v_fr_raw), abs(v_rl_raw), abs(v_rr_raw), 1.0)
        
        v_fl = int((v_fl_raw / max_val) * actual_max_speed)
        v_fr = int((v_fr_raw / max_val) * actual_max_speed)
        v_rl = int((v_rl_raw / max_val) * actual_max_speed)
        v_rr = int((v_rr_raw / max_val) * actual_max_speed)
        
        return v_fl, v_fr, v_rl, v_rr

    def render_dashboard(self, vx, vy, wz, v_fl, v_fr, v_rl, v_rr, photo_trigger):
        sys.stdout.write('\033[H')
        
        mode_str = "MANUAL (Active ESP32)" if self.current_mode == RobotMode.MANUAL else "DEMO (Simulation Only)"
        
        # Speed bar visualization e.g. [||||] 100%
        speed_bars = "|" * (self.current_speed_idx + 1)
        speed_spaces = " " * (len(self.speed_levels) - (self.current_speed_idx + 1))
        speed_percent = int(self.speed_levels[self.current_speed_idx] * 100)
        
        print(f"=========================================")
        print(f"      MECANUM DASHBOARD : {mode_str}      ")
        print(f"=========================================")
        
        link_str = f"[ CONNECTED ({self.serial_ctrl.port}) ]" if self.serial_ctrl.is_connected() else "[ DISCONNECTED ]"
        print(f"  ESP32 Link     : {link_str}")
        bat_str = f"{self.battery_percent}%" if self.battery_percent >= 0 else "WAITING..."
        print(f"  Battery Level  : [ {bat_str} ]")
        estop_str = "🚨 [ ENGAGED (STOPPED) ]" if self.is_e_stop else "[ OFF (NORMAL) ]"
        print(f"  E-Stop Status  : {estop_str}")
        print(f"  Vacuum Status : {'[ ON ] ' if self.vacuum_active else '[ OFF ]'}")
        print(f"  Camera Mount   : Yaw [ {int(self.yaw_angle):>3}° ] Pitch [ {int(self.pitch_angle):>3}° ]")
        print(f"  FPV Stream     : {'[ WEBRTC LIVE ] (WHEP :8889)' if self.camera_manager.is_streaming else '[ OFF ] (Press Start)'}")
        print(f"  Audio Status   : {'[ MUTED ]' if self.is_muted else '[ UNMUTED ]'}")
        print(f"  Photo Trigger  : {'* CLICK *' if photo_trigger else 'Ready    '}")
        print(f"  Speed Level    : [{speed_bars}{speed_spaces}] {speed_percent}%  (L1/R1 to Adjust)")
        
        # Display Hardware Shutdown State with diagnostic feedback
        if self.is_shutting_down:
            pwr_msg = "🛑 SHUTTING DOWN (Power off in 30s)"
        elif self.shutdown_start_time is not None:
            pwr_msg = f"⏳ HOLDING L1+R1... {self.shutdown_countdown_sec:.1f}s"
        elif getattr(self, 'last_l1_held', False) and not getattr(self, 'last_r1_held', False):
            pwr_msg = "L1 PRESSED (Also hold R1 to Shutdown)"
        elif getattr(self, 'last_r1_held', False) and not getattr(self, 'last_l1_held', False):
            pwr_msg = "R1 PRESSED (Also hold L1 to Shutdown)"
        elif getattr(self, 'last_l1_held', False) and getattr(self, 'last_r1_held', False) and not getattr(self, 'last_is_stationary', False):
            pwr_msg = "L1+R1 HELD BUT ROBOT MOVING (Stop sticks!)"
        else:
            pwr_msg = "READY (Hold L1+R1 5s to Shutdown)"
        print(f"  Shutdown Timer : [ {pwr_msg} ]")
        print(f"-----------------------------------------")
        
        dir_str = "STOPPED     "
        if self.is_e_stop:
            dir_str = "🚨 E-STOPPED"
        elif abs(vx) > 0.1 or abs(vy) > 0.1 or abs(wz) > 0.1:
            if vx > 0.5: dir_str = "FORWARD     "
            elif vx < -0.5: dir_str = "BACKWARD    "
            elif vy > 0.5: dir_str = "STRAFE LEFT "
            elif vy < -0.5: dir_str = "STRAFE RIGHT"
            elif wz > 0.5: dir_str = "ROTATE LEFT "
            elif wz < -0.5: dir_str = "ROTATE RIGHT"
            else: dir_str = "MOVING      "

        print(f"  Motion State   : {dir_str}")
        print(f"  Joystick Input : X:{vx:>5.2f}  Y:{vy:>5.2f}  W:{wz:>5.2f}")
        print(f"=========================================\n")

        # Visual arrows
        arr_up = "   /\\   " if vx > 0.1 else "        "
        arr_dn = "   \\/   " if vx < -0.1 else "        "
        arr_l  = "<<" if vy > 0.1 else "  "
        arr_r  = ">>" if vy < -0.1 else "  "
        
        rot_l = "(O " if wz > 0.1 else "   "
        rot_r = " O)" if wz < -0.1 else "   "

        # Display Robot and actual Wheel PWM values in the ASCII art
        print(f"              {arr_up}")
        print(f"      [FL:{v_fl:>4}]--[FR:{v_fr:>4}]")
        print(f"   {arr_l}  {rot_l} |        | {rot_r}  {arr_r}")
        print(f"      [RL:{v_rl:>4}]--[RR:{v_rr:>4}]")
        print(f"              {arr_dn}\n")
        
        sys.stdout.write('\033[J')
        sys.stdout.flush()

    def execute_auto_mode(self):
        self.serial_ctrl.send_command([0, 0, 0, 0], self.vacuum_active, self.yaw_angle, self.pitch_angle)
        
        wheels_msg = Int32MultiArray()
        wheels_msg.data = [0, 0, 0, 0, self.current_mode, 1 if self.vacuum_active else 0]
        self.wheels_pub.publish(wheels_msg)
        
        sys.stdout.write('\033[H')
        print(f"=========================================")
        print(f"      MECANUM DASHBOARD : AUTO MODE      ")
        print(f"=========================================")
        print(f"  Status : Under Development             ")
        print(f"  Robot  : COMPLETELY STOPPED            ")
        print(f"=========================================\n")
        sys.stdout.write('\033[J')
        sys.stdout.flush()

    def destroy_node(self):
        # Clear screen and show exit message so traceback doesn't mangle dashboard
        sys.stdout.write('\033[2J\033[H')
        print("Shutting down Mecanum Joy Teleop gracefully...")
        sys.stdout.flush()
        
        self.serial_ctrl.stop_robot_and_close()
        super().destroy_node()

def main(args=None):
    # Hack to bypass ROS 2 launch stdout capture (which adds [node-name] prefix and breaks ASCII art)
    if not os.isatty(sys.stdout.fileno()):
        try:
            sys.stdout = open('/dev/tty', 'w')
        except Exception:
            pass

    rclpy.init(args=args)
    node = MecanumJoyTeleop()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
