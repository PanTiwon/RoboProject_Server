#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import Int32MultiArray, Int32
import asyncio
import websockets
import json
import psutil
import threading
import time
import os
import functools
import http
import smbus

class TelemetryNode(Node):
    # ... (ส่วนคลาส TelemetryNode เหมือนเดิมทุกประการ) ...
    def __init__(self):
        super().__init__('websocket_telemetry')
        
        self.subscription_joy = self.create_subscription(
            Joy, 'joy', self.joy_callback, 10)
        self.subscription_wheels = self.create_subscription(
            Int32MultiArray, 'wheel_speeds', self.wheels_callback, 10)
            
        self.bat_pub = self.create_publisher(Int32, 'battery_percent', 10)
        
        self.declare_parameter('axis_forward', 5)
        self.declare_parameter('axis_backward', 2)
        self.declare_parameter('axis_strafe', 0)
        self.declare_parameter('axis_rotate', 3)
        self.declare_parameter('serial_port', '/dev/ttyUSB0')
        
        self.joy_x = 0.0
        self.joy_y = 0.0
        self.joy_w = 0.0
        self.trigger_l2 = 0.0
        self.trigger_r2 = 0.0
        
        self.wheel_fl = 0
        self.wheel_fr = 0
        self.wheel_bl = 0
        self.wheel_br = 0
        
        self.sweeper_status = "Offline"
        self.robot_mode = "MANUAL"
        self.last_joy_time = 0.0
        
        # Battery setup
        self.bat_percent = 0
        self.last_bat_percent = -1
        try:
            self.i2c_bus = smbus.SMBus(1)
            self.i2c_addr = 0x2d
            self.create_timer(5.0, self.check_battery) # Check every 5 seconds
        except Exception as e:
            self.get_logger().error(f"Failed to init SMBus for battery: {e}")

    def check_battery(self):
        try:
            # Read percentage
            data_pct = self.i2c_bus.read_i2c_block_data(self.i2c_addr, 0x20, 0x0C)
            percent = int(data_pct[4] | data_pct[5] << 8)
            self.bat_percent = percent
            
            # Read voltage and current
            voltage = data_pct[0] | data_pct[1] << 8
            current = data_pct[2] | data_pct[3] << 8
            if current > 0x7FFF:
                current -= 0xFFFF
                
            capacity = data_pct[6] | data_pct[7] << 8
            
            if percent != self.last_bat_percent:
                self.get_logger().info(f"🔋 UPS Battery Update: {percent}% | {voltage}mV | {current}mA | {capacity}mAh remaining")
                self.last_bat_percent = percent
                
            bat_msg = Int32()
            bat_msg.data = percent
            self.bat_pub.publish(bat_msg)
                
        except Exception as e:
            # Silently ignore read errors to prevent log spam if I2C fails temporarily
            pass

    def map_trigger(self, val):
        return (1.0 - val) / 2.0

    def joy_callback(self, msg):
        self.last_joy_time = time.time()
        try:
            axis_fwd = self.get_parameter('axis_forward').value
            axis_bwd = self.get_parameter('axis_backward').value
            axis_strafe = self.get_parameter('axis_strafe').value
            axis_rot = self.get_parameter('axis_rotate').value
            
            fwd_val = self.map_trigger(msg.axes[axis_fwd])
            bwd_val = self.map_trigger(msg.axes[axis_bwd])
            
            self.joy_x = -msg.axes[axis_strafe]
            self.joy_y = fwd_val - bwd_val
            self.joy_w = -msg.axes[axis_rot]
            
            self.trigger_l2 = bwd_val
            self.trigger_r2 = fwd_val
        except IndexError:
            pass

    def wheels_callback(self, msg):
        if len(msg.data) >= 4:
            self.wheel_fl = msg.data[0]
            self.wheel_fr = msg.data[1]
            self.wheel_bl = msg.data[2]
            self.wheel_br = msg.data[3]
        if len(msg.data) >= 5:
            mode_val = msg.data[4]
            if mode_val == 0: self.robot_mode = "MANUAL"
            elif mode_val == 1: self.robot_mode = "DEMO"
            elif mode_val == 2: self.robot_mode = "AUTO"
        if len(msg.data) >= 6:
            sweeper_active = (msg.data[5] == 1)
            self.sweeper_status = "Online" if sweeper_active else "Offline"

    def get_controller_status(self):
        if self.last_joy_time > 0 and (time.time() - self.last_joy_time) < 2.0:
            return "Online"
        return "Offline"

    def get_esp32_status(self):
        port = self.get_parameter('serial_port').value
        if os.path.exists(port):
            return "Online"
        return "Offline"
        
    def get_motor_status(self):
        return self.get_esp32_status()
        
    def get_camera_status(self):
        if os.path.exists("/dev/video0"):
            return "Online"
        return "Offline"

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = int(f.read()) / 1000.0
            return round(temp, 1)
    except FileNotFoundError:
        return 0.0

async def broadcast_telemetry(websocket, node):
    while True:
        try:
            payload = {
                "status": {
                    "pi": "Online",
                    "esp32": "Online" if node.robot_mode == "DEMO" else node.get_esp32_status(),
                    "motor": "Online" if node.robot_mode == "DEMO" else node.get_motor_status(),
                    "controller": node.get_controller_status(),
                    "camera": "Online" if node.robot_mode == "DEMO" else node.get_camera_status(),
                    "sweeper": "Online" if node.robot_mode == "DEMO" else ("Offline" if node.get_esp32_status() == "Offline" else node.sweeper_status),
                    "mode": node.robot_mode
                },
                "telemetry": {
                    "cpu_temp": get_cpu_temp(),
                    "cpu_load": psutil.cpu_percent(),
                    "ram_usage": psutil.virtual_memory().percent,
                    "battery_percent": node.bat_percent
                },
                "movement": {
                    "joy_x": round(node.joy_x, 2),
                    "joy_y": round(node.joy_y, 2),
                    "joy_w": round(node.joy_w, 2),
                    "trigger_l2": round(node.trigger_l2, 2),
                    "trigger_r2": round(node.trigger_r2, 2),
                    "wheels": {
                        "fl": node.wheel_fl,
                        "fr": node.wheel_fr,
                        "bl": node.wheel_bl,
                        "br": node.wheel_br
                    }
                }
            }
            await websocket.send(json.dumps(payload))
            await asyncio.sleep(0.1) 
            
        except websockets.exceptions.ConnectionClosed:
            node.get_logger().info("Client disconnected.")
            break
        except Exception as e:
            node.get_logger().error(f"WebSocket error: {e}")
            break

async def handler(websocket, *args, **kwargs):
    node = kwargs.get('node')
    if node is None:
        return
        
    node.get_logger().info(f"New WebSocket client connected from {websocket.remote_address}")
    await broadcast_telemetry(websocket, node)

async def process_request(path, request_headers, node=None):
    if path == '/api/status' and node is not None:
        payload = {
            "status": {
                "pi": "Online",
                "esp32": "Online" if node.robot_mode == "DEMO" else node.get_esp32_status(),
                "motor": "Online" if node.robot_mode == "DEMO" else node.get_motor_status(),
                "controller": node.get_controller_status(),
                "camera": "Online" if node.robot_mode == "DEMO" else node.get_camera_status(),
                "sweeper": "Online" if node.robot_mode == "DEMO" else ("Offline" if node.get_esp32_status() == "Offline" else node.sweeper_status),
                "mode": node.robot_mode
            }
        }
        body = json.dumps(payload).encode('utf-8')
        headers = [
            ('Content-Type', 'application/json'),
            ('Access-Control-Allow-Origin', '*')
        ]
        return (http.HTTPStatus.OK, headers, body)
    return None

def start_ros_node(node):
    rclpy.spin(node)

def main(args=None):
    rclpy.init(args=args)
    node = TelemetryNode()

    ros_thread = threading.Thread(target=start_ros_node, args=(node,), daemon=True)
    ros_thread.start()

    port = 8080
    bound_handler = functools.partial(handler, node=node)
    # เริ่มต้นการตั้งค่า WebSocket Server (แบบปกติ ไม่ต้องใช้ SSL เพราะ Tailscale Funnel จัดการให้)
    bound_process_request = functools.partial(process_request, node=node)
    start_server = websockets.serve(
        bound_handler, 
        "0.0.0.0", 
        port, 
        process_request=bound_process_request
    )
    
    node.get_logger().info(f"✅ SUCCESS: Starting WebSocket server on ws://0.0.0.0:{port} (via Funnel)")
    print(f"\n=========================================\n✅ SUCCESS: Starting WebSocket server on ws://0.0.0.0:{port} (via Funnel)\n=========================================\n")
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_server)
    
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        node.get_logger().info("Shutting down WebSocket server...")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()