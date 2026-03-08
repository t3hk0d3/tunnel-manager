#!/bin/bash

# IP Tunnel Manager - Install Script
# Usage: sudo ./install.sh or curl <url> | sudo bash

set -e

# Configuration
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/ip-tunnel-manager"
SERVICE_NAME="ip-tunnel-manager.service"
TIMER_NAME="ip-tunnel-manager.timer"
REPO_URL="https://raw.githubusercontent.com/t3hk0d3/tunnel-manager/refs/heads/master"

# Help message
function show_help() {
    echo "Usage: sudo $0 [install|uninstall|status]"
    echo ""
    echo "Commands:"
    echo "  install    - (Default) Install the IP Tunnel Manager"
    echo "  uninstall  - Remove the installation"
    echo "  status     - Show status of the service and timer"
}

# Ensure root privileges
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root. Please use sudo."
   exit 1
fi

# Function to fetch file (local or remote)
function fetch_file() {
    local filename=$1
    local target_path=$2
    
    if [[ -f "./$filename" ]]; then
        echo "Using local $filename..."
        cp -f "./$filename" "$target_path"
    else
        echo "Downloading $filename from repository..."
        curl -fsSL "$REPO_URL/$filename" -o "$target_path"
    fi
}

function install() {
    echo "Installing IP Tunnel Manager..."

    # Check for Python 3
    if ! command -v python3 &> /dev/null; then
        echo "Error: Python 3 is not installed."
        exit 1
    fi

    # 1. Create Directories
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$INSTALL_DIR"

    # 2. Install Python Script
    fetch_file "tunnel-manager.py" "$INSTALL_DIR/ip-tunnel-manager"
    chmod +x "$INSTALL_DIR/ip-tunnel-manager"

    # 3. Setup Default Configuration
    if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
        echo "Creating default configuration at $CONFIG_DIR/config.json..."
        cat > "$CONFIG_DIR/config.json" <<EOF
{
    "tunnels": {
        "example0": {
            "type": "gre",
            "remote": "1.2.3.4",
            "addresses": ["10.0.0.1/24"],
            "options": {
                "ttl": "64"
            }
        }
    }
}
EOF
    fi

    # 4. Install Systemd Units
    echo "Configuring systemd units..."
    
    # Process and install .service file
    local tmp_service=$(mktemp)
    fetch_file "ip-tunnel-manager.service" "$tmp_service"
    # Update paths to match installation
    sed -i "s|ExecStart=.*|ExecStart=$INSTALL_DIR/ip-tunnel-manager $CONFIG_DIR/config.json|" "$tmp_service"
    mv "$tmp_service" "/etc/systemd/system/$SERVICE_NAME"

    # Install .timer file
    fetch_file "ip-tunnel-manager.timer" "/etc/systemd/system/$TIMER_NAME"

    # 5. Reload and Enable
    systemctl daemon-reload
    systemctl enable "$TIMER_NAME"
    systemctl restart "$TIMER_NAME"

    echo "Installation complete!"
    echo "Configuration: $CONFIG_DIR/config.json"
    echo "Status: systemctl status $TIMER_NAME"
}

function uninstall() {
    echo "Uninstalling IP Tunnel Manager..."

    systemctl stop "$TIMER_NAME" 2>/dev/null || true
    systemctl disable "$TIMER_NAME" 2>/dev/null || true
    
    rm -f "/etc/systemd/system/$SERVICE_NAME"
    rm -f "/etc/systemd/system/$TIMER_NAME"
    rm -f "$INSTALL_DIR/ip-tunnel-manager"
    
    systemctl daemon-reload
    
    echo "Uninstall complete. Configuration in $CONFIG_DIR was preserved."
}

function status() {
    echo "--- IP Tunnel Manager Status ---"
    echo "Service: $(systemctl is-active $SERVICE_NAME)"
    echo "Timer:   $(systemctl is-active $TIMER_NAME)"
    echo ""
    systemctl status "$TIMER_NAME" --no-pager
}

# Main Command Handling
COMMAND=${1:-install}

case "$COMMAND" in
    install)
        install
        ;;
    uninstall)
        uninstall
        ;;
    status)
        status
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "Unknown command: $COMMAND"
        show_help
        exit 1
        ;;
esac
