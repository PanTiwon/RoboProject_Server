#!/usr/bin/env bash
# ==============================================================================
# Robot Startup Network Check & Hotspot Setup Portal
# ==============================================================================

CHECK_HOST="8.8.8.8"
HOTSPOT_SSID="Mecanum_Setup"
HOTSPOT_PASS="12345678"
IFACE="wlan0"
SETUP_SCRIPT="/home/spark/ros2_ws/scripts/setup_wifi.py"

echo "[StartupNet] Initializing Network Check..."

# รอ 8 วินาทีเพื่อให้ NetworkManager ลองต่อ Wi-Fi ที่บันทึกไว้เดิม
echo "[StartupNet] Waiting for automatic Wi-Fi connection..."
sleep 8

# ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต
if ping -c 2 -W 3 "$CHECK_HOST" > /dev/null 2>&1; then
    echo "[StartupNet] ✅ Internet is connected! Skipping setup portal."
    exit 0
fi

echo "[StartupNet] ⚠️ No internet connection detected!"
echo "[StartupNet] Activating Hotspot: SSID='$HOTSPOT_SSID' (Pass='$HOTSPOT_PASS') ..."

# เคลียร์การเชื่อมต่อ Hotspot เดิมหากมีค้างอยู่
nmcli connection down "$HOTSPOT_SSID" > /dev/null 2>&1 || true

# ปล่อย Wi-Fi Hotspot ด้วย nmcli
nmcli device wifi hotspot ifname "$IFACE" ssid "$HOTSPOT_SSID" password "$HOTSPOT_PASS" || {
    nmcli connection up "$HOTSPOT_SSID" || true
}

echo "[StartupNet] Hotspot is active!"
echo "[StartupNet] Launching Wi-Fi setup portal..."

# รัน Flask Setup Web Portal (เมื่อผู้ใช้ตั้งค่าเสร็จ ตัวโปรแกรมจะ shutdown ตัวเองและกลับมาที่นี่)
python3 "$SETUP_SCRIPT"

echo "[StartupNet] Setup finished. Exiting."
exit 0
