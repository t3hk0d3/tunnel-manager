#!/usr/bin/env python3

import subprocess
import sys
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import os

"""
IP Tunnel Manager - Manages Linux tunnels with configuration validation.

This module provides a TunnelManager class that manages multiple IP tunnels
defined in a JSON configuration file. It handles tunnel creation, address
assignment, interface state management, remote connectivity validation, and
route configuration.

Supported Tunnel Types:
- gre, ipip, sit, isatap, gretap, vti, and any other supported by 'ip link add'.

Configuration File Format (JSON):
{
    "tunnels": {
        "<tunnel_name>": {
            "type": "<type>",             # Tunnel mode (default: gre)
            "remote": "<remote_ip>",      # Remote endpoint IP address (required)
            "verify_ip": "<verify_ip>",   # Optional: ping this IP through the tunnel to verify connectivity
            "addresses": [                # List of IP addresses to assign
                "<ip_with_prefix>"        # CIDR notation (e.g., 192.168.1.1/24)
            ],
            "routes": [                   # Optional: routes to add via tunnel
                "<destination>"           # CIDR notation (default: 0.0.0.0/0, ::/0)
            ],
            "options": {                  # Optional: additional tunnel parameters
                "ttl": "64",              # Time To Live
                "key": "1234",            # Tunnel key
                "id": "5"                 # Tunnel ID (for VTI)
            }
        }
    }
}

Example Configuration:
{
    "tunnels": {
        "tunnel0": {
            "type": "gretap",
            "local": "203.0.113.5",
            "remote": "203.0.113.10",
            "verify_ip": "10.0.0.2",
            "addresses": [
                "10.0.0.1/24"
            ],
            "options": {
                "ttl": "64"
            }
        },
        "tunnel1": {
            "type": "vti",
            "remote": "203.0.113.20",
            "addresses": [
                "10.1.0.1/24"
            ],
            "options": {
                "key": "42"
            }
        }
    }
}
"""



# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class TunnelEntry:
    type: str = 'gre'
    remote: str = None
    addresses: List[str] = field(default_factory=list)
    local: str = None  # Optional, will be determined if not provided
    verify_ip: Optional[str] = None # Optional, ping this IP through the tunnel to verify connectivity
    routes: List[str] = field(default_factory=list)
    hooks: Dict[str, List[str]] = field(default_factory=dict)
    options: Dict[str, str] = field(default_factory=dict)

@dataclass
class AppConfig:
    tunnels: Dict[str, TunnelEntry] = field(default_factory=dict)
    hooks: Dict[str, List[str]] = field(default_factory=dict)

@dataclass
class TunnelConfig:
    """Loads and parses the JSON configuration file for tunnels."""
    config_file: str
    config: AppConfig = None

    def __post_init__(self):
        """Initialize the TunnelConfig by loading the configuration."""
        self.config = self._load_config()

    def _load_config(self) -> AppConfig:
        """Load JSON configuration file and parse into AppConfig dataclass."""
        try:
            with open(self.config_file, 'r') as f:
                raw_config = json.load(f) or {}
            
            global_hooks = raw_config.get('hooks', {})
            tunnels_data = raw_config.get('tunnels', {})
            app_tunnels = {}
            for name, data in tunnels_data.items():
                app_tunnels[name] = TunnelEntry(
                    type=data.get('type', 'gre').lower(),
                    remote=data.get('remote'),
                    addresses=data.get('addresses', []),
                    local=data.get('local'),
                    verify_ip=data.get('verify_ip'),
                    routes=data.get('routes', []),
                    hooks=data.get('hooks', {}),
                    options={str(k): str(v) for k, v in data.get('options', {}).items()}
                )
            return AppConfig(tunnels=app_tunnels, hooks=global_hooks)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            sys.exit(1)

    def get_config(self) -> AppConfig:
        """Get the loaded application configuration."""
        return self.config

class IpCommandExecutor:
    """Executes IP-related shell commands and handles their output."""
    def __init__(self):
        """Initialize the IpCommandExecutor."""
        pass

    def _run_cmd(self, cmd: List[str], check: bool = True) -> Tuple[int, str, str]:
        """
        Execute a shell command and return (returncode, stdout, stderr).
        Logs errors if the command fails.
        """
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=check
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}\n{e.stderr}")
            return e.returncode, e.stdout.strip(), e.stderr.strip()
        except Exception as e:
            logger.error(f"Command execution failed: {' '.join(cmd)}\n{e}")
            return -1, "", str(e)

    def tunnel_exists(self, name: str) -> bool:
        """Check if a tunnel interface with the given name exists."""
        code, output, _ = self._run_cmd(['ip', 'link', 'show', name], check=False)
        return code == 0

    def get_local_ip(self, remote_ip: str) -> str:
        """
        Determine the local IP address that would be used to route to a given remote IP.
        Returns an empty string if the local IP cannot be determined.
        """
        code, output, _ = self._run_cmd(['ip', 'route', 'get', remote_ip], check=False)
        if code != 0 or not output:
            return ""
        # Parse "src <local_ip>" from output
        for part in output.split():
            if part == 'src' and output.find('src') >= 0:
                idx = output.split().index('src')
                return output.split()[idx + 1]
        return ""

    def create_tunnel(self, name: str, tunnel_type: str, local: str = None, remote: str = None, options: Dict[str, str] = None) -> bool:
        """
        Create a new IP tunnel interface or update an existing one using 'ip link add' or 'ip link change'.
        Supports many tunnel types (gre, ipip, sit, isatap, gretap, vti, etc.)
        """
        options = options or {}
        exists = self.tunnel_exists(name)
        action = 'change' if exists else 'add'
        
        # Base command for modern tunnel creation/update
        cmd = ['ip', 'link', action, name, 'type', tunnel_type]
        
        # Only add remote/local if they are provided
        if remote:
            cmd.extend(['remote', remote])
        if local:
            cmd.extend(['local', local])
        
        # Add additional options (e.g., ttl, key, ikey, okey, id, dev, etc.)
        for key, value in options.items():
            cmd.extend([str(key), str(value)])
            
        code, output, err = self._run_cmd(cmd, check=False)
        if code == 0:
            logger.info(f"Tunnel {name} {'updated' if exists else 'created'} successfully with type {tunnel_type}")
            return True
        
        logger.error(f"Failed to {action} tunnel {name}: {err}")
        return False

    def get_assigned_ips(self, interface: str) -> List[str]:
        """Get a list of IP addresses assigned to a given network interface."""
        code, output, _ = self._run_cmd(['ip', 'addr', 'show', interface], check=False)
        ips = []
        if code == 0:
            for line in output.split('\n'):
                line = line.strip()
                # support both ipv4 and ipv6
                if line.startswith('inet ') or line.startswith('inet6 '):
                    parts = line.split()
                    if len(parts) >= 2:
                        # Sometimes inet6 has scope link which we might want to ignore, but we'll include it for completeness
                        if 'scope link' not in line:
                            ips.append(parts[1])
        return ips

    def assign_address(self, interface: str, address: str) -> bool:
        """Assign an IP address (CIDR) to a network interface."""
        cmd = ['ip', 'addr', 'add', address, 'dev', interface]
        code, out, err = self._run_cmd(cmd, check=False)
        if code != 0:
            logger.error(f"Failed to assign address {address} to {interface}: {err}")
            return False
        return True

    def remove_address(self, interface: str, address: str) -> bool:
        """Remove an IP address from a network interface."""
        cmd = ['ip', 'addr', 'del', address, 'dev', interface]
        code, _, err = self._run_cmd(cmd, check=False)
        if code != 0:
            logger.warning(f"Failed to remove address {address} from {interface}: {err}")
            return False
        return True

    def set_interface_up(self, interface: str) -> bool:
        """Bring a network interface up."""
        code, _, err = self._run_cmd(['ip', 'link', 'set', interface, 'up'], check=False)
        if code != 0:
            logger.error(f"Failed to bring {interface} up: {err}")
            return False
        code, output, _ = self._run_cmd(['ip', 'link', 'show', interface], check=False)
        return 'UP' in output

    def ping_remote(self, remote_ip: str, interface: str = None, count: int = 3) -> bool:
        """
        Ping a remote IP address to check connectivity.
        Returns True if the ping is successful (0% packet loss or at least half packets received).
        """
        cmd = ['ping', '-c', str(count), '-W', '2']
        if interface:
            cmd.extend(['-I', interface])
        cmd.append(remote_ip)
        code, output, _ = self._run_cmd(cmd, check=False)
        # Ping returns 0 if at least one response was heard, 1 if no response, 2 for other errors
        if code == 0 or '0% packet loss' in output or output.count('bytes from') >= count // 2:
            return True
        return False

    def add_route(self, interface: str, route: str) -> bool:
        """Add a route via the tunnel interface."""
        version = '-6' if ':' in route else '-4'
        cmd = ['ip', version, 'route', 'replace', route, 'dev', interface]
        code, _, err = self._run_cmd(cmd, check=False)
        if code == 0:
            logger.info(f"Route {route} via {interface} configured")
            return True
        logger.error(f"Failed to configure route {route} via {interface}: {err}")
        return False

    def remove_route(self, interface: str, route: str) -> bool:
        """Remove a route from the tunnel interface."""
        version = '-6' if ':' in route else '-4'
        cmd = ['ip', version, 'route', 'del', route, 'dev', interface]
        code, _, err = self._run_cmd(cmd, check=False)
        if code == 0:
            logger.info(f"Route {route} via {interface} removed")
            return True
        logger.error(f"Failed to remove route {route} via {interface}: {err}")
        return False

    def get_assigned_routes(self, interface: str) -> List[str]:
        """Get a list of routes assigned to a given network interface."""
        routes = []
        for version in ['-4', '-6']:
            code, output, _ = self._run_cmd(['ip', version, 'route', 'show', 'dev', interface], check=False)
            if code == 0:
                for line in output.split('\n'):
                    line = line.strip()
                    if line and 'proto kernel' not in line:
                        parts = line.split()
                        if len(parts) >= 1:
                            route = parts[0]
                            if route == 'default':
                                route = '0.0.0.0/0' if version == '-4' else '::/0'
                            routes.append(route)
        return routes


class HookExecutor:
    """Executes shell command hooks with environment context."""
    def __init__(self, logger):
        self.logger = logger

    def run_hooks(self, hooks: List[str], env: Dict[str, str] = None, event_name: str = ""):
        """Run a list of shell commands in a given environment."""
        if not hooks:
            return

        # Prepare environment
        hook_env = os.environ.copy()
        if env:
            hook_env.update(env)

        for cmd in hooks:
            self.logger.info(f"Executing hook [{event_name}]: {cmd}")
            try:
                # Use shell=True to allow complex commands
                subprocess.run(cmd, shell=True, env=hook_env, check=False)
            except Exception as e:
                self.logger.error(f"Failed to execute hook [{event_name}]: {cmd} - {e}")


class Tunnel:
    """Manages a single IP tunnel, including its creation, address assignment, and connectivity."""
    def __init__(self, name: str, config: TunnelEntry, ip_executor: IpCommandExecutor, hook_executor: HookExecutor):
        """Initialize a Tunnel instance.

        Args:
            name: The name of the tunnel interface (e.g., 'tunnel0').
            config: The TunnelEntry dataclass containing the tunnel's configuration.
            ip_executor: An instance of IpCommandExecutor to execute IP commands.
            hook_executor: An instance of HookExecutor to execute shell hooks.
        """
        self.name = name
        self.config = config
        self.ip_executor = ip_executor
        self.hook_executor = hook_executor

    def _get_hook_env(self) -> Dict[str, str]:
        """Prepare context variables for hooks as environment variables."""
        env = {
            'TUNNEL_NAME': self.name,
            'TUNNEL_TYPE': self.config.type,
            'REMOTE_IP': self.config.remote or '',
            'LOCAL_IP': self.config.local or '',
            'VERIFY_IP': self.config.verify_ip or '',
            'ADDRESSES': ' '.join(self.config.addresses),
            'ROUTES': ' '.join(self.config.routes)
        }
        # Add options to environment
        for k, v in self.config.options.items():
            env[f'TUNNEL_OPT_{k.upper()}'] = v
        return env

    def _run_hooks(self, event_name: str):
        """Run hooks for a specific event."""
        hooks = self.config.hooks.get(event_name, [])
        if hooks:
            env = self._get_hook_env()
            self.hook_executor.run_hooks(hooks, env, event_name)

    def _ensure_tunnel_exists(self, tunnel_type: str, local_ip: str, remote_ip: str, options: Dict[str, str]) -> bool:
        """Ensures the tunnel interface exists and has the correct parameters."""
        if not self.ip_executor.create_tunnel(self.name, tunnel_type, local_ip, remote_ip, options):
            return False
        return True

    def _configure_addresses(self, addresses: List[str]) -> bool:
        """Configures IP addresses for the tunnel interface, adding or removing as needed."""
        assigned = self.ip_executor.get_assigned_ips(self.name)
        
        # Compare by exact IP (without mask) to avoid partial matches like 10.0.0.1 matching 10.0.0.12
        def get_ip(cidr): return cidr.split('/')[0]

        target_ips = [get_ip(a) for a in addresses]
        
        for addr in assigned:
            if get_ip(addr) not in target_ips:
                self.ip_executor.remove_address(self.name, addr)
                logger.info(f"Tunnel {self.name}: removed {addr}")

        for addr in addresses:
            if get_ip(addr) not in [get_ip(ip) for ip in self.ip_executor.get_assigned_ips(self.name)]:
                if self.ip_executor.assign_address(self.name, addr):
                    logger.info(f"Tunnel {self.name}: assigned {addr}")
                else:
                    logger.error(f"Tunnel {self.name}: failed to assign {addr}")
                    return False
        return True

    def _configure_routes(self, routes: List[str]) -> bool:
        """Configures routes for the tunnel interface, replacing or removing as needed."""
        assigned = self.ip_executor.get_assigned_routes(self.name)
        
        # Normalize routes to match iproute2 output
        normalized_routes = []
        for r in routes:
            if r == 'default':
                normalized_routes.append('0.0.0.0/0')
            else:
                normalized_routes.append(r)
        
        for route in assigned:
            if route not in normalized_routes:
                self.ip_executor.remove_route(self.name, route)
                logger.info(f"Tunnel {self.name}: removed route {route}")
                
        for route in normalized_routes:
            if not self.ip_executor.add_route(self.name, route):
                logger.error(f"Tunnel {self.name}: failed to configure route {route}")
                return False
                
        return True

    def _bring_up_interface(self) -> bool:
        """Brings the tunnel interface up."""
        if not self.ip_executor.set_interface_up(self.name):
            logger.error(f"Tunnel {self.name}: failed to bring UP")
            return False
        return True

    def _verify_connectivity(self, verify_ip: str) -> bool:
        """Verifies connectivity to the given IP address via ping through the tunnel."""
        if not self.ip_executor.ping_remote(verify_ip, interface=self.name):
            logger.error(f"Tunnel {self.name}: cannot reach verify_ip {verify_ip} through interface")
            return False
        return True

    def manage(self) -> bool:
        """Main method to manage the tunnel lifecycle."""
        success = False
        try:
            self._run_hooks('before-manage')
            
            tunnel_type = self.config.type
            remote_ip = self.config.remote
            addresses = self.config.addresses
            routes = self.config.routes
            local_ip = self.config.local
            options = self.config.options

            # Auto-discover local IP if remote is provided but local is not
            if not local_ip and remote_ip:
                local_ip = self.ip_executor.get_local_ip(remote_ip)
                if not local_ip:
                    logger.error(f"Tunnel {self.name}: cannot determine local IP for {remote_ip}")
                    return False
                # Update config for hook context
                self.config.local = local_ip

            self._run_hooks('before-create')
            if not self._ensure_tunnel_exists(tunnel_type, local_ip, remote_ip, options):
                return False
            self._run_hooks('after-create')
            
            self._run_hooks('before-configured')
            if not self._configure_addresses(addresses):
                return False

            if not self._bring_up_interface():
                return False
            self._run_hooks('after-configured')

            # Verification - only if verify_ip is provided
            verify_ip = self.config.verify_ip
            if verify_ip:
                self._run_hooks('before-verify')
                if not self._verify_connectivity(verify_ip):
                    return False
                self._run_hooks('after-verify')
            
            self._run_hooks('before-routing')
            if not self._configure_routes(routes):
                return False
            self._run_hooks('after-routing')

            logger.info(f"Tunnel {self.name} is operational")
            success = True
            self._run_hooks('on-success')
            return True

        except Exception as e:
            logger.error(f"Tunnel {self.name}: management failed - {e}")
            return False
        finally:
            if not success:
                self._run_hooks('on-failure')
            self._run_hooks('always')


class TunnelManager:
    """Orchestrates the management of multiple IP tunnels based on a configuration file."""
    def __init__(self, config_file: str):
        """Initialize the TunnelManager.

        Args:
            config_file: The path to the JSON configuration file.
        """
        self.config_file = config_file
        self.tunnel_config = TunnelConfig(config_file)
        self.app_config = self.tunnel_config.get_config()
        self.ip_executor = IpCommandExecutor()
        self.hook_executor = HookExecutor(logger)

    def run(self):
        """Manages all configured tunnels by iterating through them and applying their settings."""
        # Run global before-all hooks
        global_hooks = self.app_config.hooks
        if 'before-all' in global_hooks:
            self.hook_executor.run_hooks(global_hooks['before-all'], event_name='before-all')

        if not self.app_config.tunnels:
            logger.warning("No tunnels configured")
        else:
            for name, tunnel_entry in self.app_config.tunnels.items():
                tunnel = Tunnel(name, tunnel_entry, self.ip_executor, self.hook_executor)
                tunnel.manage()

        # Run global after-all hooks
        if 'after-all' in global_hooks:
            self.hook_executor.run_hooks(global_hooks['after-all'], event_name='after-all')

if __name__ == '__main__':
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    elif 'TUNNEL_MANAGER_CONFIG' in os.environ:
        config_file = os.environ['TUNNEL_MANAGER_CONFIG']
    else:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        local_config = os.path.join(script_dir, 'config.json')
        if os.path.isfile(local_config):
            config_file = local_config
        else:
            config_file = '/etc/ip-tunnel-manager/config.json'

    manager = TunnelManager(config_file)
    manager.run()