# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
IXIA Configuration Cache for TAAC.

This module provides functionality to save and load IXIA .ixncfg configurations
directly on the IXIA chassis, significantly reducing test setup time by avoiding
the need to reconfigure IXIA from scratch on each run.

Usage:
    # In TaacIxia or test setup:

    # Try to load existing config
    config_path = f"/root/taac_configs/{test_config_name}.ixncfg"
    if ixia.load_config_from_chassis(config_path):
        # Fast path - config loaded successfully
        pass
    else:
        # Fallback - do full IXIA setup
        ixia.setup_protocols()
        ixia.setup_traffic_items()
        # Save for next time
        ixia.save_config_to_chassis(config_path)

File Location on IXIA Chassis:
    /root/taac_configs/<test_config_name>.ixncfg
"""

import logging
import typing as t

# Default path on IXIA chassis for storing configs
IXIA_CONFIG_DIR = "/root/taac_configs"


class IxiaConfigCache:
    """
    Simple cache manager for IXIA .ixncfg configurations.

    Stores IXIA configs directly on the IXIA chassis filesystem.
    Uses IXIA's native .ixncfg format for reliable save/restore.
    """

    def __init__(
        self,
        logger: logging.Logger,
        config_dir: str = IXIA_CONFIG_DIR,
    ):
        """
        Initialize the IXIA config cache.

        Args:
            logger: Logger instance for logging messages
            config_dir: Directory on IXIA chassis to store configs
        """
        self.logger = logger
        self.config_dir = config_dir

    def get_config_path(self, test_config_name: str) -> str:
        """
        Get the full file path for a cached config on the IXIA chassis.

        Args:
            test_config_name: Name of the test configuration (e.g., "bag002_snc1")

        Returns:
            Full path to the .ixncfg file (e.g., "/root/taac_configs/bag002_snc1.ixncfg")
        """
        return f"{self.config_dir}/{test_config_name}.ixncfg"

    def save_config(
        self,
        ixnetwork_session: t.Any,
        test_config_name: str,
    ) -> bool:
        """
        Save current IXIA configuration to chassis as .ixncfg file.

        Args:
            ixnetwork_session: The IxNetwork session object
            test_config_name: Name of the test configuration

        Returns:
            True if save was successful, False otherwise
        """
        config_path = self.get_config_path(test_config_name)

        try:
            # Ensure directory exists on chassis
            # IxNetwork API handles this when saving
            self.logger.info(f"Saving IXIA config to chassis: {config_path}")

            # Save using IxNetwork's native SaveConfig
            # This saves the complete session state in .ixncfg format
            ixnetwork_session.SaveConfig(config_path)

            self.logger.info(f"Successfully saved IXIA config: {config_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save IXIA config to chassis: {e}")
            return False

    def load_config(
        self,
        ixnetwork_session: t.Any,
        test_config_name: str,
    ) -> bool:
        """
        Load IXIA configuration from chassis .ixncfg file.

        Args:
            ixnetwork_session: The IxNetwork session object
            test_config_name: Name of the test configuration

        Returns:
            True if load was successful, False otherwise
        """
        config_path = self.get_config_path(test_config_name)

        try:
            self.logger.info(
                f"Attempting to load IXIA config from chassis: {config_path}"
            )

            # Load using IxNetwork's native LoadConfig
            # This restores the complete session state from .ixncfg
            ixnetwork_session.LoadConfig(config_path)

            self.logger.info(f"Successfully loaded IXIA config: {config_path}")
            return True

        except Exception as e:
            # File doesn't exist or load failed - this is expected on first run
            self.logger.info(
                f"Could not load IXIA config from {config_path}: {e}. "
                "Will fall back to full setup."
            )
            return False

    def config_exists(
        self,
        ixnetwork_session: t.Any,
        test_config_name: str,
    ) -> bool:
        """
        Check if a cached config exists on the IXIA chassis.

        Args:
            ixnetwork_session: The IxNetwork session object
            test_config_name: Name of the test configuration

        Returns:
            True if config file exists, False otherwise
        """
        try:
            # Use IxNetwork's file operations to check existence
            files = ixnetwork_session.GetFileList(self.config_dir)
            filename = f"{test_config_name}.ixncfg"
            return filename in files
        except Exception as e:
            self.logger.debug(f"Could not check config existence: {e}")
            return False

    def delete_config(
        self,
        ixnetwork_session: t.Any,
        test_config_name: str,
    ) -> bool:
        """
        Delete a cached config from the IXIA chassis.

        Args:
            ixnetwork_session: The IxNetwork session object
            test_config_name: Name of the test configuration

        Returns:
            True if deletion was successful, False otherwise
        """
        config_path = self.get_config_path(test_config_name)

        try:
            self.logger.info(f"Deleting IXIA config from chassis: {config_path}")
            ixnetwork_session.DeleteFile(config_path)
            self.logger.info(f"Successfully deleted IXIA config: {config_path}")
            return True
        except Exception as e:
            self.logger.warning(f"Could not delete IXIA config {config_path}: {e}")
            return False
