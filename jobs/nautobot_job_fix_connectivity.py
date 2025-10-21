#!/usr/bin/env python3
"""
Nautobot Job: Fix Network Connectivity

This is a Nautobot Job version of the 4b_config_arista_template_fix.py script.
It demonstrates how to convert a standalone Python script to a Nautobot Job.

CONVERSION HIGHLIGHTS:
- Static inventory → Dynamic Nautobot database queries
- Hardcoded device list → Device selection from database
- print() statements → self.logger methods
- No error handling → Comprehensive error handling
- Single execution → Dry-run mode support

ORIGINAL SCRIPT: 4b_config_arista_template_fix.py
CONVERTED TO: Nautobot Job (this file)

See: SCRIPT_TO_JOB_CONVERSION.md for detailed conversion guide
"""

from nautobot.apps.jobs import Job, MultiObjectVar, BooleanVar, register_jobs
from nautobot.dcim.models import Device
from jinja2 import Environment, BaseLoader

try:
    import pyeapi
    PYEAPI_AVAILABLE = True
except ImportError:
    PYEAPI_AVAILABLE = False

name = "Network Fixes"


class FixNetworkConnectivity(Job):
    """
    Fix network connectivity by enabling Ethernet2 interfaces.
    
    This job:
    1. Finds devices with Ethernet2 interfaces
    2. Renders configuration using Jinja2 template
    3. Enables interfaces and adds loopback
    4. Pushes config to devices via eAPI
    
    This is a direct conversion from the standalone script
    4b_config_arista_template_fix.py to demonstrate migration to Nautobot.
    """

    class Meta:
        name = "Fix Network Connectivity (Enable Ethernet2)"
        description = "Enable Ethernet2 interfaces and add loopback - converted from script"
        has_sensitive_variables = False
        field_order = ["devices", "dry_run", "commit_changes"]

    devices = MultiObjectVar(
        description="Devices to configure (leave empty to auto-discover Arista devices with Ethernet2)",
        model=Device,
        required=False,
    )

    dry_run = BooleanVar(
        description="Dry run - show config without pushing to devices",
        default=True,
        required=False,
    )

    commit_changes = BooleanVar(
        description="Save configuration to device (write memory)",
        default=True,
        required=False,
    )

    # Same template as original script
    TEMPLATE = """
!
! === FIX: Enable Ethernet2 interfaces ===
!
{% for iface in device.interfaces %}
interface {{ iface.name }}
  description {{ iface.description }}
  switchport mode access
  switchport access vlan {{ iface.vlan }}
  no shutdown
!
{% endfor %}
!
! === Add Loopback interface (for {{ device.name }}) ===
!
interface Loopback0
  description {{ device.name }} Loopback - Reachable from data plane
  ip address {{ device.loopback_ip }}/32
  no shutdown
!
end
"""

    def run(self, devices=None, dry_run=True, commit_changes=True):
        """Main execution method."""
        
        # Check if pyeapi is available
        if not PYEAPI_AVAILABLE:
            self.logger.error("pyeapi library is not installed")
            self.logger.error("Install with: pip install pyeapi")
            return

        self.logger.info("=" * 80)
        self.logger.info("Fix Network Connectivity Job")
        self.logger.info("=" * 80)

        # If no devices specified, auto-discover
        if not devices:
            self.logger.info("No devices specified - auto-discovering Arista devices with Ethernet2...")
            devices = self._discover_devices()
        
        if not devices:
            self.logger.warning("No devices found to configure")
            return

        self.logger.info(f"Found {len(devices)} device(s) to configure")
        self.logger.info("")

        # Process each device
        for device in devices:
            self._process_device(device, dry_run, commit_changes)

        self.logger.info("=" * 80)
        self.logger.success(f"Completed processing {len(devices)} device(s)")
        self.logger.info("=" * 80)

    def _discover_devices(self):
        """
        Discover devices that need configuration.
        
        Finds Arista devices with Ethernet2 interfaces.
        This replaces the hardcoded ARISTA_DEVICES list from the script.
        """
        from nautobot.dcim.models import Interface
        
        # Find Arista devices with Ethernet2 interface
        devices = Device.objects.filter(
            platform__name__icontains="Arista",
            interfaces__name="Ethernet2"
        ).distinct()

        self.logger.info(f"Auto-discovered {devices.count()} Arista device(s) with Ethernet2")
        
        for device in devices:
            self.logger.info(f"  - {device.name} ({device.primary_ip4.address if device.primary_ip4 else 'No IP'})")
        
        return devices

    def _process_device(self, device, dry_run, commit_changes):
        """Process a single device."""
        self.logger.info("-" * 80)
        self.logger.info(f"Processing device: {device.name}")
        
        # Validate device
        if not self._validate_device(device):
            return
        
        # Get device data for template
        device_data = self._get_device_data(device)
        
        # Render configuration
        rendered_config = self._render_config(device_data)
        
        # Show rendered configuration
        self.logger.info("Rendered configuration:")
        self.logger.info("-" * 80)
        self.logger.info(rendered_config)
        self.logger.info("-" * 80)
        
        # Push to device (if not dry run)
        if dry_run:
            self.logger.warning(f"DRY RUN mode - configuration NOT pushed to {device.name}")
            self.logger.info("Run again with 'Dry run' unchecked to apply changes")
        else:
            self._push_config_to_device(device, rendered_config, commit_changes)

    def _validate_device(self, device):
        """Validate device has required attributes."""
        
        # Check platform
        if not device.platform or "arista" not in device.platform.name.lower():
            self.logger.warning(f"Device {device.name} is not Arista platform - skipping")
            return False
        
        # Check primary IP
        if not device.primary_ip4:
            self.logger.error(f"Device {device.name} has no primary IPv4 address - skipping")
            return False
        
        # Check has Ethernet2
        if not device.interfaces.filter(name="Ethernet2").exists():
            self.logger.warning(f"Device {device.name} has no Ethernet2 interface - skipping")
            return False
        
        return True

    def _get_device_data(self, device):
        """
        Get device data for template rendering.
        
        This replaces the hardcoded device dictionaries from the script.
        Data is now pulled from Nautobot database.
        """
        from nautobot.dcim.models import Interface
        
        # Get Ethernet2 interface
        eth2 = device.interfaces.get(name="Ethernet2")
        
        # Get VLAN from interface (untagged_vlan for access ports)
        vlan_id = "10"  # Default
        if eth2.untagged_vlan:
            vlan_id = str(eth2.untagged_vlan.vid)
        
        # Build device data structure (same format as original script)
        device_data = {
            "name": device.name,
            "host": str(device.primary_ip4.address.ip),
            "loopback_ip": self._get_loopback_ip(device),
            "interfaces": [
                {
                    "name": eth2.name,
                    "description": eth2.description or f"Connected to {eth2.connected_endpoint}" if eth2.connected_endpoint else "Data interface",
                    "mode": "access",
                    "vlan": vlan_id,
                }
            ],
        }
        
        return device_data

    def _get_loopback_ip(self, device):
        """
        Get or assign loopback IP for device.
        
        In the original script, this was hardcoded.
        Here we could pull from Nautobot or calculate it.
        """
        # Check if device already has a loopback interface with IP
        loopback = device.interfaces.filter(name="Loopback0").first()
        if loopback and loopback.ip_addresses.exists():
            # Use existing loopback IP
            return str(loopback.ip_addresses.first().address.ip)
        
        # Otherwise, assign based on device name pattern (same as original script)
        loopback_mapping = {
            "access1": "10.99.1.1",
            "access2": "10.99.1.2",
            "dist1": "10.99.1.3",
            "rtr1": "10.0.0.254",
        }
        
        return loopback_mapping.get(device.name, "10.99.99.99")

    def _render_config(self, device_data):
        """
        Render Jinja2 template with device data.
        
        Same template logic as original script.
        """
        env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)
        template = env.from_string(self.TEMPLATE)
        rendered = template.render(device=device_data)
        return rendered

    def _push_config_to_device(self, device, rendered_config, commit_changes):
        """
        Push configuration to device via eAPI.
        
        Same as original script's push_config() function.
        """
        host = str(device.primary_ip4.address.ip)
        
        self.logger.info(f"Connecting to {device.name} at {host}...")
        
        try:
            # Connect to device (same as original script)
            connection = pyeapi.connect(
                transport="https",
                host=host,
                username="admin",
                password="admin",
                port=443,
            )
            node = pyeapi.client.Node(connection)
            
            # Filter out empty lines and comments (same as original)
            config_cmds = [
                line for line in rendered_config.splitlines()
                if line.strip() and not line.strip().startswith("!")
            ]
            
            if config_cmds:
                # Push configuration
                node.config(config_cmds)
                self.logger.success(f"Configuration pushed to {device.name}")
                
                # Save configuration (if requested)
                if commit_changes:
                    node.enable("write memory")
                    self.logger.success(f"Configuration saved on {device.name}")
                else:
                    self.logger.warning(f"Configuration NOT saved (write memory skipped)")
            else:
                self.logger.warning("No configuration commands to push")

        except Exception as e:
            self.logger.error(f"Failed to configure {device.name}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())


# Register the job with Nautobot
register_jobs(FixNetworkConnectivity)

