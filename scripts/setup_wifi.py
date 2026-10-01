#!/usr/bin/env python3
"""
Simple Wi-Fi Setup Portal (Flask) for Mecanum Robot
Allows on-site Wi-Fi configuration via a clean mobile-friendly web UI.
"""

import sys
import os
import glob
import time
import threading
import subprocess

# Automatically include user site-packages so flask works under both normal user and sudo/root
for site_pkg in glob.glob("/home/*/.local/lib/python3.*/site-packages"):
    if os.path.isdir(site_pkg) and site_pkg not in sys.path:
        sys.path.insert(0, site_pkg)

try:
    from flask import Flask, request, render_template_string, redirect, url_for
except ImportError:
    print("[Error] Flask is not installed. Please run: pip3 install flask")
    sys.exit(1)

app = Flask(__name__)

PORT = 80 if os.geteuid() == 0 else 8080

# ==============================================================================
# HTML TEMPLATES (Modern, Mobile-First Dark Theme)
# ==============================================================================
FORM_HTML = """
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mecanum Robot | Wi-Fi Setup</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
    body {
      background: radial-gradient(circle at 50% 10%, #1e293b, #0f172a 75%);
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 20px;
    }
    .card {
      background: rgba(30, 41, 59, 0.75);
      backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 20px;
      padding: 32px 24px;
      width: 100%;
      max-width: 400px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
    }
    .header {
      text-align: center;
      margin-bottom: 26px;
    }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      font-size: 0.72rem;
      font-weight: 700;
      border-radius: 9999px;
      background: rgba(56, 189, 248, 0.15);
      color: #38bdf8;
      margin-bottom: 10px;
      letter-spacing: 0.5px;
    }
    h1 {
      font-size: 1.5rem;
      font-weight: 700;
      color: #38bdf8;
      letter-spacing: -0.5px;
    }
    p {
      font-size: 0.86rem;
      color: #94a3b8;
      margin-top: 6px;
      line-height: 1.4;
    }
    .form-group {
      margin-bottom: 20px;
    }
    label {
      display: block;
      font-size: 0.84rem;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 8px;
    }
    input {
      width: 100%;
      padding: 13px 15px;
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 10px;
      color: #fff;
      font-size: 1rem;
      transition: all 0.2s ease;
    }
    input:focus {
      outline: none;
      border-color: #38bdf8;
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.25);
    }
    .hint {
      font-size: 0.75rem;
      color: #64748b;
      margin-top: 5px;
    }
    .btn {
      width: 100%;
      padding: 14px;
      background: linear-gradient(135deg, #0ea5e9, #2563eb);
      border: none;
      border-radius: 10px;
      color: #ffffff;
      font-size: 1.05rem;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 4px 16px rgba(37, 99, 235, 0.4);
      transition: all 0.2s ease;
      margin-top: 6px;
    }
    .btn:active {
      transform: scale(0.98);
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <span class="badge">NETWORK CONFIG</span>
      <h1>📶 เชื่อมต่อ Wi-Fi หุ่นยนต์</h1>
      <p>กรอกชื่อและรหัสผ่าน Wi-Fi เพื่อให้หุ่นยนต์เชื่อมต่ออินเทอร์เน็ต</p>
    </div>

    <form method="POST" action="/">
      <div class="form-group">
        <label>ชื่อ Wi-Fi (SSID)</label>
        <input type="text" name="ssid" placeholder="เช่น MyHome_WiFi_2.4G" required autofocus>
      </div>

      <div class="form-group">
        <label>รหัสผ่าน Wi-Fi (Password)</label>
        <input type="password" name="password" placeholder="รหัสผ่าน (เว้นว่างได้ถ้าไม่มี)">
        <div class="hint">กรณี Wi-Fi ไม่มีรหัสผ่าน สามารถเว้นว่างไว้ได้</div>
      </div>

      <button type="submit" class="btn">🚀 เชื่อมต่อ Wi-Fi (Connect)</button>
    </form>
  </div>
</body>
</html>
"""

CONNECTING_HTML = """
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>กำลังเชื่อมต่อ...</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
    body {
      background: radial-gradient(circle at 50% 10%, #1e293b, #0f172a 75%);
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 20px;
      text-align: center;
    }
    .card {
      background: rgba(30, 41, 59, 0.75);
      backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 20px;
      padding: 40px 24px;
      width: 100%;
      max-width: 380px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
    }
    .spinner {
      width: 50px;
      height: 50px;
      border: 4px solid rgba(56, 189, 248, 0.2);
      border-top-color: #38bdf8;
      border-radius: 50%;
      animation: spin 1s linear infinite;
      margin: 0 auto 24px auto;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    h2 {
      font-size: 1.35rem;
      color: #38bdf8;
      margin-bottom: 10px;
    }
    p {
      color: #94a3b8;
      font-size: 0.9rem;
      line-height: 1.5;
    }
    .ssid-name {
      color: #22c55e;
      font-weight: 700;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <h2>กำลังเชื่อมต่อ...</h2>
    <p>ระบบกำลังเชื่อมต่อไปยัง <span class="ssid-name">{{ ssid }}</span></p>
    <p style="margin-top: 10px; font-size: 0.8rem; color: #64748b;">
      ฮอตสปอตและเซิร์ฟเวอร์จะปิดตัวลงโดยอัตโนมัติในไม่กี่วินาที
    </p>
  </div>
</body>
</html>
"""

# ==============================================================================
# ROUTES (Catch-All for Captive Portal)
# ==============================================================================
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def index(path):
    if request.method == "POST":
        ssid = request.form.get("ssid", "").strip()
        password = request.form.get("password", "").strip()

        print(f"[SetupWiFi] Received SSID: '{ssid}'")

        # ฟังก์ชันรันคำสั่งเชื่อมต่อ Wi-Fi และสั่ง Shutdown Server
        def connect_and_shutdown():
            time.sleep(1.5)  # รอส่งหน้า HTML ให้เบราว์เซอร์ให้เสร็จก่อน

            print(f"[SetupWiFi] Executing: nmcli device wifi connect '{ssid}' ...")
            if password:
                cmd = ["sudo", "nmcli", "device", "wifi", "connect", ssid, "password", password]
            else:
                cmd = ["sudo", "nmcli", "device", "wifi", "connect", ssid]

            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
                print(f"[SetupWiFi] nmcli output:\n{res.stdout}")
                if res.returncode != 0:
                    print(f"[SetupWiFi] nmcli error:\n{res.stderr}")
            except Exception as e:
                print(f"[SetupWiFi] Connection error: {e}")

            print("[SetupWiFi] Setup complete. Shutting down Flask server...")
            time.sleep(1.0)
            os._exit(0)

        threading.Thread(target=connect_and_shutdown, daemon=True).start()
        return render_template_string(CONNECTING_HTML, ssid=ssid)

    return render_template_string(FORM_HTML)

# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    print(f"==================================================")
    print(f"🤖 Starting Robot Wi-Fi Setup Portal on port {PORT}...")
    print(f"==================================================")
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False)
    except PermissionError:
        print(f"[SetupWiFi] Port {PORT} requires root privileges. Falling back to port 8080...")
        app.run(host="0.0.0.0", port=8080, debug=False)
