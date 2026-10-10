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
the terminal. The command is `tailscale-api`, so it does not clash with the
`tailscale` command of the official Tailscale client. The `--api-key` option
can also be set via the `TAILSCALE_API_KEY` environment variable.

```bash
# Set credentials once via environment variable
export TAILSCALE_API_KEY="tskey-api-..."

# List all devices (includes node IDs for use with other commands)
tailscale-api devices

# Show detailed information for a single device
tailscale-api device nSRVBN3CNTRL

# Show subnet routes for a device
tailscale-api routes nSRVBN3CNTRL

# Authorize / deauthorize a device
tailscale-api authorize nSRVBN3CNTRL
tailscale-api deauthorize nSRVBN3CNTRL

# Delete a device from the tailnet
tailscale-api delete nSRVBN3CNTRL

# Expire a device's key (force re-authentication)
tailscale-api expire-key nSRVBN3CNTRL

# Enable or disable key expiry
tailscale-api set-key-expiry nSRVBN3CNTRL --disable
tailscale-api set-key-expiry nSRVBN3CNTRL --enable

# Rename a device
tailscale-api rename nSRVBN3CNTRL new-hostname

# Set ACL tags
tailscale-api set-tags nSRVBN3CNTRL tag:server tag:prod

# Set enabled subnet routes
tailscale-api set-routes nSRVBN3CNTRL 10.0.0.0/24 192.168.1.0/24

# Set Tailscale IPv4 address
tailscale-api set-ip nSRVBN3CNTRL 100.64.0.1

# DNS management
tailscale-api dns nameservers
tailscale-api dns set-nameservers 8.8.8.8 1.1.1.1
tailscale-api dns preferences
tailscale-api dns set-preferences --magic-dns
tailscale-api dns search-paths
tailscale-api dns set-search-paths corp.example.com
tailscale-api dns split

# List users and show user details
tailscale-api users
tailscale-api user u12345

# Tailnet settings
tailscale-api settings show
tailscale-api settings device-approval --enable
tailscale-api settings auto-updates --disable
tailscale-api settings key-duration 90
tailscale-api settings network-flow-logging --enable
tailscale-api settings external-tailnets admin
tailscale-api settings https --enable
tailscale-api settings route-selection regional-routing

# Edit the policy file (HuJSON, comments included). The ETag makes sure it is
# not set when someone else changed it in the meantime.
ETAG="$(tailscale-api policy show --etag)"
tailscale-api policy show > policy.hujson
tailscale-api policy validate policy.hujson
tailscale-api policy set policy.hujson --etag "$ETAG"

# List webhooks and Services, and the configuration changes of the last day
tailscale-api webhooks
tailscale-api services
tailscale-api audit-logs --hours 24

# List and manage auth keys
tailscale-api keys
tailscale-api delete-key k1234567890abcdef

# Dump raw API responses as JSON (useful for debugging/fixtures)
tailscale-api dump devices
tailscale-api dump device nSRVBN3CNTRL
tailscale-api dump routes nSRVBN3CNTRL
tailscale-api dump device-posture-attributes nSRVBN3CNTRL
tailscale-api dump device-invites nSRVBN3CNTRL
tailscale-api dump dns-configuration
tailscale-api dump dns-nameservers
tailscale-api dump dns-preferences
tailscale-api dump dns-search-paths
tailscale-api dump dns-split
tailscale-api dump users
tailscale-api dump user u12345
tailscale-api dump user-invites
tailscale-api dump keys
tailscale-api dump key k1234567890abcdef
tailscale-api dump settings
tailscale-api dump policy
tailscale-api dump webhooks
tailscale-api dump services
tailscale-api dump service svc:example
tailscale-api dump service-hosts svc:example
tailscale-api dump posture-integrations
tailscale-api dump oauth-apps
tailscale-api dump contacts
tailscale-api dump organization-tailnets
tailscale-api dump audit-logs --hours 24
tailscale-api dump network-logs --hours 1
tailscale-api dump log-stream network
tailscale-api dump log-stream-status configuration
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
    async with Tailscale(api_key="tskey-api-...") as tailscale:
        devices = await tailscale.devices()

        for device in devices.values():
            print(f"{device.hostname} ({device.os})")
            print(f"  Addresses: {', '.join(device.addresses)}")
            print(f"  Last seen: {device.last_seen}")


if __name__ == "__main__":
    asyncio.run(main())
```

The client covers the whole [Tailscale API][tailscale-api]. The sections below
show the main parts; every method has a docstring with the details.

### Authentication

Use an API access token, or the credentials of an OAuth client. API access
tokens expire after at most 90 days; OAuth clients do not. With an OAuth
client, the client gets short-lived access tokens itself, and gets a new one
before the current one expires.

```python
# With an API access token
Tailscale(api_key="tskey-api-...")

# With an OAuth client
Tailscale(
    oauth_client_id="...",
    oauth_client_secret="tskey-client-...",
)
```

To keep the access token of an OAuth client across restarts, pass a
`token_storage`: an implementation of `TokenStorage`, with a `get_token()`
and a `set_token()` method.

The `tailnet` defaults to `"-"`, the tailnet of the credentials. Pass the
tailnet ID to use another tailnet the credentials have access to.

### Devices

Each device is a `Device` dataclass with properties like `hostname`, `os`,
`addresses`, `authorized`, `client_version`, `last_seen`, `tags`,
`advertised_routes`, `enabled_routes`, `distro`, and more. `devices()`
returns them as a dictionary keyed by device ID.

Only the identifiers (`device_id`, `node_id`, `hostname`, and `name`) are
always set. The API leaves out many fields for devices shared in from another
tailnet, so the other fields are `None` when the API does not return them.

```python
async with Tailscale(api_key="tskey-api-...") as tailscale:
    device = await tailscale.device("nSRVBN3CNTRL")

    await tailscale.authorize_device(device.node_id, authorized=True)
    await tailscale.rename_device(device.node_id, name="server")
    await tailscale.set_device_tags(device.node_id, tags=["tag:server"])

    routes = await tailscale.device_routes(device.node_id)
    await tailscale.set_device_routes(
        device.node_id, routes=routes.advertised_routes
    )

    # Share the device with someone outside of the tailnet
    invite = await tailscale.create_device_invite(
        device.node_id, email="alice@example.com"
    )
```

Custom posture attributes of devices are set with
`set_device_posture_attribute()`, or for several devices at once with
`update_device_posture_attributes()`.

### Users and keys

```python
async with Tailscale(api_key="tskey-api-...") as tailscale:
    admins = await tailscale.users(role="admin")
    invite = await tailscale.create_user_invite(role="member")

    # An auth key, to add devices to the tailnet
    key = await tailscale.create_key(
        description="CI runners",
        reusable=True,
        ephemeral=True,
        tags=["tag:ci"],
    )
    print(key.key)

    # An OAuth client, which does not expire
    client = await tailscale.create_key(
        key_type="client",
        description="Monitoring",
        scopes=["devices:core:read"],
    )
    print(client.key_id, client.key)
```

The secret of a new key is only returned when it is created.

### Tailnet settings and DNS

```python
async with Tailscale(api_key="tskey-api-...") as tailscale:
    settings = await tailscale.tailnet_settings()
    await tailscale.update_tailnet_settings(devices_approval_on=True)

    configuration = await tailscale.dns_configuration()
    configuration.search_paths.append("corp.example.com")
    await tailscale.set_dns_configuration(configuration)
```

Next to the full DNS configuration, the nameservers, preferences, search
paths, and split DNS have their own methods too.

### Policy file

The policy file is kept as HuJSON, so its comments and formatting survive a
round trip. Pass along its ETag when setting it, so it is not set when someone
else changed it in the meantime.

```python
async with Tailscale(api_key="tskey-api-...") as tailscale:
    policy_file = await tailscale.policy_file()
    policy = policy_file.policy.replace("tag:old", "tag:new")

    validation = await tailscale.validate_policy_file(policy)
    if validation.valid:
        await tailscale.set_policy_file(policy, etag=policy_file.etag)
    else:
        print(validation.message)
```

`test_policy_file()` runs tests against the current policy file, and
`preview_policy_rules()` shows which rules apply to a user or an address.

### Webhooks, Services, and logs

```python
from datetime import UTC, datetime, timedelta

async with Tailscale(api_key="tskey-api-...") as tailscale:
    webhook = await tailscale.create_webhook(
        endpoint_url="https://example.com/tailscale",
        subscriptions=["nodeCreated", "nodeNeedsApproval"],
    )
    print(webhook.secret)

    services = await tailscale.services()

    end = datetime.now(UTC)
    logs = await tailscale.configuration_audit_logs(
        start=end - timedelta(days=1), end=end, events=["NODE.CREATE"]
    )
```

There is more: network flow logs, log streaming, posture integrations, OAuth
apps, the contacts of the tailnet, and the tailnets of an organization.

### Error handling

All errors are a `TailscaleError`:

- `TailscaleConnectionError`: the API could not be reached, or did not answer
  in time.
- `TailscaleAuthenticationError`: the credentials are missing or refused.
  `TailscaleUnauthorizedError` (HTTP 401) means the credentials are invalid,
  and `TailscalePermissionError` (HTTP 403) that they lack the permission, or
  that the billing plan of the tailnet lacks the feature.
- `TailscaleNotFoundError`: the device, user, or other resource does not
  exist.
- `TailscaleResponseError`: the API responded with another error.

The response errors have the HTTP `status`, and the `reason` the API gave:

```python
from tailscale import TailscalePermissionError

try:
    await tailscale.network_flow_logs(start=start, end=end)
except TailscalePermissionError as err:
    print(err.status, err.reason)
```

### Connection options

All constructor arguments are optional, apart from the credentials:

```python
Tailscale(
    api_key="tskey-api-...",
    tailnet="-",  # the tailnet of the credentials (default)
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
poetry install --all-extras
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
