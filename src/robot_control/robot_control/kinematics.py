class MecanumKinematics:
    """
    คลาสนี้ทำหน้าที่คำนวณคณิตศาสตร์ของการเคลื่อนที่ล้อ Mecanum
    แปลงค่าจากจอยสติ๊ก (X, Y, Rotation) ให้กลายเป็นความเร็วของล้อแต่ละล้อ
    """
    def __init__(self, max_pwm=255.0):
        self.max_pwm = max_pwm

    def calculate_speeds(self, forward_backward, strafe_left_right, rotation_left_right):
        """
        คำนวณและปรับลดสเกลความเร็วมอเตอร์ไม่ให้เกินขีดจำกัด (Normalize)
        
        :param forward_backward: ค่าความเร็วเดินหน้า/ถอยหลัง (-1.0 ถึง 1.0)
        :param strafe_left_right: ค่าความเร็วสไลด์ซ้าย/ขวา (-1.0 ถึง 1.0)
        :param rotation_left_right: ค่าการหมุนซ้าย/ขวา (-1.0 ถึง 1.0)
        :return: list ของ PWM [M1, M2, M3, M4]
        """
        v_x = forward_backward
        v_y = strafe_left_right
        omega = rotation_left_right
        
        # Standard Kinematic Model for Mecanum (X-forward, Y-left, Z-up)
        m1_fl = v_x - v_y - omega
        m2_fr = v_x + v_y + omega
        m3_bl = v_x + v_y - omega
        m4_br = v_x - v_y + omega
        
        speeds = [m1_fl, m2_fr, m3_bl, m4_br]
        max_speed = max(map(abs, speeds))
        
        # Normalize (ลดสัดส่วนลงถ้าผลรวมมากกว่า 1.0 เพื่อไม่ให้มอเตอร์หมุนเกิน 255)
        if max_speed > 1.0:
            speeds = [s / max_speed for s in speeds]
            
        # Map to PWM range
        pwm_speeds = [int(s * self.max_pwm) for s in speeds]
        
        return pwm_speeds
