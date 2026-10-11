#!/usr/bin/env bash
# ==============================================================================
# Refuse Robot Auto-Start Installation & Setup Script
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="$SCRIPT_DIR/robot-core.service"
SERVICE_DST="/etc/systemd/system/robot-core.service"
START_SCRIPT="$SCRIPT_DIR/start_ros2.sh"
BASHRC_FILE="$HOME/.bashrc"

echo "=================================================="
echo "🤖 Installing Refuse Robot Autostart Service..."
echo "=================================================="

# 1. Ensure scripts are executable
echo "[1/4] Setting execution permissions..."
chmod +x "$START_SCRIPT"
chmod +x "$SCRIPT_DIR/install_autostart.sh"
if [ -f "$SCRIPT_DIR/startup_network.sh" ]; then
    chmod +x "$SCRIPT_DIR/startup_network.sh"
fi
if [ -f "$SCRIPT_DIR/setup_wifi.py" ]; then
    chmod +x "$SCRIPT_DIR/setup_wifi.py"
fi

# 2. Install and enable systemd service
echo "[2/4] Installing systemd unit file to $SERVICE_DST ..."
sudo cp "$SERVICE_SRC" "$SERVICE_DST"
sudo chmod 644 "$SERVICE_DST"

echo "[3/4] Reloading systemd and enabling robot-core.service..."
sudo systemctl daemon-reload
sudo systemctl enable robot-core.service
sudo systemctl restart robot-core.service

# 3. Add Developer Aliases to ~/.bashrc
echo "[4/4] Configuring bash shortcuts in $BASHRC_FILE ..."
if ! grep -q "robot-log" "$BASHRC_FILE" 2>/dev/null; then
    cat << 'EOF' >> "$BASHRC_FILE"

# ==========================================================
# Refuse Robot Management Aliases
# ==========================================================
alias robot-log='journalctl -u robot-core.service -f -n 50'
alias robot-start='sudo systemctl start robot-core.service'
alias robot-stop='sudo systemctl stop robot-core.service'
alias robot-restart='sudo systemctl restart robot-core.service'
alias robot-status='systemctl status robot-core.service'
EOF
    echo "✅ Aliases added successfully to $BASHRC_FILE!"
else
    echo "ℹ️ Aliases already exist in $BASHRC_FILE. Skipping duplicate entry."
fi

echo "=================================================="
echo "🎉 Autostart installation complete!"
echo "=================================================="
echo ""
echo "Shortcuts available in new terminals:"
echo "  • robot-log     : View live robot console log / dashboard"
echo "  • robot-status  : Check systemd service status"
echo "  • robot-restart : Restart the robot ROS 2 stack"
echo "  • robot-stop    : Stop the robot stack (e.g. for development/manual testing)"
echo "  • robot-start   : Start the robot stack"
echo ""
echo "To activate shortcuts in the current terminal, run:"
echo "  source ~/.bashrc"
echo ""
