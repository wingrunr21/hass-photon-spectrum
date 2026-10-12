"""Photon Spectrum notification integration."""

from functools import partial

import voluptuous as vol
from homeassistant.components import webhook as ha_webhook
from homeassistant.components.notify import DATA_COMPONENT, NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from .client import SharedLineClient
from .config_flow import RECIPIENT
from .notify import PhotonNotifyEntity
from .webhook import async_handle_webhook, webhook_id

DOMAIN = "photon_spectrum"
WEBHOOK_ENTRIES = f"{DOMAIN}_webhook_entries"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a shared-line notification target."""
    if not hass.data.get(DOMAIN) and hass.services.has_service("notify", DOMAIN):
        raise HomeAssistantError("notify.photon_spectrum is already registered")
    entry.runtime_data = SharedLineClient(
        hass,
        entry.data["project_id"],
        entry.data["project_secret"],
    )
    registered = False
    try:
        if entry.options.get("webhook_signing_secret"):
            ha_webhook.async_register(
                hass,
                DOMAIN,
                "Photon Spectrum",
                webhook_id(entry),
                partial(async_handle_webhook, entry=entry),
                local_only=False,
                allowed_methods=("POST",),
            )
            registered = True
            hass.data.setdefault(WEBHOOK_ENTRIES, set()).add(entry.entry_id)
        await hass.config_entries.async_forward_entry_setups(entry, ["notify"])
    except Exception:
        if registered:
            _unregister_webhook(hass, entry)
        await entry.runtime_data.close()
        raise
    active = hass.data.setdefault(DOMAIN, set())
    if not active:
        hass.data[DATA_COMPONENT].async_register_entity_service(
            DOMAIN,
            {
                vol.Required("message"): cv.string,
                vol.Optional("title"): cv.string,
                vol.Optional("target"): vol.All(
                    cv.ensure_list, [vol.Match(RECIPIENT.pattern)], vol.Length(min=1)
                ),
            },
            async_send_photon,
        )
        service.async_set_service_schema(
            hass,
            "notify",
            DOMAIN,
            {
                "name": "Send Photon Spectrum message",
                "description": "Send using project defaults or override recipients.",
                "target": {"entity": {"domain": "notify", "integration": DOMAIN}},
                "fields": {
                    "message": {"required": True, "selector": {"text": {}}},
                    "title": {"selector": {"text": {}}},
                    "target": {"selector": {"object": {}}},
                },
            },
        )
    active.add(entry.entry_id)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the target and its connection."""
    if not await hass.config_entries.async_unload_platforms(entry, ["notify"]):
        return False
    _unregister_webhook(hass, entry)
    await entry.runtime_data.close()
    active = hass.data[DOMAIN]
    active.remove(entry.entry_id)
    if not active:
        hass.services.async_remove("notify", DOMAIN)
        hass.data.pop(DOMAIN)
    return True


async def async_send_photon(entity: NotifyEntity, call: ServiceCall) -> None:
    """Send through the selected Photon notification entity."""
    if not isinstance(entity, PhotonNotifyEntity):
        raise HomeAssistantError("Target must be a Photon Spectrum notify entity")
    await entity._async_send_message(
        message=call.data["message"],
        title=call.data.get("title"),
        target=call.data.get("target"),
    )


def _unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove only a webhook this integration successfully registered."""
    owned = hass.data.get(WEBHOOK_ENTRIES)
    if not owned or entry.entry_id not in owned:
        return
    ha_webhook.async_unregister(hass, webhook_id(entry))
    owned.remove(entry.entry_id)
    if not owned:
        hass.data.pop(WEBHOOK_ENTRIES)


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the notification target when recipients change."""
    await hass.config_entries.async_reload(entry.entry_id)
