"""Automation triggers for verified incoming Photon messages."""

from typing import Any, cast

import voluptuous as vol
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.helpers.trigger import Trigger, TriggerActionRunner, TriggerConfig
from homeassistant.helpers.typing import ConfigType

from .webhook import DOMAIN, EVENT_WEBHOOK

_SCHEMA = vol.Schema({vol.Required("target"): cv.TARGET_FIELDS})


class MessageReceivedTrigger(Trigger):
    """Trigger on inbound text messages for selected Photon notify entities."""

    @classmethod
    async def async_validate_config(
        cls, hass: HomeAssistant, config: ConfigType
    ) -> ConfigType:
        """Validate the entity target."""
        return cast(ConfigType, _SCHEMA(config))

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        super().__init__(hass, config)
        self._target = TargetSelection(config.target or {})

    async def async_attach_runner(
        self, run_action: TriggerActionRunner, did_not_trigger: Any = None
    ) -> CALLBACK_TYPE:
        """Listen only to verified project events and detach with the automation."""
        registry = er.async_get(self._hass)

        @callback
        def on_event(event: Event) -> None:
            payload = event.data.get("payload")
            if not isinstance(payload, dict) or payload.get("event") != "messages":
                return
            message = payload.get("message")
            if not isinstance(message, dict):
                return
            if (
                message.get("direction") != "inbound"
                or message.get("platform") != "imessage"
            ):
                return
            content = message.get("content")
            sender = message.get("sender")
            space = message.get("space")
            if (
                not isinstance(content, dict)
                or content.get("type") != "text"
                or not isinstance(content.get("text"), str)
                or not isinstance(sender, dict)
                or not isinstance(sender.get("id"), str)
                or not isinstance(space, dict)
            ):
                return
            selected = async_extract_referenced_entity_ids(self._hass, self._target)
            for entity_id in sorted(
                selected.referenced | selected.indirectly_referenced
            ):
                entity = registry.async_get(entity_id)
                if (
                    entity is None
                    or entity.domain != "notify"
                    or entity.platform != DOMAIN
                    or entity.config_entry_id is None
                ):
                    continue
                entry = self._hass.config_entries.async_get_entry(
                    entity.config_entry_id
                )
                if entry is None or entry.data["project_id"] != event.data.get(
                    "project_id"
                ):
                    continue
                run_action(
                    {
                        "entity_id": entity_id,
                        "project_id": event.data["project_id"],
                        "text": content["text"],
                        "sender": sender["id"],
                        "message_id": message.get("id"),
                        "space_id": space.get("id"),
                        "timestamp": message.get("timestamp"),
                    },
                    "iMessage received",
                    event.context,
                )

        return self._hass.bus.async_listen(EVENT_WEBHOOK, on_event)


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Expose the notify-targeted message trigger."""
    return {"message_received": MessageReceivedTrigger}
