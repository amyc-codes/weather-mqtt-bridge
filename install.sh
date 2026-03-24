#!/bin/bash
set -e

# weather-mqtt-bridge installer for LoxBerry / Raspberry Pi
INSTALL_DIR="/opt/weather-mqtt-bridge"

echo "=== weather-mqtt-bridge installer ==="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Install with: sudo apt install python3 python3-pip"
    exit 1
fi

# Install dir
echo "📁 Installing to $INSTALL_DIR ..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp weather_mqtt_bridge.py "$INSTALL_DIR/"
sudo cp requirements.txt "$INSTALL_DIR/"

# Copy config only if not already present (don't overwrite user config)
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    sudo cp config.yaml "$INSTALL_DIR/"
    echo "📝 Default config copied. Edit $INSTALL_DIR/config.yaml for your setup."
else
    echo "⚠️  Config already exists at $INSTALL_DIR/config.yaml — not overwriting."
fi

# Dependencies
echo "📦 Installing Python dependencies..."
sudo pip3 install --break-system-packages -r "$INSTALL_DIR/requirements.txt" 2>/dev/null \
  || sudo pip3 install -r "$INSTALL_DIR/requirements.txt"

# Systemd service
echo "🔧 Installing systemd service..."
sudo cp systemd/weather-mqtt-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable weather-mqtt-bridge

echo ""
echo "✅ Installed! Next steps:"
echo "   1. Edit config:  sudo nano $INSTALL_DIR/config.yaml"
echo "   2. Make sure Mosquitto is running: sudo systemctl status mosquitto"
echo "   3. Start service: sudo systemctl start weather-mqtt-bridge"
echo "   4. Check logs:    journalctl -u weather-mqtt-bridge -f"
echo ""
echo "Test with: python3 $INSTALL_DIR/weather_mqtt_bridge.py --config $INSTALL_DIR/config.yaml --once --verbose"
