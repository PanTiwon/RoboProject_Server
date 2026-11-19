#!/usr/bin/env python3
"""
Robot Captive Portal Setup Server (Flask)
Used for initial device provisioning: Wi-Fi, Firebase, and Tailscale.
"""

import sys
import glob
import os

# Automatically include user site-packages so flask works under both normal user and sudo/root
for site_pkg in glob.glob("/home/*/.local/lib/python3.*/site-packages"):
    if os.path.isdir(site_pkg) and site_pkg not in sys.path:
        sys.path.insert(0, site_pkg)

import subprocess
import logging
from pathlib import Path

try:
    from flask import (
        Flask,
        request,
        redirect,
        url_for,
        session,
        render_template_string,
        flash,
        jsonify
    )
except ImportError:
    print("[Portal Error] Flask is not installed. Please run: pip3 install flask")
    sys.exit(1)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
ADMIN_USERNAME = "admin"
# กำหนดรหัสผ่านเริ่มต้นตรงนี้ (หรือรับจาก Environment Variable)
ADMIN_PASSWORD = os.environ.get("PORTAL_ADMIN_PASSWORD", "robot2026")

# ตำแหน่งไฟล์ .env ที่ต้องการบันทึก (ระบุชัดเจนเพื่อไม่ให้ root เขียนผิดที่)
ENV_FILE_PATH = os.environ.get(
    "ROBOT_ENV_PATH",
    "/home/spark/ros2_ws/.env"
)

is_root = (os.geteuid() == 0) if hasattr(os, "geteuid") else False
DEFAULT_PORT = 80 if is_root else 8080
PORTAL_PORT = int(os.environ.get("PORTAL_PORT", DEFAULT_PORT))

# ==============================================================================
# FLASK INITIALIZATION
# ==============================================================================
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "robot-setup-portal-super-secret-key-2026")

# Suppress standard werkzeug logs to keep terminal readable
log = logging.getLogger("werkzeug")
log.setLevel(logging.INFO)

# ==============================================================================
# HELPER FUNCTIONS: .ENV PARSING & WRITING
# ==============================================================================
def read_current_env():
    """Reads existing .env file into a dictionary."""
    config = {
        "WIFI_SSID": "",
        "WIFI_PASSWORD": "",
        "FIREBASE_URL": "",
        "FIREBASE_KEY": "",
        "TAILSCALE_AUTHKEY": ""
    }
    env_path = Path(ENV_FILE_PATH)
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        config[k.strip()] = v.strip().strip("'\"")
        except Exception as e:
            print(f"[Portal] Warning reading existing .env: {e}")
    return config

def write_env_file(data: dict):
    """Writes the dictionary to .env file preserving existing keys if needed."""
    env_path = Path(ENV_FILE_PATH)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    
    current_env = read_current_env()
    current_env.update(data)
    
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# ==========================================================\n")
        f.write("# Robot Configuration Environment (.env)\n")
        f.write("# Auto-generated via Robot Captive Portal\n")
        f.write("# ==========================================================\n\n")
        for key, val in current_env.items():
            f.write(f"{key}={val}\n")
    print(f"[Portal] Saved configurations to {env_path.resolve()}")

# ==============================================================================
# CAPTIVE PORTAL REDIRECT ROUTES (iOS, Android, Windows)
# ==============================================================================
@app.route("/generate_204")           # Android
@app.route("/gen_204")                # Android variant
@app.route("/hotspot-detect.html")     # Apple iOS / macOS
@app.route("/canonical.html")          # Apple variant
@app.route("/ncsi.txt")                # Windows
@app.route("/connecttest.txt")         # Windows
@app.route("/redirect")
def captive_portal_detector():
    """Redirects captive portal detection queries to root setup page."""
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return redirect(url_for("index"))

# ==============================================================================
# ROUTE: LOGIN (/login)
# ==============================================================================
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Robot Setup Portal | Login</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
    body {
      background: radial-gradient(circle at 50% 10%, #1e293b, #0f172a 70%);
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 20px;
    }
    .card {
      background: rgba(30, 41, 59, 0.7);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 16px;
      padding: 32px;
      width: 100%;
      max-width: 400px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
    }
    .brand {
      text-align: center;
      margin-bottom: 24px;
    }
    .brand h1 {
      font-size: 1.5rem;
      font-weight: 700;
      color: #38bdf8;
      letter-spacing: -0.5px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
    }
    .brand p {
      font-size: 0.85rem;
      color: #94a3b8;
      margin-top: 6px;
    }
    .form-group {
      margin-bottom: 18px;
    }
    label {
      display: block;
      font-size: 0.82rem;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    input {
      width: 100%;
      padding: 12px 14px;
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 8px;
      color: #fff;
      font-size: 0.95rem;
      transition: all 0.2s ease;
    }
    input:focus {
      outline: none;
      border-color: #38bdf8;
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.25);
    }
    .btn {
      width: 100%;
      padding: 12px;
      background: linear-gradient(135deg, #0284c7, #2563eb);
      border: none;
      border-radius: 8px;
      color: #ffffff;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
      transition: all 0.2s ease;
      margin-top: 10px;
    }
    .btn:hover {
      background: linear-gradient(135deg, #0369a1, #1d4ed8);
      transform: translateY(-1px);
    }
    .alert {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.4);
      color: #fca5a5;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 0.85rem;
      margin-bottom: 18px;
      text-align: center;
    }
    .badge {
      display: inline-block;
      padding: 3px 8px;
      font-size: 0.72rem;
      border-radius: 9999px;
      background: rgba(56, 189, 248, 0.15);
      color: #38bdf8;
      margin-bottom: 10px;
      font-weight: 600;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <span class="badge">PROVISIONING MODE</span>
      <h1>🤖 Robot Portal</h1>
      <p>เข้าสู่ระบบเพื่อตั้งค่าเครือข่ายและระบบคลาวด์</p>
    </div>

    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert">{{ message }}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="POST" action="/login">
      <div class="form-group">
        <label>Username</label>
        <input type="text" name="username" placeholder="admin" required autofocus>
      </div>
      <div class="form-group">
        <label>Password</label>
        <input type="password" name="password" placeholder="••••••••" required>
      </div>
      <button type="submit" class="btn">Login เข้าสู่ระบบ</button>
    </form>
  </div>
</body>
</html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            session["user"] = username
            flash("เข้าสู่ระบบสำเร็จ", "success")
            return redirect(url_for("index"))
        else:
            flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
            return redirect(url_for("login"))
            
    # GET
    if session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template_string(LOGIN_HTML)

# ==============================================================================
# ROUTE: LOGOUT (/logout)
# ==============================================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ==============================================================================
# ROUTE: INDEX / CONFIGURATION (/ and /config)
# ==============================================================================
INDEX_HTML = """
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Robot System Provisioning</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
    body {
      background: radial-gradient(circle at 50% 10%, #1e293b, #0f172a 70%);
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 24px 16px;
    }
    .container {
      width: 100%;
      max-width: 620px;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      padding: 0 4px;
    }
    .header h2 {
      font-size: 1.4rem;
      font-weight: 700;
      color: #38bdf8;
    }
    .logout-btn {
      background: rgba(239, 68, 68, 0.2);
      border: 1px solid rgba(239, 68, 68, 0.4);
      color: #fca5a5;
      padding: 7px 14px;
      border-radius: 8px;
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 600;
      transition: all 0.2s ease;
    }
    .logout-btn:hover {
      background: rgba(239, 68, 68, 0.4);
      color: #fff;
    }
    .card {
      background: rgba(30, 41, 59, 0.7);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 16px;
      padding: 28px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
    }
    .section-title {
      font-size: 0.9rem;
      font-weight: 700;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin: 18px 0 12px 0;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .section-title:first-of-type { margin-top: 0; }
    .form-group {
      margin-bottom: 16px;
    }
    label {
      display: block;
      font-size: 0.82rem;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 6px;
    }
    input, textarea {
      width: 100%;
      padding: 11px 13px;
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 8px;
      color: #fff;
      font-size: 0.92rem;
      transition: all 0.2s ease;
    }
    textarea {
      font-family: monospace;
      resize: vertical;
      min-height: 80px;
    }
    input:focus, textarea:focus {
      outline: none;
      border-color: #38bdf8;
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.25);
    }
    .input-hint {
      font-size: 0.75rem;
      color: #64748b;
      margin-top: 4px;
    }
    .btn-submit {
      width: 100%;
      padding: 13px;
      background: linear-gradient(135deg, #0ea5e9, #2563eb);
      border: none;
      border-radius: 8px;
      color: #ffffff;
      font-size: 1.05rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 16px rgba(37, 99, 235, 0.4);
      margin-top: 14px;
      transition: all 0.2s ease;
    }
    .btn-submit:hover {
      background: linear-gradient(135deg, #0284c7, #1d4ed8);
      transform: translateY(-1px);
    }
    .alert-success {
      background: rgba(34, 197, 94, 0.15);
      border: 1px solid rgba(34, 197, 94, 0.4);
      color: #86efac;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 0.9rem;
      margin-bottom: 20px;
      line-height: 1.4;
    }
    .alert-error {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.4);
      color: #fca5a5;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 0.9rem;
      margin-bottom: 20px;
      line-height: 1.4;
    }
    .cmd-log {
      background: #000;
      color: #38bdf8;
      padding: 12px;
      border-radius: 8px;
      font-family: monospace;
      font-size: 0.8rem;
      white-space: pre-wrap;
      max-height: 150px;
      overflow-y: auto;
      margin-top: 10px;
      border: 1px solid rgba(255,255,255,0.1);
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h2>⚙️ Robot Setup & Config</h2>
      <a href="/logout" class="logout-btn">ออกจากระบบ (Logout)</a>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="{{ 'alert-success' if category == 'success' else 'alert-error' }}">
            {{ message|safe }}
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <div class="card">
      <form method="POST" action="/">
        <!-- 1. Wi-Fi Configuration -->
        <div class="section-title">📡 1. เครือข่าย Wi-Fi ท้องถิ่น</div>
        <div class="form-group">
          <label>Wi-Fi SSID (ชื่อสัญญาณ Wi-Fi)</label>
          <input type="text" name="wifi_ssid" value="{{ config.WIFI_SSID }}" placeholder="เช่น Home_WiFi_2.4G" required>
        </div>
        <div class="form-group">
          <label>Wi-Fi Password (รหัสผ่าน Wi-Fi)</label>
          <input type="password" name="wifi_password" value="{{ config.WIFI_PASSWORD }}" placeholder="รหัสผ่านเชื่อมต่อ Wi-Fi">
          <div class="input-hint">หากเป็น Wi-Fi แบบไม่มีรหัสผ่าน สามารถเว้นว่างไว้ได้</div>
        </div>

        <!-- 2. Firebase Configuration -->
        <div class="section-title">🔥 2. ระบบคลาวด์ Firebase</div>
        <div class="form-group">
          <label>Firebase Database URL</label>
          <input type="url" name="firebase_url" value="{{ config.FIREBASE_URL }}" placeholder="https://your-project-rtdb.asia-southeast1.firebasedatabase.app/" required>
        </div>
        <div class="form-group">
          <label>Firebase Service Account Key (Path หรือ JSON)</label>
          <textarea name="firebase_key" placeholder="/home/spark/firebase_key.json หรือวางโค้ด JSON คีย์" rows="2">{{ config.FIREBASE_KEY }}</textarea>
          <div class="input-hint">ใส่ Path ไปยังไฟล์ Service Account (เช่น /home/spark/firebase_key.json)</div>
        </div>

        <!-- 3. Tailscale VPN -->
        <div class="section-title">🔒 3. เครือข่ายระยะไกล (Tailscale Mesh VPN)</div>
        <div class="form-group">
          <label>Tailscale Auth Key</label>
          <input type="text" name="tailscale_authkey" value="{{ config.TAILSCALE_AUTHKEY }}" placeholder="tskey-auth-kXXXXX-XXXXXXXXXXXXXXX">
          <div class="input-hint">Auth Key ที่ได้จาก Tailscale Admin Console (ใช้สำหรับเครื่อง Join เครือข่ายอัตโนมัติ)</div>
        </div>

        <button type="submit" class="btn-submit">💾 บันทึกและเชื่อมต่อเครือข่าย (Save & Connect)</button>
      </form>
    </div>
  </div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    # ตรวจสอบการ Login
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    current_config = read_current_env()

    if request.method == "POST":
        wifi_ssid = request.form.get("wifi_ssid", "").strip()
        wifi_password = request.form.get("wifi_password", "").strip()
        firebase_url = request.form.get("firebase_url", "").strip()
        firebase_key = request.form.get("firebase_key", "").strip()
        tailscale_authkey = request.form.get("tailscale_authkey", "").strip()

        # 1. บันทึกค่าลง .env
        env_payload = {
            "WIFI_SSID": wifi_ssid,
            "WIFI_PASSWORD": wifi_password,
            "FIREBASE_URL": firebase_url,
            "FIREBASE_KEY": firebase_key,
            "TAILSCALE_AUTHKEY": tailscale_authkey
        }
        write_env_file(env_payload)

        logs = []
        logs.append(f"บันทึกไฟล์ .env เรียบร้อยแล้วที่ {ENV_FILE_PATH}")

        # 2. รันคำสั่งตั้งค่า Tailscale (หากมีการกรอก Key)
        if tailscale_authkey:
            try:
                ts_cmd = ["sudo", "tailscale", "up", f"--authkey={tailscale_authkey}", "--accept-routes"]
                ts_res = subprocess.run(ts_cmd, capture_output=True, text=True, timeout=15)
                if ts_res.returncode == 0:
                    logs.append("✅ ตั้งค่า Tailscale สำเร็จ")
                else:
                    logs.append(f"⚠️ Tailscale warning: {ts_res.stderr.strip() or ts_res.stdout.strip()}")
            except Exception as e:
                logs.append(f"❌ Tailscale error: {str(e)}")

        # 3. รันคำสั่ง nmcli เพื่อเชื่อมต่อ Wi-Fi เป้าหมาย
        if wifi_ssid:
            try:
                # ปล่อยคำสั่ง nmcli ให้เชื่อมต่อ Wi-Fi
                if wifi_password:
                    nmcli_cmd = ["sudo", "nmcli", "dev", "wifi", "connect", wifi_ssid, "password", wifi_password]
                else:
                    nmcli_cmd = ["sudo", "nmcli", "dev", "wifi", "connect", wifi_ssid]

                # ให้รันแบบ asynchronous เล็กน้อย หรือ timeout พอประมาณ เพราะเมื่อเปลี่ยนเครือข่าย Hotspot อาจหลุด
                wifi_res = subprocess.run(nmcli_cmd, capture_output=True, text=True, timeout=20)
                if wifi_res.returncode == 0:
                    logs.append(f"✅ เชื่อมต่อ Wi-Fi '{wifi_ssid}' สำเร็จแล้ว!")
                else:
                    logs.append(f"⚠️ ผลการเชื่อมต่อ Wi-Fi: {wifi_res.stderr.strip() or wifi_res.stdout.strip()}")
            except subprocess.TimeoutExpired:
                logs.append(f"ℹ️ กำลังเชื่อมต่อไปยัง '{wifi_ssid}' (คำสั่งถูกส่งไปยัง NetworkManager แล้ว)")
            except Exception as e:
                logs.append(f"❌ Wi-Fi Error: {str(e)}")

        success_html = "<br>".join(logs)
        flash(f"<b>ดำเนินการเสร็จสิ้น:</b><br>{success_html}", "success")
        return redirect(url_for("index"))

    return render_template_string(INDEX_HTML, config=current_config)

# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    print(f"==================================================")
    print(f"🤖 Starting Robot Captive Portal on port {PORTAL_PORT}...")
    print(f"🔑 Admin credentials -> User: {ADMIN_USERNAME} | Pass: {ADMIN_PASSWORD}")
    print(f"📁 Target .env -> {ENV_FILE_PATH}")
    print(f"==================================================")
    try:
        app.run(host="0.0.0.0", port=PORTAL_PORT, debug=False)
    except PermissionError:
        print(f"\n[Portal] ⚠️ Permission denied binding to port {PORTAL_PORT} (privileged port).")
        print(f"[Portal] 🔄 Auto-switching to unprivileged port 8080...")
        print(f"🌐 Please visit: http://localhost:8080 or http://<IP>:8080")
        app.run(host="0.0.0.0", port=8080, debug=False)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"\n[Portal] ⚠️ Port {PORTAL_PORT} is already in use!")
            print(f"[Portal] 🔄 Trying port 8080...")
            print(f"🌐 Please visit: http://localhost:8080 or http://<IP>:8080")
            app.run(host="0.0.0.0", port=8080, debug=False)
        else:
            raise e
