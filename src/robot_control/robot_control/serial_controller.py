import serial
import serial.tools.list_ports
import time
import os
import glob

def find_esp32_port(preferred_port=None):
    """
    Finds the active serial port for ESP32.
    Checks preferred_port first, then candidate ports (/dev/ttyACM*, /dev/ttyUSB*),
    and filters by known USB vendor IDs or descriptions if multiple exist.
    """
    if preferred_port and os.path.exists(preferred_port):
        return preferred_port
        
    candidates = []
    for pattern in ['/dev/ttyACM*', '/dev/ttyUSB*']:
        candidates.extend(glob.glob(pattern))
        
    if not candidates:
        return preferred_port or '/dev/ttyACM0'
        
    if len(candidates) == 1:
        return candidates[0]
        
    for p in serial.tools.list_ports.comports():
        if p.device in candidates:
            # Check for ESP32 or common USB serial chips (CH34x 1A86, CP210x 10C4, FTDI 0403, Espressif 303A)
            if p.vid in (0x1a86, 0x10c4, 0x0403, 0x303a) or 'ESP' in (p.description or ''):
                return p.device
                
    return candidates[0]

class SerialController:
    """
    คลาสนี้รับผิดชอบเรื่องการส่งข้อมูลผ่านสาย USB (Serial) ไปยัง ESP32 เท่านั้น
    รองรับ Auto-detection พอร์ต (/dev/ttyACM* และ /dev/ttyUSB*) และ Reconnection
    """
    def __init__(self, port='/dev/ttyACM0', baudrate=115200, logger=None):
        self.preferred_port = port
        self.port = port
        self.baudrate = baudrate
        self.logger = logger
        self.ser = None
        self._last_reconnect_attempt = 0.0
        self.connect()

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def connect(self):
        # Auto-detect actual port
        detected_port = find_esp32_port(self.preferred_port)
        self.port = detected_port

        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            if self.logger:
                self.logger.info(f"Successfully connected to ESP32 on {self.port}")
            time.sleep(2) # Wait for ESP32 to reset upon serial connection
            return True
        except Exception as e:
            self.ser = None
            if self.logger:
                self.logger.error(f"Failed to connect to ESP32 on {self.port}: {e}")
            return False

    def send_command(self, speeds, vacuum_on, yaw=0.0, pitch=0.0):
        """
        แปลงข้อมูลตัวเลขให้เป็น String รูปแบบ <M1,M2,M3,M4,Vacuum,Yaw,Pitch> แล้วส่งไป
        :param speeds: list ความเร็วมอเตอร์ [M1, M2, M3, M4]
        :param vacuum_on: boolean เปิด/ปิดมอเตอร์ดูดฝุ่น (True/False)
        :param yaw: float มุม Yaw ของกล้อง (-90 ถึง 90) X
        :param pitch: float มุม Pitch ของกล้อง (-90 ถึง 90) Y
        """
        if not self.ser or not self.ser.is_open:
            now = time.time()
            if now - self._last_reconnect_attempt > 2.0:
                self._last_reconnect_attempt = now
                self.connect()
            if not self.ser or not self.ser.is_open:
                return

        # Relay control: 1 = ON, 0 = OFF
        vacuum_val = 1 if vacuum_on else 0
        payload = f"<{speeds[0]},{speeds[1]},{speeds[2]},{speeds[3]},{vacuum_val},{int(yaw)},{int(pitch)}>\n"
        
        try:
            self.ser.write(payload.encode('utf-8'))
        except Exception as e:
            if self.logger:
                self.logger.error(f"Serial write error: {e}. Resetting connection.")
            try:
                if self.ser:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None

    def stop_robot_and_close(self):
        """ส่งคำสั่งให้หุ่นหยุดนิ่ง แล้วปิดการเชื่อมต่อ Serial อย่างปลอดภัย"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(b"<0,0,0,0,0,0,0>\n")
            except:
                pass
            try:
                self.ser.close()
            except:
                pass
            self.ser = None