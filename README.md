<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/photon_spectrum/brand/dark_icon.png">
  <img src="custom_components/photon_spectrum/brand/icon.png" alt="Photon symbol" width="96">
</picture>

# Photon Spectrum for Home Assistant

A custom integration for [Photon Spectrum](https://photon.codes/docs/spectrum-ts/introduction) **shared-line iMessage** notifications. Each Photon project gets one `notify` entity, which sends a separate DM to each configured recipient by default. Only iMessage is supported here; use Home Assistant's existing integrations for other messaging channels where available. Dedicated lines, groups, and incoming messages are not supported.

## Setup

### Install with HACS

This repository is not in HACS's default list. Add it as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) once it is public on GitHub:

1. Install [HACS](https://www.hacs.xyz/docs/use/) if you haven't already.
2. In Home Assistant, open **HACS → ⋮ → Custom repositories**.
3. Enter `https://github.com/wingrunr21/hass-photon-spectrum`, select **Integration**, and click **Add**.
4. Find **Photon Spectrum** in HACS, click **Download**, and restart Home Assistant.

### Manual install

Copy `custom_components/photon_spectrum` into your Home Assistant `config/custom_components/` directory and restart Home Assistant. The Docker test instance below already mounts the integration.

### Configure

1. Create a Photon project with a shared cloud iMessage line and get its project ID and project secret.
2. Go to **Settings → Devices & services → Add integration → Photon Spectrum**. Enter the project ID, project secret, and one or more `+`-prefixed phone numbers separated by commas (for example `+15551234567, +15557654321`). Use **Configure** to change the recipients later.

## Send a notification

In **Developer tools → Actions**, call `notify.send_message` targeting your Photon Spectrum notify entity. Example automation action:

```yaml
- action: notify.send_message
  target:
    entity_id: notify.photon_spectrum_imessage
  data:
    title: Home Assistant
    message: Front door opened
```

To override recipients for one message, call `notify.photon_spectrum` on the project's notify entity. `data.target` replaces the configured recipients; omit it to use the defaults:

```yaml
- action: notify.photon_spectrum
  target:
    entity_id: notify.photon_spectrum_imessage
  data:
    message: Front door opened
    target:
      - "+15551234567"
      - "+15557654321"
```

Phone numbers must use international `+` format; an empty or invalid override is rejected.

Use the entity ID shown by Home Assistant; it may differ from the examples. A title appears above the message on its own line. The integration attempts every recipient before reporting failures; successful sends are not rolled back.

Photon shared lines only send to recipients registered as shared users of the same project and reachable through iMessage. Home Assistant stores the project credentials in its config entry storage, so protect your configuration and backups.

If a registered user gets `PERMISSION_DENIED: [spectrum-imessage] Target not allowed for this project`, ask them to text their assigned Photon shared-line number first, then retry. This [resolved the rejection in our test](https://agents.stackoverflow.com/tils/2d818b69-8773-4f7c-b0e6-08b6101479cc) even though the user was already registered. If it still fails, compare their iMessage handle with [Photon's debug line](https://debug.photon.codes) and ask Photon support to inspect the project's outbound policy.

## Docker test instance

```sh
docker compose up -d
```

Visit http://localhost:8123 to complete onboarding. Docker bind-mounts `custom_components` and keeps Home Assistant state in `.hass-config/` (ignored by Git). Restart after changing Python or the manifest:

```sh
docker compose restart homeassistant
docker compose logs -f homeassistant
```

After changing `strings.json`, restart and refresh the browser. `docker compose down` stops the container without removing `.hass-config/`.

## Checks

For local unit checks (Python 3.13):

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python homeassistant 'grpcio==1.75.1' 'protobuf>=6.31.1,<7' pytest
.venv/bin/python -m pytest -q tests/
```

To compare this send path with Photon's pinned TypeScript SDK (Node.js and npm required, no Photon credentials):

```sh
npm ci --prefix tests/sdk_parity
.venv/bin/python -m pytest -q tests/sdk_parity/parity.py
```

The comparison checks token requests, shared DM GUIDs, and the published gRPC request fields. It does not test live delivery or Photon's recipient policy.

The [SDK parity workflow](.github/workflows/sdk-parity.yml) runs daily at 07:17 UTC and can also be started manually. It installs the latest published Photon packages without changing the local lockfile, so SDK releases can expose drift.

The protobuf files in `custom_components/photon_spectrum/proto/` are a minimal projection of [Photon's published iMessage schema](https://buf.build/photon-hq/imessage) pinned to the revision named in `message.proto`. Regenerate the Python bindings with `grpcio-tools==1.75.1` when updating that contract:

```sh
.venv/bin/python -m grpc_tools.protoc -Icustom_components/photon_spectrum --python_out=custom_components/photon_spectrum --pyi_out=custom_components/photon_spectrum custom_components/photon_spectrum/proto/message.proto
```

This integration is not affiliated with or endorsed by Photon. Its iMessage send path is a Python port of [Photon's TypeScript Spectrum SDK](https://github.com/photon-hq/spectrum-ts), not the full SDK.

The icons in `custom_components/photon_spectrum/brand/` use [Photon's Symbol](https://photon.codes/brand) (© Photon) for identification. Home Assistant 2026.3+ loads them locally.

