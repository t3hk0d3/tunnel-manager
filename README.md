# IP Tunnel Manager

IP Tunnel Manager is a lightweight Python utility designed to automate the creation and management of Linux network tunnels. It uses a declarative configuration to define tunnel parameters, addresses, and routes, and includes a flexible hook system for custom lifecycle automation.

## Features

- **Protocol Support**: Supports `GRE`, `SIT`, `IPIP`, `ISATAP`, `GRETAP`, `VTI`, and any other tunnel types supported by the `ip link` subsystem.
- **Modern Command Architecture**: Utilizes `ip link add` for more flexible tunnel creation and configuration.
- **Declarative Configuration**: Define all tunnels in a single JSON file.
- **Advanced Options**: Support for specifying tunnel attributes like `TTL`, `Key`, `ID`, and more.
- **Automatic IP Discovery**: Automatically determines the local endpoint IP if not explicitly provided.
- **Address & Route Management**: Handles assignment of multiple IP addresses and routing table entries.
- **Connectivity Validation**: Optional built-in ping verification to ensure tunnels are operational (`verify_ip`).
- **Extensive Hook System**: Execute custom shell commands at every stage of the tunnel lifecycle (global and per-tunnel).
- **Systemd Integration**: Includes a service unit and a timer for periodic tunnel health checks and management.

## Prerequisites

- Linux OS with `iproute2` and `ping` installed.
- Python 3.7 or higher (for `dataclasses` support).
- No additional libraries required (uses Python standard library).

## Installation

The easiest way to install the IP Tunnel Manager is by using the automated installation script.

```bash
curl -sSL https://raw.githubusercontent.com/t3hk0d3/tunnel-manager/refs/heads/master/install.sh | sudo bash
```

This script will:
1.  Install the `ip-tunnel-manager` script to `/usr/local/bin/`.
2.  Set up a default configuration in `/etc/ip-tunnel-manager/config.json`.
3.  Install and enable a systemd timer to run the manager every 5 minutes.

### Manual Setup (Optional)

If you prefer to install it manually:

1. **Download and unpack the repository**:
   ```bash
   git clone https://github.com/tehkode/tunnel-manager.git
   cd tunnel-manager
   ```

2. **Run the local install script**:
   ```bash
   sudo ./install.sh
   ```

3. **Or configure systemd manually**:
   ```bash
   sudo mkdir -p /etc/ip-tunnel-manager
   sudo cp ip-tunnel-manager.service ip-tunnel-manager.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now ip-tunnel-manager.timer
   ```

## Configuration

The manager looks for a configuration file in the following order:
1.  **Command-line argument**: `python tunnel-manager.py /path/to/config.json`
2.  **Environment variable**: `TUNNEL_MANAGER_CONFIG=/path/to/config.json python tunnel-manager.py`
3.  **Default path**: `/etc/ip-tunnel-manager/config.json`

The configuration format should be valid JSON.

### Example `config.json`

```json
{
  "hooks": {
    "before-all": [
      "echo 'Starting tunnel management...'"
    ]
  },
  "tunnels": {
    "gre-tunnel0": {
      "type": "gre",
      "local": "203.0.113.5",
      "remote": "203.0.113.10",
      "verify_ip": "10.0.0.2",
      "addresses": [
        "10.0.0.1/24"
      ],
      "routes": [
        "192.168.100.0/24"
      ],
      "options": {
        "ttl": "64"
      },
      "hooks": {
        "after-create": [
          "echo 'Interface $TUNNEL_NAME created!'"
        ]
      }
    },
    "vti-tunnel1": {
      "type": "vti",
      "remote": "203.0.113.20",
      "addresses": [
        "10.1.0.1/24"
      ],
      "options": {
        "key": "42",
        "id": "1"
      }
    }
  }
}
```

### Tunnel Parameters
- `type`: Tunnel mode (e.g., `gre`, `sit`, `ipip`, `isatap`, `gretap`, `vti`).
- `remote`: Remote endpoint IP address (required).
- `local`: Local endpoint IP (optional; auto-discovered if omitted).
- `addresses`: List of IP addresses (CIDR) to assign to the tunnel interface.
- `routes`: Optional list of destinations to route via this tunnel.
- `options`: Key-value pairs for additional tunnel attributes like `ttl`, `key`, `id`, `dev`, etc.

### Hook Environment Variables
When a hook is executed, it has access to the following environment variables:
- `TUNNEL_NAME`: Name of the interface (e.g., `tunnel0`).
- `TUNNEL_TYPE`: Type of tunnel.
- `REMOTE_IP`: The remote endpoint.
- `LOCAL_IP`: The local endpoint used.
- `ADDRESSES`: Space-separated list of assigned addresses.
- `ROUTES`: Space-separated list of configured routes.
- `TUNNEL_OPT_<OPTION>`: Values from the `options` dictionary (e.g., `TUNNEL_OPT_TTL`).

## Usage

### Manual Execution

You can run the manager manually and specify a configuration file:

```bash
sudo python3 tunnel-manager.py /path/to/your/config.json
```

### Systemd Service & Timer

The manager includes two systemd units for automation:

#### `ip-tunnel-manager.service`
A `oneshot` service that runs the tunnel manager once and exits.

#### `ip-tunnel-manager.timer`
A timer that triggers the service every 5 minutes (default). This ensures that tunnels are automatically re-created or fixed if they go down.

```bash
# Start and enable the timer (recommended)
sudo systemctl enable --now ip-tunnel-manager.timer

# Run the service immediately (manual trigger)
sudo systemctl start ip-tunnel-manager.service

# Check timer status
systemctl status ip-tunnel-manager.timer

# View execution logs
sudo journalctl -u ip-tunnel-manager.service
```

## Lifecycle Hooks

The following events can trigger hooks:

| Hook Event | Scope | Description |
| :--- | :--- | :--- |
| `before-all` | Global | Runs before processing any tunnels. |
| `after-all` | Global | Runs after all tunnels have been processed. |
| `before-manage` | Tunnel | Runs at the very start of tunnel processing. |
| `before-create` | Tunnel | Runs before `ip tunnel add`. |
| `after-create` | Tunnel | Runs after the tunnel interface is created. |
| `before-configured`| Tunnel | Runs before IP addresses are assigned. |
| `after-configured` | Tunnel | Runs after IPs are assigned and interface is UP. |
| `before-verify` | Tunnel | Runs before connectivity check (ping). |
| `after-verify` | Tunnel | Runs after successful connectivity check. |
| `before-routing` | Tunnel | Runs before adding routes. |
| `after-routing` | Tunnel | Runs after routes are successfully added. |
| `on-success` | Tunnel | Runs only if the entire setup for the tunnel succeeded. |
| `on-failure` | Tunnel | Runs if any part of the setup failed. |
| `always` | Tunnel | Runs at the end regardless of success or failure. |

## WireGuard via Hooks

Since WireGuard interfaces are managed via the `wg` tool, you can use hooks to handle the setup while the manager handles interface creation, IP addresses, and routing:

```json
"wg-vpn": {
  "type": "wireguard",
  "addresses": ["10.8.0.2/24"],
  "hooks": {
    "after-create": ["wg set $TUNNEL_NAME private-key /path/to/key peer <PUBKEY> endpoint 1.2.3.4:51820"]
  }
}
```

The manager natively handles the creation of the `wireguard` interface. By using the `after-create` hook, you can apply your specific peer and key configuration. If you omit `remote` and `local`, the manager will skip the connectivity verification (ping) phase.

## License

MIT License
