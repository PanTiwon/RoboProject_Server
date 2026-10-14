#!/usr/bin/env bash
# ==============================================================================
# Robot Startup Network Check & Hotspot Setup Portal
# ==============================================================================

CHECK_HOST="8.8.8.8"
HOTSPOT_SSID="ROBOClearner_Setup_Group9"
HOTSPOT_PASS="" # Empty string = Open Wi-Fi (No password required)
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

# สแกนสัญญาณ Wi-Fi รอบตัวเก็บเข้าแคชไว้ล่วงหน้าก่อนเปิด Hotspot
echo "[StartupNet] Pre-scanning nearby Wi-Fi networks..."
nmcli device wifi rescan ifname "$IFACE" > /dev/null 2>&1 || true
sleep 1.5

# เคลียร์การเชื่อมต่อ Hotspot เดิมหากมีค้างอยู่
nmcli connection down "$HOTSPOT_SSID" > /dev/null 2>&1 || true
nmcli connection delete "$HOTSPOT_SSID" > /dev/null 2>&1 || true
nmcli connection delete "Hotspot" > /dev/null 2>&1 || true

# ปล่อย Wi-Fi Hotspot แบบ Open (ไม่มีรหัสผ่าน) เพื่อให้โทรศัพท์แตะเชื่อมต่อได้ทันที
if [ -n "$HOTSPOT_PASS" ]; then
    echo "[StartupNet] Activating Secured Hotspot: SSID='$HOTSPOT_SSID' (Pass='$HOTSPOT_PASS') ..."
    nmcli device wifi hotspot ifname "$IFACE" ssid "$HOTSPOT_SSID" password "$HOTSPOT_PASS" || {
        nmcli connection up "$HOTSPOT_SSID" || true
    }
else
    echo "[StartupNet] Activating Open Hotspot: SSID='$HOTSPOT_SSID' (No password) ..."
    nmcli connection add type wifi ifname "$IFACE" con-name "$HOTSPOT_SSID" autoconnect no ssid "$HOTSPOT_SSID" mode ap ipv4.method shared ipv6.method ignore > /dev/null 2>&1 || true
    nmcli connection up "$HOTSPOT_SSID" || true
fi

echo "[StartupNet] Hotspot is active!"
echo "[StartupNet] Launching Wi-Fi setup portal..."

# รัน Flask Setup Web Portal (เมื่อผู้ใช้ตั้งค่าเสร็จ ตัวโปรแกรมจะ shutdown ตัวเองและกลับมาที่นี่)
python3 "$SETUP_SCRIPT"

# เคลียร์ Hotspot ชั่วคราวออกหลังเสร็จสิ้นการตั้งค่า
echo "[StartupNet] Setup finished. Cleaning up temporary Hotspot..."
nmcli connection down "$HOTSPOT_SSID" > /dev/null 2>&1 || true
nmcli connection delete "$HOTSPOT_SSID" > /dev/null 2>&1 || true
nmcli connection delete "Hotspot" > /dev/null 2>&1 || true

echo "[StartupNet] Exiting."
exit 0
