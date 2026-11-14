"""Configuration package — exposes the runtime settings singleton."""

from config.settings import Settings, get_settings, reload_settings, settings

__all__ = ["Settings", "get_settings", "reload_settings", "settings"]