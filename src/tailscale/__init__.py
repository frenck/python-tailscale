"""Asynchronous Python client for the Tailscale API."""

from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
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
    Latency,
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
    "Latency",
    "Tailscale",
    "TailscaleAuthenticationError",
    "TailscaleConnectionError",
    "TailscaleError",
    "TailscaleUser",
    "TokenStorage",
]
