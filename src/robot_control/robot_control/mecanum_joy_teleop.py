#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import Int32MultiArray, Bool, Int32
import sys
import os
from robot_control.serial_controller import SerialController

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
        
        # State Machine
        self.current_mode = RobotMode.MANUAL
        
        # Button state tracking for edge detection
        self.last_action1_state = 0
        self.last_action2_state = 0
        self.last_action3_state = 0
        self.last_speed_down_state = 0
        self.last_speed_up_state = 0
        
        # Robot States
        self.sweeper_active = False
        self.is_muted = False
        
        # Speed levels (Multiplier for max_speed)
        self.speed_levels = [0.25, 0.50, 0.75, 1.0]
        self.current_speed_idx = 3 # Start at 1.0 (100%)
        
        # Joystick mappings (standard PS4/Xbox mappings)
        self.declare_parameter('axis_forward', 5) # R2 (Right Trigger)
        self.declare_parameter('axis_backward', 2) # L2 (Left Trigger)
        self.declare_parameter('axis_strafe', 0) # Left Analog X
        self.declare_parameter('axis_rotate', 3) # Right Analog X
        
        self.declare_parameter('btn_photo', 0) # Action 1 (Cross/A)
        self.declare_parameter('btn_sweeper', 1) # Action 2 (Circle/B)
        self.declare_parameter('btn_mute', 2) # Action 4 (Triangle/Y)
        self.declare_parameter('btn_mode', 6) # Action 3 / Mode Switch (Select / Share / Back)
        self.declare_parameter('btn_speed_down', 4) # L1 (Left Bumper)
        self.declare_parameter('btn_speed_up', 5) # R1 (Right Bumper)
        
        # Serial parameters
        self.declare_parameter('serial_port', '/dev/ttyUSB0')
        self.declare_parameter('serial_baudrate', 115200)
        self.declare_parameter('max_speed', 255.0)
        
        serial_port = self.get_parameter('serial_port').value
        baudrate = self.get_parameter('serial_baudrate').value
        self.serial_ctrl = SerialController(port=serial_port, baudrate=baudrate, logger=self.get_logger())

        self.get_logger().info("Mecanum Joy Teleop Node Started.")
        self.print_mode_status()

    def map_trigger(self, val):
        # joy_node typically maps triggers from 1.0 (unpressed) to -1.0 (fully pressed)
        return (1.0 - val) / 2.0

    def joy_callback(self, msg):
        # Extract indices
        axis_fwd = self.get_parameter('axis_forward').value
        axis_bwd = self.get_parameter('axis_backward').value
        axis_strafe = self.get_parameter('axis_strafe').value
        axis_rot = self.get_parameter('axis_rotate').value
        
        btn_photo_idx = self.get_parameter('btn_photo').value
        btn_sweeper_idx = self.get_parameter('btn_sweeper').value
        btn_mute_idx = self.get_parameter('btn_mute').value
        btn_mode_idx = self.get_parameter('btn_mode').value
        btn_speed_down_idx = self.get_parameter('btn_speed_down').value
        btn_speed_up_idx = self.get_parameter('btn_speed_up').value
        
        # Get raw values
        try:
            fwd_val = self.map_trigger(msg.axes[axis_fwd])
            bwd_val = self.map_trigger(msg.axes[axis_bwd])
            strafe_val = msg.axes[axis_strafe] 
            rot_val = msg.axes[axis_rot] 
        except IndexError:
            fwd_val = bwd_val = strafe_val = rot_val = 0.0

        try:
            action1 = msg.buttons[btn_photo_idx]
            action2 = msg.buttons[btn_sweeper_idx]
            action_mute = msg.buttons[btn_mute_idx]
            action3 = msg.buttons[btn_mode_idx]
            speed_down = msg.buttons[btn_speed_down_idx]
            speed_up = msg.buttons[btn_speed_up_idx]
        except IndexError:
            action1 = action2 = action_mute = action3 = speed_down = speed_up = 0

        # Edge detection for buttons
        action1_pressed = (action1 == 1 and self.last_action1_state == 0)
        action2_pressed = (action2 == 1 and self.last_action2_state == 0)
        action_mute_pressed = (action_mute == 1 and getattr(self, 'last_action_mute_state', 0) == 0)
        action3_pressed = (action3 == 1 and self.last_action3_state == 0)
        speed_down_pressed = (speed_down == 1 and self.last_speed_down_state == 0)
        speed_up_pressed = (speed_up == 1 and self.last_speed_up_state == 0)

        self.last_action1_state = action1
        self.last_action2_state = action2
        self.last_action_mute_state = action_mute
        self.last_action3_state = action3
        self.last_speed_down_state = speed_down
        self.last_speed_up_state = speed_up
        
        # Speed Control (L1 / R1)
        if speed_down_pressed:
            self.current_speed_idx = max(0, self.current_speed_idx - 1)
        if speed_up_pressed:
            self.current_speed_idx = min(len(self.speed_levels) - 1, self.current_speed_idx + 1)
        
        # Action 3: Cycle modes
        if action3_pressed:
            # Stop the robot immediately when leaving a mode that could be moving it
            self.serial_ctrl.send_command([0, 0, 0, 0], self.sweeper_active)
            
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

        # Action 1: Photo
        photo_trigger = action1_pressed
        if action1_pressed:
            pass # Implement photo logic here

        # Action 2: Sweeper Toggle
        if action2_pressed:
            self.sweeper_active = not self.sweeper_active

        # Compute combined linear_x
        linear_x = fwd_val - bwd_val
        linear_y = strafe_val
        angular_z = rot_val

        # Execute Mode Logic
        if self.current_mode == RobotMode.AUTO:
            self.execute_auto_mode()
        else:
            # Calculate raw intended speeds
            v_fl, v_fr, v_rl, v_rr = self.calculate_kinematics(linear_x, linear_y, angular_z)
            
            # Safety Logic: Check if ESP32 is actually connected
            is_esp32_connected = (self.serial_ctrl.ser is not None and self.serial_ctrl.ser.is_open)
            
            if self.current_mode == RobotMode.MANUAL:
                if is_esp32_connected:
                    self.serial_ctrl.send_command([v_fl, v_fr, v_rl, v_rr], self.sweeper_active)
                else:
                    # In Manual mode, if hardware is disconnected, wheels cannot move physically
                    v_fl = v_fr = v_rl = v_rr = 0
            
            # Publish wheel speeds and mode for the WebSocket node to catch
            wheels_msg = Int32MultiArray()
            wheels_msg.data = [v_fl, v_fr, v_rl, v_rr, self.current_mode, 1 if self.sweeper_active else 0]
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
        print(f"  Sweeper Status : {'[ ON ] ' if self.sweeper_active else '[ OFF ]'}")
        print(f"  Audio Status   : {'[ MUTED ]' if self.is_muted else '[ UNMUTED ]'}")
        print(f"  Photo Trigger  : {'* CLICK *' if photo_trigger else 'Ready    '}")
        print(f"  Speed Level    : [{speed_bars}{speed_spaces}] {speed_percent}%  (L1/R1 to Adjust)")
        print(f"-----------------------------------------")
        
        dir_str = "STOPPED     "
        if abs(vx) > 0.1 or abs(vy) > 0.1 or abs(wz) > 0.1:
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
        self.serial_ctrl.send_command([0, 0, 0, 0], self.sweeper_active)
        
        wheels_msg = Int32MultiArray()
        wheels_msg.data = [0, 0, 0, 0, self.current_mode, 1 if self.sweeper_active else 0]
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
