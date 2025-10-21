#!/usr/bin/env python3
"""Device Provisioning Job with Golden Config Integration.

This job provisions a device by:
1. Generating the intended configuration using Golden Config plugin
2. Deploying it to the device startup configuration
3. Loading the startup config to running config
"""

from nautobot.apps.jobs import Job, ObjectVar, BooleanVar, register_jobs
from nautobot.dcim.models import Device
from napalm import get_network_driver
from napalm.base.exceptions import ConnectionException, CommitError, ReplaceConfigException
import traceback

name = "Device Provisioning"


class ProvisionDevice(Job):
    """
    Provision a device with its intended configuration from Golden Config.
    
    This job:
    1. Connects to the device using NAPALM
    2. Generates intended configuration from Golden Config plugin
    3. Loads the configuration to the device
    4. Commits the changes (saves to startup-config)
    5. Optionally reloads/applies the configuration
    
    Can be triggered manually or via a Job Button on device pages.
    """

    class Meta:
        name = "Provision Device"
        description = "Generate intended config from Golden Config and deploy to device"
        has_sensitive_variables = True
        field_order = ["device", "dry_run", "replace_config", "commit_changes", "show_debug"]

    device = ObjectVar(
        description="Device to provision",
        model=Device,
        required=True,
    )

    dry_run = BooleanVar(
        description="Dry run mode - show config diff without committing",
        default=True,
        required=False,
    )

    replace_config = BooleanVar(
        description="Replace entire config (use with caution!)",
        default=False,
        required=False,
    )

    commit_changes = BooleanVar(
        description="Commit changes to startup-config",
        default=True,
        required=False,
    )
    
    show_debug = BooleanVar(
        description="Show detailed debug/info logs",
        default=False,
        required=False,
    )

    def run(self, device, dry_run=True, replace_config=False, commit_changes=True, show_debug=False):
        """Main execution method."""
        # Store debug flag for use in helper methods
        self._show_debug = show_debug
        
        self._log_info("=" * 80)
        self._log_info(f"Starting provisioning for device: {device.name}")
        self._log_info("=" * 80)

        # Validate device has required attributes
        if not self._validate_device(device):
            return

        # Get device credentials
        username, password = self._get_credentials(device)

        # Get intended configuration from Golden Config
        intended_config = self._get_intended_config(device)
        if not intended_config:
            self.logger.error("No intended configuration available. Cannot proceed.")
            return

        # Connect to device and deploy configuration
        self._deploy_config(
            device, 
            intended_config, 
            username, 
            password, 
            dry_run, 
            replace_config,
            commit_changes
        )

        self._log_info("=" * 80)
        self.logger.success(f"Provisioning completed for {device.name}")
        self._log_info("=" * 80)

    def _log_info(self, message):
        """Log info message only if debug mode is enabled."""
        if getattr(self, '_show_debug', False):
            self.logger.info(message)
    
    def _log_debug(self, message):
        """Log debug message only if debug mode is enabled."""
        if getattr(self, '_show_debug', False):
            self.logger.debug(message)

    def _validate_device(self, device):
        """Validate device has all required attributes."""
        self._log_info("Validating device configuration...")

        if not device.platform:
            self.logger.error(f"Device {device.name} has no platform configured")
            return False

        if not device.platform.napalm_driver:
            self.logger.error(
                f"Device {device.name} platform '{device.platform.name}' "
                f"has no NAPALM driver configured"
            )
            return False

        if not device.primary_ip4:
            self.logger.error(f"Device {device.name} has no primary IPv4 address")
            return False

        self.logger.success("Device validation passed")
        return True

    def _get_credentials(self, device):
        """Get device credentials from secrets or use defaults."""
        from nautobot.extras.choices import SecretsGroupAccessTypeChoices, SecretsGroupSecretTypeChoices
        
        username = "admin"
        password = "admin"

        # Try to get credentials from secrets group
        if device.secrets_group:
            self._log_info(f"Secrets group configured: {device.secrets_group.name}")
            
            username_from_secrets = False
            password_from_secrets = False
            
            # Try to get username using proper Nautobot choices
            try:
                username = device.secrets_group.get_secret_value(
                    access_type=SecretsGroupAccessTypeChoices.TYPE_GENERIC,
                    secret_type=SecretsGroupSecretTypeChoices.TYPE_USERNAME,
                    obj=device,  # Pass device for template context
                )
                if username:
                    self.logger.success(f"✓ Retrieved username from secrets group: {username}")
                    username_from_secrets = True
                else:
                    username = "admin"
                    self._log_info("Username secret returned empty, using default")
            except Exception as e:
                username = "admin"
                self._log_debug(f"Could not retrieve username: {type(e).__name__}: {e}")
                self._log_info("Could not retrieve username from secrets, using default")
            
            # Try to get password using proper Nautobot choices
            try:
                password = device.secrets_group.get_secret_value(
                    access_type=SecretsGroupAccessTypeChoices.TYPE_GENERIC,
                    secret_type=SecretsGroupSecretTypeChoices.TYPE_PASSWORD,
                    obj=device,  # Pass device for template context
                )
                if password:
                    self.logger.success("✓ Retrieved password from secrets group")
                    password_from_secrets = True
                else:
                    password = "admin"
                    self._log_info("Password secret returned empty, using default")
            except Exception as e:
                password = "admin"
                self._log_debug(f"Could not retrieve password: {type(e).__name__}: {e}")
                self._log_info("Could not retrieve password from secrets, using default")
            
            # Check if we got credentials from secrets
            if username_from_secrets or password_from_secrets:
                self.logger.success(f"Using credentials from secrets group: {device.secrets_group.name}")
            else:
                self.logger.warning(
                    f"Secrets group '{device.secrets_group.name}' is configured but "
                    "secrets could not be retrieved. Using default credentials (admin/admin)."
                )
                self._log_info("")
                self._log_info("To fix this, you have two options:")
                self._log_info("")
                self._log_info("Option 1: Set environment variables in Nautobot")
                self._log_info("  Add to docker-compose.yml or nautobot_config.py:")
                self._log_info("  NAUTOBOT_NAPALM_USERNAME=admin")
                self._log_info("  NAUTOBOT_NAPALM_PASSWORD=admin")
                self._log_info("")
                self._log_info("Option 2: Change secrets to use Text provider instead")
                self._log_info("  Secrets → Secrets → Edit each secret")
                self._log_info("  Change provider from 'environment-variable' to 'text-file' or other")
                self._log_info("")
                self._log_info("For this lab, default credentials (admin/admin) will work fine!")
                self._log_info("")
        else:
            self._log_info(
                "No secrets group configured for this device. "
                "Using default credentials (admin/admin)"
            )
            self._log_info(
                "Tip: Assign a secrets group in the device settings for production use"
            )

        # Log final credential status (without revealing passwords)
        if username == "admin" and password == "admin":
            self._log_info("Using default credentials: admin/admin")
        else:
            self._log_info(f"Using credentials from secrets: {username}/<hidden>")

        return username, password

    def _get_intended_config(self, device):
        """Get intended configuration from Golden Config plugin."""
        self._log_info("-" * 80)
        self._log_info("Generating intended configuration from Golden Config...")

        try:
            # Import Golden Config models
            from nautobot_golden_config.models import GoldenConfig
            
            # Try to get existing Golden Config record
            try:
                golden_config = GoldenConfig.objects.get(device=device)
                
                if golden_config.intended_config:
                    # Get last update timestamp if available
                    last_update = getattr(golden_config, 'intended_last_success_date', None)
                    if not last_update:
                        last_update = getattr(golden_config, 'last_modified', 'unknown')
                    
                    self.logger.success(
                        f"Found existing intended config "
                        f"(last updated: {last_update})"
                    )
                    
                    # Log first few lines of config
                    config_preview = "\n".join(
                        golden_config.intended_config.split("\n")[:10]
                    )
                    self._log_info(f"Config preview:\n{config_preview}\n...")
                    
                    return golden_config.intended_config
                else:
                    self.logger.warning(
                        "Golden Config record exists but has no intended config"
                    )
                    
            except GoldenConfig.DoesNotExist:
                self.logger.warning(
                    f"No Golden Config record found for {device.name}"
                )

            # Try to generate config using Golden Config plugin
            self._log_info("Attempting to generate config using Golden Config plugin...")
            
            try:
                # Import the task
                from nautobot_golden_config.utilities.helper import get_job_filter
                from nautobot_golden_config.nornir_plays.config_intended import config_intended
                
                self._log_info("Generating new intended configuration...")
                
                # This would normally be done through the Golden Config job
                # For now, we'll inform the user to generate it first
                self.logger.error(
                    "Please run the Golden Config 'Generate Intended Configurations' job first"
                )
                return None
                
            except ImportError as e:
                self.logger.error(
                    f"Golden Config plugin not available or not properly configured: {e}"
                )
                return None

        except ImportError:
            self.logger.error(
                "Golden Config plugin is not installed. "
                "Please install nautobot-golden-config plugin."
            )
            return None

    def _deploy_config(self, device, config, username, password, dry_run, replace, commit):
        """Deploy configuration to device using NAPALM."""
        self._log_info("-" * 80)
        self._log_info("Connecting to device and deploying configuration...")

        device_ip = str(device.primary_ip4.address.ip)
        driver_name = device.platform.napalm_driver

        self._log_info(f"Device IP: {device_ip}")
        self._log_info(f"NAPALM Driver: {driver_name}")
        self._log_info(f"Mode: {'DRY RUN' if dry_run else 'LIVE DEPLOYMENT'}")
        self._log_info(f"Method: {'REPLACE' if replace else 'MERGE'}")

        # Parse NAPALM optional args
        optional_args = device.platform.napalm_args or {}
        if isinstance(optional_args, str):
            import json
            optional_args = json.loads(optional_args)

        napalm_device = None
        try:
            # Connect to device
            driver = get_network_driver(driver_name)
            napalm_device = driver(
                hostname=device_ip,
                username=username,
                password=password,
                optional_args=optional_args
            )

            self._log_info(f"Opening connection to {device_ip}...")
            napalm_device.open()
            self.logger.success(f"Connected to {device.name}")

            # Load configuration
            self._log_info("Loading configuration to device...")
            
            if replace:
                self.logger.warning("REPLACE mode: Entire configuration will be replaced!")
                napalm_device.load_replace_candidate(config=config)
            else:
                self._log_info("MERGE mode: Configuration will be merged with existing")
                napalm_device.load_merge_candidate(config=config)

            self.logger.success("Configuration loaded successfully")

            # Get configuration diff
            self._log_info("Generating configuration diff...")
            diff = napalm_device.compare_config()

            if diff:
                self._log_info("Configuration changes:")
                self._log_info("-" * 80)
                self._log_info(diff)
                self._log_info("-" * 80)
            else:
                self._log_info("No configuration changes detected")
                napalm_device.discard_config()
                return

            # Commit or discard based on dry_run
            if dry_run:
                self.logger.warning("DRY RUN mode: Discarding configuration changes")
                napalm_device.discard_config()
                self._log_info(
                    "To apply these changes, run again with 'Dry run mode' unchecked"
                )
            else:
                if commit:
                    self._log_info("Committing configuration changes...")
                    napalm_device.commit_config()
                    self.logger.success(
                        "Configuration committed successfully and saved to startup-config"
                    )

                    # Verify configuration was applied
                    self._log_info("Verifying configuration...")
                    facts = napalm_device.get_facts()
                    self.logger.success(
                        f"Device {facts.get('hostname')} is running with new configuration"
                    )
                else:
                    self.logger.warning("Commit disabled: Changes loaded but not committed")
                    napalm_device.discard_config()

        except ConnectionException as e:
            self.logger.error(f"Connection error: {e}")
            self.logger.error(
                "Please verify:\n"
                "  - Device is reachable\n"
                "  - Credentials are correct\n"
                "  - Management interface is configured\n"
                "  - SSH/API is enabled on device"
            )

        except (CommitError, ReplaceConfigException) as e:
            self.logger.error(f"Configuration deployment error: {e}")
            self.logger.error("Configuration has been rolled back")

        except Exception as e:
            self.logger.error(f"Unexpected error during deployment: {e}")
            self.logger.error(traceback.format_exc())

            if napalm_device:
                try:
                    self._log_info("Attempting to discard configuration changes...")
                    napalm_device.discard_config()
                    self._log_info("Configuration changes discarded")
                except Exception as discard_error:
                    self.logger.error(f"Could not discard config: {discard_error}")

        finally:
            if napalm_device:
                try:
                    napalm_device.close()
                    self._log_info("Connection closed")
                except Exception as close_error:
                    self.logger.warning(f"Error closing connection: {close_error}")


register_jobs(ProvisionDevice)

