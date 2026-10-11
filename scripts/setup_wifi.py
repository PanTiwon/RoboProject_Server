#!/usr/bin/env python3
"""
Simple Wi-Fi Setup Portal (Flask) for Mecanum Robot
Allows on-site Wi-Fi configuration via a clean mobile-friendly web UI
with dynamic Wi-Fi network scanning dropdown and manual fallback.
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
    from flask import Flask, request, render_template_string, redirect, url_for, jsonify
except ImportError:
    print("[Error] Flask is not installed. Please run: pip3 install flask")
    sys.exit(1)

app = Flask(__name__)

PORT = 80 if os.geteuid() == 0 else 8080

# ==============================================================================
# WI-FI SCANNING UTILITY
# ==============================================================================
def scan_wifi_networks():
    """Scans and returns nearby Wi-Fi networks using nmcli cache/list."""
    networks = {}
    try:
        res = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=8
        )
        if res.returncode == 0:
            lines = res.stdout.strip().split("\n")
            for line in lines:
                if not line.strip():
                    continue
                parts = line.rsplit(":", 2)
                if len(parts) == 3:
                    ssid = parts[0].replace(r"\:", ":").strip()
                    try:
                        signal = int(parts[1].strip())
                    except ValueError:
                        signal = 0
                    security = parts[2].replace(r"\:", ":").strip()

                    # Ignore empty/hidden or our own hotspot
                    if not ssid or ssid == "Mecanum_Setup" or ssid == "--":
                        continue

                    # Keep entry with strongest signal if SSID is duplicate (e.g. 2.4G & 5G)
                    if ssid not in networks or signal > networks[ssid]["signal"]:
                        networks[ssid] = {
                            "ssid": ssid,
                            "signal": signal,
                            "security": security
                        }
    except Exception as e:
        print(f"[SetupWiFi] Scan error: {e}")

    # Return list sorted descending by signal strength
    return sorted(networks.values(), key=lambda x: x["signal"], reverse=True)


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
      max-width: 420px;
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
    .select-wrap {
      display: flex;
      gap: 8px;
      align-items: stretch;
    }
    select, input {
      width: 100%;
      padding: 13px 15px;
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 10px;
      color: #fff;
      font-size: 0.95rem;
      transition: all 0.2s ease;
      appearance: none;
      -webkit-appearance: none;
    }
    select {
      cursor: pointer;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%2338bdf8'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'%3E%3C/path%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 14px center;
      background-size: 16px;
      padding-right: 38px;
    }
    select option {
      background: #0f172a;
      color: #fff;
    }
    select:focus, input:focus {
      outline: none;
      border-color: #38bdf8;
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.25);
    }
    .btn-refresh {
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 10px;
      color: #38bdf8;
      width: 48px;
      flex-shrink: 0;
      display: flex;
      justify-content: center;
      align-items: center;
      cursor: pointer;
      font-size: 1.15rem;
      transition: all 0.2s ease;
    }
    .btn-refresh:hover {
      background: rgba(56, 189, 248, 0.15);
      border-color: #38bdf8;
    }
    .btn-refresh.loading {
      pointer-events: none;
      opacity: 0.6;
    }
    .btn-refresh.loading span {
      display: inline-block;
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    .hint {
      font-size: 0.75rem;
      color: #64748b;
      margin-top: 5px;
    }
    .manual-box {
      margin-top: 10px;
      display: none;
      animation: fadeIn 0.3s ease;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(-4px); }
      to { opacity: 1; transform: translateY(0); }
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
    .status-msg {
      font-size: 0.78rem;
      margin-top: 6px;
      color: #94a3b8;
      min-height: 18px;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <span class="badge">NETWORK CONFIG</span>
      <h1>📶 เชื่อมต่อ Wi-Fi หุ่นยนต์</h1>
      <p>เลือกเครือข่าย Wi-Fi ที่ต้องการให้หุ่นยนต์เชื่อมต่อ</p>
    </div>

    <form id="wifiForm" method="POST" action="/">
      <input type="hidden" name="ssid" id="final_ssid">

      <div class="form-group">
        <label>ชื่อสัญญาณ Wi-Fi (SSID)</label>
        <div class="select-wrap">
          <select id="wifi_select">
            <option value="">🔍 กำลังค้นหาสัญญาณ Wi-Fi...</option>
          </select>
          <button type="button" id="btn_refresh" class="btn-refresh" title="รีเฟรชค้นหาสัญญาณใหม่">
            <span>🔄</span>
          </button>
        </div>
        <div id="status_msg" class="status-msg"></div>

        <div id="manual_box" class="manual-box">
          <label style="font-size: 0.78rem; color: #94a3b8; margin-bottom: 4px;">ระบุชื่อ Wi-Fi ด้วยตนเอง:</label>
          <input type="text" id="manual_ssid" placeholder="เช่น MyHome_WiFi_2.4G">
        </div>
      </div>

      <div class="form-group">
        <label>รหัสผ่าน Wi-Fi (Password)</label>
        <input type="password" name="password" id="password_input" placeholder="รหัสผ่าน (เว้นว่างได้ถ้าไม่มี)">
        <div class="hint">กรณี Wi-Fi ไม่มีรหัสผ่าน สามารถเว้นว่างไว้ได้</div>
      </div>

      <button type="submit" class="btn" id="submit_btn">🚀 เชื่อมต่อ Wi-Fi (Connect)</button>
    </form>
  </div>

  <script>
    const selectElem = document.getElementById('wifi_select');
    const refreshBtn = document.getElementById('btn_refresh');
    const manualBox = document.getElementById('manual_box');
    const manualInput = document.getElementById('manual_ssid');
    const statusMsg = document.getElementById('status_msg');
    const formElem = document.getElementById('wifiForm');
    const finalSsid = document.getElementById('final_ssid');

    function getSignalIcon(sig) {
      if (sig >= 75) return '🟢 ▂▄▆█';
      if (sig >= 50) return '🟡 ▂▄▆_';
      if (sig >= 25) return '🟠 ▂▄__';
      return '🔴 ▂___';
    }

    async function fetchWifiList(rescan = false) {
      refreshBtn.classList.add('loading');
      statusMsg.textContent = rescan ? 'กำลังสแกนสัญญาณรอบตัวใหม่...' : 'กำลังดึงรายชื่อ Wi-Fi...';

      try {
        const url = '/api/wifi/scan' + (rescan ? '?rescan=true' : '');
        const res = await fetch(url);
        const data = await res.json();

        selectElem.innerHTML = '';

        if (data.status === 'success' && data.networks && data.networks.length > 0) {
          const defaultOpt = document.createElement('option');
          defaultOpt.value = '';
          defaultOpt.textContent = '--- เลือกเครือข่าย Wi-Fi (' + data.networks.length + ' จุด) ---';
          selectElem.appendChild(defaultOpt);

          data.networks.forEach(net => {
            const opt = document.createElement('option');
            opt.value = net.ssid;
            const icon = getSignalIcon(net.signal);
            const sec = net.security ? (' [' + net.security + ']') : '';
            opt.textContent = `${net.ssid} (${icon} ${net.signal}%${sec})`;
            selectElem.appendChild(opt);
          });

          statusMsg.textContent = `พบทั้งหมด ${data.networks.length} เครือข่าย`;
        } else {
          const opt = document.createElement('option');
          opt.value = '';
          opt.textContent = '-- ไม่พบสัญญาณ Wi-Fi รอบตัว --';
          selectElem.appendChild(opt);
          statusMsg.textContent = 'ไม่พบสัญญาณ Wi-Fi รอบตัว กรุณากรอกชื่อเอง';
          manualBox.style.display = 'block';
        }

        // Always add Manual / Hidden Network option at the bottom
        const manualOpt = document.createElement('option');
        manualOpt.value = '__manual__';
        manualOpt.textContent = '✏️ กรอกชื่อ Wi-Fi เอง (Hidden Network)';
        selectElem.appendChild(manualOpt);

      } catch (err) {
        console.error('Scan error:', err);
        statusMsg.textContent = 'ไม่สามารถดึงข้อมูลเครือข่ายได้';
        selectElem.innerHTML = '<option value="__manual__">✏️ กรอกชื่อ Wi-Fi เอง</option>';
        manualBox.style.display = 'block';
      } finally {
        refreshBtn.classList.remove('loading');
      }
    }

    selectElem.addEventListener('change', () => {
      if (selectElem.value === '__manual__') {
        manualBox.style.display = 'block';
        manualInput.focus();
      } else {
        manualBox.style.display = 'none';
      }
    });

    refreshBtn.addEventListener('click', () => {
      fetchWifiList(true);
    });

    formElem.addEventListener('submit', (e) => {
      let targetSsid = '';
      if (selectElem.value === '__manual__') {
        targetSsid = manualInput.value.trim();
        if (!targetSsid) {
          alert('กรุณากรอกชื่อ Wi-Fi (SSID)');
          manualInput.focus();
          e.preventDefault();
          return;
        }
      } else {
        targetSsid = selectElem.value.trim();
        if (!targetSsid) {
          alert('กรุณาเลือกเครือข่าย Wi-Fi ที่ต้องการเชื่อมต่อ');
          selectElem.focus();
          e.preventDefault();
          return;
        }
      }
      finalSsid.value = targetSsid;
    });

    // Auto fetch on initial page load
    document.addEventListener('DOMContentLoaded', () => {
      fetchWifiList(false);
    });
  </script>
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
# API ROUTES
# ==============================================================================
@app.route("/api/wifi/scan", methods=["GET"])
def api_wifi_scan():
    """Returns scanned Wi-Fi networks in JSON format."""
    rescan = request.args.get("rescan", "false").lower() == "true"
    if rescan:
        try:
            subprocess.run(["nmcli", "device", "wifi", "rescan"], capture_output=True, timeout=5)
            time.sleep(1.0)
        except Exception:
            pass

    net_list = scan_wifi_networks()
    return jsonify({"status": "success", "networks": net_list})


# ==============================================================================
# ROUTES (Catch-All for Captive Portal)
# ==============================================================================
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def index(path):
    if request.method == "POST":
        ssid = request.form.get("ssid", "").strip()
        # Fallbacks if submitted through different field names
        if not ssid or ssid == "__manual__":
            ssid = request.form.get("manual_ssid", "").strip()
        if not ssid:
            ssid = request.form.get("wifi_select", "").strip()

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
