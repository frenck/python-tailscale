# Python: Asynchronous client for the Tailscale API

[![GitHub Release][releases-shield]][releases]
[![Python Versions][python-versions-shield]][pypi]
![Project Stage][project-stage-shield]
![Project Maintenance][maintenance-shield]
[![License][license-shield]](LICENSE.md)

[![Build Status][build-shield]][build]
[![Code Coverage][codecov-shield]][codecov]
[![OpenSSF Scorecard][scorecard-shield]][scorecard]
[![Open in Dev Containers][devcontainer-shield]][devcontainer]

[![Sponsor Frenck via GitHub Sponsors][github-sponsors-shield]][github-sponsors]

[![Support Frenck on Patreon][patreon-shield]][patreon]

Asynchronous Python client for the Tailscale API.

## About

This package allows you to control and monitor Tailscale clients
programmatically. It is mainly created to allow third-party programs to
integrate with Tailscale.

An excellent example of this might be Home Assistant, which allows you to write
automations based on the status of your Tailscale network devices.

## Installation

```bash
pip install tailscale
```

To install with the optional CLI:

```bash
pip install "tailscale[cli]"
```

## CLI

The optional CLI lets you query and manage your tailnet directly from
the terminal. The `--api-key` option can also be set via the
`TAILSCALE_API_KEY` environment variable.

```bash
# Set credentials once via environment variable
export TAILSCALE_API_KEY="tskey-api-..."

# List all devices (includes node IDs for use with other commands)
tailscale devices

# Show detailed information for a single device
tailscale device nSRVBN3CNTRL

# Show subnet routes for a device
tailscale routes nSRVBN3CNTRL

# Authorize / deauthorize a device
tailscale authorize nSRVBN3CNTRL
tailscale deauthorize nSRVBN3CNTRL

# Delete a device from the tailnet
tailscale delete nSRVBN3CNTRL

# Expire a device's key (force re-authentication)
tailscale expire-key nSRVBN3CNTRL

# Enable or disable key expiry
tailscale set-key-expiry nSRVBN3CNTRL --disable
tailscale set-key-expiry nSRVBN3CNTRL --enable

# Rename a device
tailscale rename nSRVBN3CNTRL new-hostname

# Set ACL tags
tailscale set-tags nSRVBN3CNTRL tag:server tag:prod

# Set enabled subnet routes
tailscale set-routes nSRVBN3CNTRL 10.0.0.0/24 192.168.1.0/24

# Set Tailscale IPv4 address
tailscale set-ip nSRVBN3CNTRL 100.64.0.1

# DNS management
tailscale dns nameservers
tailscale dns set-nameservers 8.8.8.8 1.1.1.1
tailscale dns preferences
tailscale dns set-preferences --magic-dns
tailscale dns search-paths
tailscale dns set-search-paths corp.example.com
tailscale dns split

# List users and show user details
tailscale users
tailscale user u12345

# Tailnet settings
tailscale settings show
tailscale settings device-approval --enable
tailscale settings auto-updates --disable
tailscale settings key-duration 90
tailscale settings network-flow-logging --enable
tailscale settings external-tailnets admin

# List and manage auth keys
tailscale keys
tailscale delete-key k1234567890abcdef

# Dump raw API responses as JSON (useful for debugging/fixtures)
tailscale dump devices
tailscale dump device nSRVBN3CNTRL
tailscale dump routes nSRVBN3CNTRL
tailscale dump dns-nameservers
tailscale dump dns-preferences
tailscale dump dns-search-paths
tailscale dump dns-split
tailscale dump users
tailscale dump user u12345
tailscale dump settings
tailscale dump keys
tailscale dump key k1234567890abcdef
```

OAuth authentication is also supported via `--oauth-client-id` and
`--oauth-client-secret` (or the `TAILSCALE_OAUTH_CLIENT_ID` and
`TAILSCALE_OAUTH_CLIENT_SECRET` environment variables).

## Usage

The client is an async context manager; every API call is a coroutine. A
quick example that lists all devices in your tailnet:

```python
import asyncio

from tailscale import Tailscale


async def main() -> None:
    """Show example of using the Tailscale API client."""
    async with Tailscale(
        tailnet="frenck",
        api_key="tskey-somethingsomething",
    ) as tailscale:
        devices = await tailscale.devices()

        for device_id, device in devices.items():
            print(f"{device.hostname} ({device.os})")
            print(f"  Addresses: {', '.join(device.addresses)}")
            print(f"  Last seen: {device.last_seen}")
            print(f"  Update available: {device.update_available}")


if __name__ == "__main__":
    asyncio.run(main())
```

Each device returned is a `Device` dataclass with properties like `hostname`,
`os`, `addresses`, `authorized`, `client_version`, `last_seen`, `tags`,
`advertised_routes`, `enabled_routes`, and more. Devices are returned as a
dictionary keyed by device ID.

### Connection options

All constructor arguments except `tailnet` and `api_key` are optional:

```python
Tailscale(
    tailnet="your-tailnet",
    api_key="tskey-...",
    request_timeout=10,  # per-request timeout in seconds (default: 8)
)
```

You may also pass your own `aiohttp.ClientSession` via `session=...` to
share a connection pool across multiple clients.

## Changelog & Releases

This repository keeps a change log using [GitHub's releases][releases]
functionality. The format of the log is based on
[Keep a Changelog][keepchangelog].

Releases are based on [Semantic Versioning][semver], and use the format
of `MAJOR.MINOR.PATCH`. In a nutshell, the version will be incremented
based on the following:

- `MAJOR`: Incompatible or major changes.
- `MINOR`: Backwards-compatible new features and enhancements.
- `PATCH`: Backwards-compatible bugfixes and package updates.

## Contributing

This is an active open-source project. We are always open to people who want to
use the code or contribute to it.

We've set up a separate document for our
[contribution guidelines](CONTRIBUTING.md).

Thank you for being involved! :heart_eyes:

## Setting up development environment

This Python project is fully managed using the [Poetry][poetry] dependency
manager. But also relies on the use of NodeJS for certain checks during
development.

You need at least:

- Python 3.11+
- [Poetry][poetry-install]
- NodeJS 24+ (including NPM)

To install all packages, including all development requirements:

```bash
npm install
poetry install
```

As this repository uses the [prek][prek] framework, all changes
are linted and tested with each commit. You can run all checks and tests
manually, using the following command:

```bash
poetry run prek run --all-files
```

To run just the Python tests:

```bash
poetry run pytest
```

## Authors & contributors

The original setup of this repository is by [Franck Nijhof][frenck].

For a full list of all authors and contributors,
check [the contributor's page][contributors].

## Disclaimer

This project is an independent, community-driven effort and is **not
affiliated with, endorsed by, or supported by** Tailscale Inc. All product
names, trademarks, and registered trademarks are property of their respective
owners.

This library interacts with the [Tailscale API][tailscale-api], which is a
publicly documented interface. A valid API key, issued by Tailscale, is
required to use this library.

Use this software at your own risk. The authors are not responsible for any
consequences resulting from the use of this library, including but not limited
to unintended changes to your Tailscale network configuration.

## License

MIT License

Copyright (c) 2021-2026 Franck Nijhof

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

[build-shield]: https://github.com/frenck/python-tailscale/actions/workflows/tests.yaml/badge.svg
[build]: https://github.com/frenck/python-tailscale/actions/workflows/tests.yaml
[codecov-shield]: https://codecov.io/gh/frenck/python-tailscale/branch/main/graph/badge.svg
[codecov]: https://codecov.io/gh/frenck/python-tailscale
[contributors]: https://github.com/frenck/python-tailscale/graphs/contributors
[devcontainer-shield]: https://img.shields.io/static/v1?label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode
[devcontainer]: https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/frenck/python-tailscale
[frenck]: https://github.com/frenck
[github-sponsors-shield]: https://frenck.dev/wp-content/uploads/2019/12/github_sponsor.png
[github-sponsors]: https://github.com/sponsors/frenck
[keepchangelog]: https://keepachangelog.com/en/1.0.0/
[license-shield]: https://img.shields.io/github/license/frenck/python-tailscale.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[patreon-shield]: https://frenck.dev/wp-content/uploads/2019/12/patreon.png
[patreon]: https://www.patreon.com/frenck
[poetry-install]: https://python-poetry.org/docs/#installation
[poetry]: https://python-poetry.org
[prek]: https://github.com/j178/prek
[project-stage-shield]: https://img.shields.io/badge/project%20stage-production%20ready-brightgreen.svg
[pypi]: https://pypi.org/project/tailscale/
[python-versions-shield]: https://img.shields.io/pypi/pyversions/tailscale
[releases-shield]: https://img.shields.io/github/release/frenck/python-tailscale.svg
[releases]: https://github.com/frenck/python-tailscale/releases
[scorecard]: https://scorecard.dev/viewer/?uri=github.com/frenck/python-tailscale
[scorecard-shield]: https://api.scorecard.dev/projects/github.com/frenck/python-tailscale/badge
[semver]: https://semver.org/spec/v2.0.0.html
[tailscale-api]: https://tailscale.com/api
