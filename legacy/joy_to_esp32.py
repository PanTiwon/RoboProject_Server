import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy

# นำเข้าคลาสที่แยกย่อยหน้าที่มาแล้ว
from kinematics import MecanumKinematics
from serial_controller import SerialController

class MecanumJoyTeleop(Node):
    """
    คลาสนี้เป็น ROS2 Node หลัก มีหน้าที่:
    1. รับข้อมูลจากจอยสติ๊ก (Subscribe)
    2. จัดเตรียมข้อมูล แล้วส่งให้ 'Kinematics' คำนวณ
    3. รับผลลัพธ์ที่คำนวณได้ ส่งให้ 'SerialController' ยิงเข้า ESP32
    """
    def __init__(self):
        super().__init__('mecanum_joy_teleop')
        
        # --- Configuration ---
        # Joy Axes Configuration (Standard PS4/Xbox Controller Mapping)
        self.axis_left_x = 0    # Left Analog X-axis (Strafe)
        self.axis_right_x = 3   # Right Analog X-axis (Yaw)
        self.axis_l2 = 2        # Left Trigger (Backward)
        self.axis_r2 = 5        # Right Trigger (Forward)
        
        # Joy Buttons Configuration
        self.btn_sweeper = 0    # 'A' or 'Cross' button to toggle sweeper
        
        # --- State Variables ---
        self.sweeper_on = False
        self.last_sweeper_button_state = 0
        
        # --- Instances of Helpers ---
        self.kinematics = MecanumKinematics(max_pwm=255.0)
        self.serial_ctrl = SerialController(port='/dev/ttyUSB0', baudrate=115200, logger=self.get_logger())
        
        # --- Subscribers ---
        self.joy_sub = self.create_subscription(
            Joy,
            '/joy',
            self.joy_callback,
            10
        )
        self.get_logger().info("Mecanum Joy Teleop Node initialized.")

    def joy_callback(self, msg):
        """
        ฟังก์ชันนี้จะถูกเรียกทุกครั้งที่มีการขยับจอยสติ๊ก
        """
        # 1. จัดการปุ่มทริกเกอร์ (L2 / R2) ให้อยู่ในช่วง 0.0 - 1.0
        r2_val = msg.axes[self.axis_r2]
        l2_val = msg.axes[self.axis_l2]
        
        forward = (1.0 - r2_val) / 2.0  
        backward = (1.0 - l2_val) / 2.0 
        
        v_x = forward - backward # เดินหน้า/ถอยหลัง
        v_y = msg.axes[self.axis_left_x]    # สไลด์ซ้าย/ขวา
        omega = msg.axes[self.axis_right_x] # หมุนซ้าย/ขวา
        
        # 2. ให้ Kinematics คำนวณความเร็วมอเตอร์
        pwm_speeds = self.kinematics.calculate_speeds(v_x, v_y, omega)
        
        # 3. จัดการสถานะการเปิด/ปิดไม้กวาด (กดปุ่มสลับสถานะ Toggle)
        current_sweeper_btn = msg.buttons[self.btn_sweeper]
        if current_sweeper_btn == 1 and self.last_sweeper_button_state == 0:
            self.sweeper_on = not self.sweeper_on
            self.get_logger().info(f"Sweeper toggled: {'ON' if self.sweeper_on else 'OFF'}")
        self.last_sweeper_button_state = current_sweeper_btn
        
        # 4. สั่งให้ SerialController ยิงข้อมูลออกไป
        self.serial_ctrl.send_command(pwm_speeds, self.sweeper_on)

def main(args=None):
    rclpy.init(args=args)
    node = MecanumJoyTeleop()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # ปิดระบบอย่างปลอดภัย
        node.serial_ctrl.stop_robot_and_close()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
