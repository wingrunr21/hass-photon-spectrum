"""Notify-targeted triggers flatten verified inbound messages without extra entities."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers.trigger import TriggerConfig

from custom_components.photon_spectrum.trigger import MessageReceivedTrigger
from custom_components.photon_spectrum.webhook import EVENT_WEBHOOK


def test_message_received_trigger(tmp_path):
    async def check():
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = MagicMock()
        hass.config_entries.async_get_entry.return_value = SimpleNamespace(
            data={"project_id": "project-one"}
        )
        registry = MagicMock()
        registry.async_get.return_value = SimpleNamespace(
            domain="notify", platform="photon_spectrum", config_entry_id="entry-one"
        )
        trigger = MessageReceivedTrigger(
            hass,
            TriggerConfig(
                key="photon_spectrum.message_received",
                target={"entity_id": "notify.imessage"},
            ),
        )
        config = await trigger.async_validate_config(
            hass, {"target": {"entity_id": "notify.imessage"}}
        )
        assert config["target"]["entity_id"] == ["notify.imessage"]
        with pytest.raises(vol.Invalid):
            await trigger.async_validate_config(hass, {})
        runner = MagicMock()
        message = {
            "direction": "inbound",
            "platform": "imessage",
            "id": "message-one",
            "timestamp": "2026-10-11T19:03:21.121Z",
            "content": {"type": "text", "text": "Test"},
            "sender": {"id": "+15551234567"},
            "space": {"id": "any;-;+15551234567"},
        }
        data = {
            "project_id": "project-one",
            "payload": {"event": "messages", "message": message},
        }
        with (
            patch(
                "custom_components.photon_spectrum.trigger.er.async_get",
                return_value=registry,
            ),
            patch(
                "custom_components.photon_spectrum.trigger.async_extract_referenced_entity_ids",
                return_value=SimpleNamespace(
                    referenced={"notify.imessage"}, indirectly_referenced=set()
                ),
            ),
        ):
            remove = await trigger.async_attach_runner(runner)
            for _ in range(2):
                hass.bus.async_fire(EVENT_WEBHOOK, data)
                await hass.async_block_till_done()
            assert runner.call_count == 2
            assert runner.call_args.args[0] == {
                "entity_id": "notify.imessage",
                "project_id": "project-one",
                "text": "Test",
                "sender": "+15551234567",
                "message_id": "message-one",
                "space_id": "any;-;+15551234567",
                "timestamp": "2026-10-11T19:03:21.121Z",
            }
            for field, value in [
                ("direction", "outbound"),
                ("platform", "sms"),
                ("content", None),
                ("sender", None),
                ("space", None),
            ]:
                invalid = deepcopy(data)
                invalid["payload"]["message"][field] = value
                hass.bus.async_fire(EVENT_WEBHOOK, invalid)
            hass.bus.async_fire(
                EVENT_WEBHOOK, {**data, "project_id": "another-project"}
            )
            hass.bus.async_fire(EVENT_WEBHOOK, {"payload": []})
            await hass.async_block_till_done()
            assert runner.call_count == 2
            registry.async_get.return_value.platform = "other_integration"
            hass.bus.async_fire(EVENT_WEBHOOK, data)
            await hass.async_block_till_done()
            assert runner.call_count == 2
            remove()
            registry.async_get.return_value.platform = "photon_spectrum"
            hass.bus.async_fire(EVENT_WEBHOOK, data)
            await hass.async_block_till_done()
            assert runner.call_count == 2

    asyncio.run(check())
