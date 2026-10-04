"""Photon Spectrum notification target."""

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Add the project's notification entity."""
    async_add_entities([PhotonNotifyEntity(entry)])


class PhotonNotifyEntity(NotifyEntity):
    """Deliver Home Assistant notifications to the project's recipients."""

    _attr_has_entity_name = True
    _attr_name = "iMessage"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, entry: ConfigEntry) -> None:
        self._client = entry.runtime_data
        self._recipients = entry.options.get(
            "recipients", entry.data["recipients"]
        )
        self._attr_unique_id = f"{entry.entry_id}_notify"

    async def async_send_message(
        self, message: str, title: str | None = None, target: list[str] | None = None
    ) -> None:
        """Send a separate DM to each chosen recipient."""
        text = f"{title}\n{message}" if title else message
        recipients = (
            list(dict.fromkeys(target)) if target is not None else self._recipients
        )
        errors: list[HomeAssistantError] = []
        for recipient in recipients:
            try:
                await self._client.send(recipient, text)
            except HomeAssistantError as err:
                errors.append(err)
        if errors:
            raise HomeAssistantError(
                f"Photon send failed for {len(errors)} of "
                f"{len(recipients)} recipients: {errors[0]}"
            ) from errors[0]
