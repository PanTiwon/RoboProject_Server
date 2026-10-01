import serial
import time

class SerialController:
    """
    คลาสนี้รับผิดชอบเรื่องการส่งข้อมูลผ่านสาย USB (Serial) ไปยัง ESP32 เท่านั้น
    """
    def __init__(self, port='/dev/ttyUSB0', baudrate=115200, logger=None):
        self.port = port
        self.baudrate = baudrate
        self.logger = logger
        self.ser = None
        self.connect()

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            if self.logger:
                self.logger.info(f"Successfully connected to ESP32 on {self.port}")
            time.sleep(2) # Wait for ESP32 to reset upon serial connection
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to connect to ESP32: {e}")

    def send_command(self, speeds, vacuum_on, yaw=0.0, pitch=0.0):
        """
        แปลงข้อมูลตัวเลขให้เป็น String รูปแบบ <M1,M2,M3,M4,Vacuum,Yaw,Pitch> แล้วส่งไป
        :param speeds: list ความเร็วมอเตอร์ [M1, M2, M3, M4]
        :param vacuum_on: boolean เปิด/ปิดมอเตอร์ดูดฝุ่น (True/False)
        :param yaw: float มุม Yaw ของกล้อง (-90 ถึง 90) X
        :param pitch: float มุม Pitch ของกล้อง (-90 ถึง 90) Y
        """
        if not self.ser or not self.ser.is_open:
            return

        # Relay control: 1 = ON, 0 = OFF
        vacuum_val = 1 if vacuum_on else 0
        payload = f"<{speeds[0]},{speeds[1]},{speeds[2]},{speeds[3]},{vacuum_val},{int(yaw)},{int(pitch)}>\n"
        
        try:
            self.ser.write(payload.encode('utf-8'))
        except Exception as e:
            if self.logger:
                self.logger.error(f"Serial write error: {e}")

    def stop_robot_and_close(self):
        """ส่งคำสั่งให้หุ่นหยุดนิ่ง แล้วปิดการเชื่อมต่อ Serial อย่างปลอดภัย"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(b"<0,0,0,0,0,0,0>\n")
            except:
                pass
            self.ser.close()