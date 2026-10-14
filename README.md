<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/photon_spectrum/brand/dark_icon.png">
  <img src="custom_components/photon_spectrum/brand/icon.png" alt="Photon symbol" width="96">
</picture>

# Photon Spectrum for Home Assistant

A custom integration for [Photon Spectrum](https://photon.codes/docs/spectrum-ts/introduction) **shared-line iMessage** notifications. Each Photon project gets one `notify` entity, which sends a separate DM to each configured recipient by default. Only iMessage is supported here; use Home Assistant's existing integrations for other messaging channels where available. Signed Photon webhooks also support incoming-message automations. Dedicated lines and group messaging are not supported.

## Setup

### Install with HACS

This repository is not in HACS's default list. Add it as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/):

1. Install [HACS](https://www.hacs.xyz/docs/use/) if you haven't already.
2. In Home Assistant, open **HACS → ⋮ → Custom repositories**.
3. Enter `https://github.com/wingrunr21/hass-photon-spectrum`, select **Integration**, and click **Add**.
4. Find **Photon Spectrum** in HACS, click **Download**, and restart Home Assistant.

### Manual install

Copy `custom_components/photon_spectrum` into your Home Assistant `config/custom_components/` directory and restart Home Assistant.

### Configure

1. Create a project in your [Photon Dashboard](https://app.photon.codes/dashboard) and get its project ID and project secret. Also make sure you add your recipient phone numbers to the Users section of your project.
2. Go to **Settings → Devices & services → Add integration → Photon Spectrum**. Enter the project ID, project secret, and one or more `+`-prefixed phone numbers separated by commas (for example `+15551234567, +15557654321`). Use **Configure** to change the recipients later.

## Send a notification

You can use the `notify.send_message` action to send a notification:


```yaml
- action: notify.send_message
  target:
    entity_id: notify.photon_spectrum_imessage
  data:
    title: Home Assistant
    message: Front door opened
```

To override recipients for one message, use `data.target` to replace the configured recipients:

```yaml
- action: notify.photon_spectrum
  target:
    entity_id: notify.photon_spectrum_imessage
  data:
    title: Home Assistant
    message: Front door opened
    target:
      - "+15551234567"
      - "+15557654321"
```

## Receive signed webhooks

In **Settings → Devices & services → Photon Spectrum → Configure**, copy the project's **Webhook path** (`/api/webhook/...`) shown above the fields and append it to the public HTTPS URL that reaches your Home Assistant (Nabu Casa or your own reverse proxy).

Register that URL in the [Photon webhook dashboard](https://photon.codes/docs/webhooks/managing-webhooks). Upon registration, Photon will show a separate 64-character signing secret. In **Settings → Devices & services → Photon Spectrum → Configure**, paste that secret into **Webhook signing secret**. Leave it blank when changing recipients to keep the saved secret; check **Disable webhook** to remove it.

The webhook path remains visible even when reception is disabled. Disabling the webhook does not delete the webhook in your Photon project; delete or disable it there to stop delivery attempts. Home Assistant may acknowledge an unregistered webhook with HTTP 200 without processing it.

### Trigger on incoming messages

On Home Assistant versions supporting integration-specific triggers (confirmed on 2026.9.4+), choose **Add trigger → By target → your Photon iMessage notify entity → iMessage received**.

Alternatively, paste this example into the automation editor's **Edit in YAML** view. Replace both occurrences of `notify.imessage` with your project's notify entity ID.

```yaml
alias: Photon - Message Received
description: ''
triggers:
  - trigger: photon_spectrum.message_received
    target:
      entity_id: notify.imessage
conditions: []
actions:
  - action: logbook.log
    data:
      name: Photon
      message: '{{ trigger.sender }}: {{ trigger.text }}'
      entity_id: notify.imessage
mode: single
```

The action's `entity_id` associates the log entry with the iMessage entity, so it appears in that entity's activity view as well as the main Activity/Logbook view.

The trigger exposes `entity_id`, `project_id`, `text`, `sender`, `message_id`, `space_id`, and `timestamp` directly on `trigger`. It handles only inbound iMessage text messages; outbound messages, attachments, and other webhook events do not fire it. Identical messages still trigger separately. Message data stays out of entity state, but Home Assistant's recorder can store raw webhook events, and automation traces and actions may record message content and sender phone numbers.

This Home Assistant trigger API is still experimental and may change. If the trigger is unavailable on your version, use the raw event below instead.

### Raw webhook events

Verified deliveries fire a `photon_spectrum_webhook` Home Assistant event. Use an event trigger, not a stock webhook trigger, to access `trigger.event.data.payload`:

```yaml
triggers:
  - trigger: event
    event_type: photon_spectrum_webhook
    event_data:
      project_id: "<your Photon project UUID>"
actions:
  - action: logbook.log
    data:
      name: Photon Spectrum
      message: "{{ trigger.event.data.payload.event }}"
```

The handler checks the exact request bytes, Photon's signature, and a five-minute timestamp window before firing the event. Bad signatures never reach automations. A valid request may still be replayed within that window, so make side-effecting automations idempotent if duplicates matter. Rotate a leaked secret by deleting and re-registering the Photon webhook, then updating the signing secret in **Configure**. Do not use the Photon project secret in this field.

## Troubleshooting

If a registered user gets `PERMISSION_DENIED: [spectrum-imessage] Target not allowed for this project`, ask them to text their assigned Photon shared-line number first, then retry. This [resolved the rejection in our test](https://agents.stackoverflow.com/tils/2d818b69-8773-4f7c-b0e6-08b6101479cc) even though the user was already registered. If it still fails, compare their iMessage handle with [Photon's debug line](https://debug.photon.codes) and ask Photon support to inspect the project's outbound policy.

## Developing

### Docker test instance

```sh
docker compose up -d
```

Visit http://localhost:8123 to complete onboarding. Docker bind-mounts `custom_components` and keeps Home Assistant state in `.hass-config/` (ignored by Git). Restart after changing Python or the manifest:

```sh
docker compose restart homeassistant
docker compose logs -f homeassistant
```

After changing `strings.json`, restart and refresh the browser. `docker compose down` stops the container without removing `.hass-config/`.

### Checks

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

The protobuf files in `custom_components/photon_spectrum/proto/` are a minimal projection of [Photon's published iMessage schema](https://buf.build/photon-hq/imessage) pinned to the revision named in `message.proto`. Regenerate the Python bindings with `grpcio-tools==1.75.1` when updating that contract:

```sh
.venv/bin/python -m grpc_tools.protoc -Icustom_components/photon_spectrum --python_out=custom_components/photon_spectrum --pyi_out=custom_components/photon_spectrum custom_components/photon_spectrum/proto/message.proto
```

This integration is not affiliated with or endorsed by Photon. Its iMessage send path is a Python port of [Photon's TypeScript Spectrum SDK](https://github.com/photon-hq/spectrum-ts), not the full SDK.
