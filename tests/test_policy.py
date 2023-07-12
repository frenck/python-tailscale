"""Asynchronous client for the Tailscale API."""
# pylint: disable=protected-access
import asyncio
import json
from typing import Dict

import aiohttp
import pytest
from aresponses import Response, ResponsesMockServer

from tailscale import Tailscale
from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)
from tailscale.models import Policy

test_policy_1 = {
    "id": "test",
    "name": "test policy",
    "description": "This is a test policy",
    "users": ["user@example.com"],
    "nodes": ["test"],
    "tags": ["tag:golink"],
    "routes": ["10.0.0.0/8"],
    "denyUnknown": True,
    "allowAll": False,
    "logActivity": True,
    "bypass": False,
    "created": "2022-12-01T05:23:30Z",
    "lastModified": "2022-12-01T05:23:30Z",
}
