"""Asynchronous Python client for the Tailscale API."""

from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
    TailscaleNotFoundError,
)
from .models import (
    ClientConnectivity,
    ClientSupports,
    Device,
    DeviceRoutes,
    Devices,
    DNSNameservers,
    DNSPreferences,
    DNSSearchPaths,
    KeyCapabilities,
    KeyCapabilitiesCreate,
    KeyCapabilitiesDevices,
    Latency,
    TailnetSettings,
    TailscaleKey,
    TailscaleUser,
)
from .storage import TokenStorage
from .tailscale import Tailscale

__all__ = [
    "ClientConnectivity",
    "ClientSupports",
    "DNSNameservers",
    "DNSPreferences",
    "DNSSearchPaths",
    "Device",
    "DeviceRoutes",
    "Devices",
    "KeyCapabilities",
    "KeyCapabilitiesCreate",
    "KeyCapabilitiesDevices",
    "Latency",
    "TailnetSettings",
    "Tailscale",
    "TailscaleAuthenticationError",
    "TailscaleConnectionError",
    "TailscaleError",
    "TailscaleKey",
    "TailscaleNotFoundError",
    "TailscaleUser",
    "TokenStorage",
]
